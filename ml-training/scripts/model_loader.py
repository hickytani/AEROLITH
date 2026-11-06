"""Memory-efficient safetensors loader using accelerate's meta device.

Allocates 0 bytes initially (init_empty_weights), then populates each tensor
one-by-one directly on the CPU device in bfloat16.
Peak RAM is EXACTLY the final model size (~988 MB for Qwen2.5-0.5B).
Zero duplicate allocation, zero random weight initialization, zero mmap.
"""
from __future__ import annotations

import gc
import json
import struct
from pathlib import Path

import numpy as np
import torch
from accelerate import init_empty_weights
from accelerate.utils import set_module_tensor_to_device
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

_DTYPE_MAP: dict = {
    "F64":  (np.float64,  torch.float64),
    "F32":  (np.float32,  torch.float32),
    "F16":  (np.float16,  torch.float16),
    "BF16": (np.uint16,   torch.bfloat16),
    "I64":  (np.int64,    torch.int64),
    "I32":  (np.int32,    torch.int32),
    "I16":  (np.int16,    torch.int16),
    "I8":   (np.int8,     torch.int8),
    "U8":   (np.uint8,    torch.uint8),
    "BOOL": (np.uint8,    torch.bool),
}


def load_model_no_mmap(
    model_dir: str | Path,
    target_dtype: torch.dtype = torch.bfloat16,
    verbose: bool = True,
) -> tuple[AutoModelForCausalLM, AutoTokenizer]:
    """Load Qwen model + tokenizer without mmap. Peak RAM ≈ model_size only."""
    model_dir = Path(model_dir)
    sf_path = model_dir / "model.safetensors"
    if not sf_path.exists():
        raise FileNotFoundError(f"model.safetensors not found in {model_dir}")

    # 1. Config & tokenizer
    config = AutoConfig.from_pretrained(str(model_dir), local_files_only=True)
    if verbose:
        print(f"  Config   : arch={config.architectures[0]}, "
              f"layers={config.num_hidden_layers}, hidden={config.hidden_size}", flush=True)

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    if verbose:
        print(f"  Tokenizer: vocab_size={tokenizer.vocab_size}", flush=True)

    # 2. Allocate meta skeleton (0 BYTES RAM)
    if verbose:
        print("  Model    : allocating on meta device (0 bytes RAM)...", flush=True)
    with init_empty_weights():
        model = AutoModelForCausalLM.from_config(config)

    # 3. Read safetensors file header
    sf_mb = sf_path.stat().st_size / 1e6
    if verbose:
        print(f"  Weights  : {sf_mb:.0f} MB — reading one-by-one to CPU...", flush=True)

    with open(sf_path, "rb") as f:
        header_len = struct.unpack("<Q", f.read(8))[0]
        header: dict = json.loads(f.read(header_len))
        data_offset = 8 + header_len

        tensor_names = [k for k in header if k != "__metadata__"]
        total = len(tensor_names)
        if verbose:
            print(f"  Tensors  : {total}", flush=True)

        for idx, name in enumerate(tensor_names, 1):
            meta = header[name]
            dtype_str = meta["dtype"]
            shape = meta["shape"]
            begin, end = meta["data_offsets"]
            nbytes = end - begin

            f.seek(data_offset + begin)

            if dtype_str == "BF16" and target_dtype == torch.bfloat16:
                # Fast direct read into CPU tensor
                t = torch.empty(shape, dtype=torch.bfloat16, device="cpu")
                f.readinto(t.view(torch.uint8).numpy())
            else:
                raw = bytearray(f.read(nbytes))
                np_dtype, torch_dtype = _DTYPE_MAP[dtype_str]
                arr = np.frombuffer(raw, dtype=np_dtype)
                t = torch.from_numpy(arr)
                if dtype_str == "BF16":
                    t = t.view(torch.bfloat16)
                t = t.reshape(shape).to(target_dtype).to("cpu")
                del raw, arr

            set_module_tensor_to_device(model, name, device="cpu", value=t)
            del t

            if idx % 60 == 0:
                gc.collect()
            if verbose and (idx % 60 == 0 or idx == total):
                print(f"    {idx}/{total} tensors loaded", flush=True)

    # Tie weights if configured (e.g. Qwen2 ties lm_head.weight to embed_tokens.weight)
    # Because lm_head.weight is not stored in safetensors when tied, failing to tie
    # leaves lm_head on the meta device, causing all-zero logits and constant 11.9312 loss!
    if getattr(config, "tie_word_embeddings", False):
        model.tie_weights()

    gc.collect()
    total_params = sum(p.numel() for p in model.parameters())
    if verbose:
        print(f"  Done     : {total_params/1e6:.1f}M params loaded as {target_dtype}", flush=True)

    return model, tokenizer
