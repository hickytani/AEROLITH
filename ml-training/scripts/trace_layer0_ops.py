import sys
from pathlib import Path
import json
import torch

REPO_ROOT = Path('.').resolve()
sys.path.insert(0, str(REPO_ROOT / 'ml-training/scripts'))
from model_loader import load_model_no_mmap
from transformers import AutoTokenizer

MODEL_PATH = Path(r'C:\Users\prasu\.cache\hf_direct\Qwen2.5-0.5B-Instruct')
model, tok = load_model_no_mmap(MODEL_PATH, target_dtype=torch.bfloat16, verbose=False)

messages = [
    {"role": "system", "content": "You are AEROLITH's engineering parameter extraction and constraint model."},
    {"role": "user", "content": "External spur pair with 18 pinion teeth"},
    {"role": "assistant", "content": '{"pinion_teeth": 18}'},
]
rendered = tok.apply_chat_template(messages, tokenize=False)
enc = tok(rendered, return_tensors="pt")
input_ids = enc["input_ids"]

seq_len = input_ids.shape[1]
print("seq_len:", seq_len)

# Run model with forward hooks on EVERY submodule of layer 0!
l0 = model.model.layers[0]

def make_hook(name):
    def hook(m, inp, outp):
        t = outp[0] if isinstance(outp, tuple) else outp
        if torch.is_tensor(t):
            # check positions 0, 1, 2, 3, 4, 5
            for p in range(min(8, t.shape[1] if t.dim() > 1 else 1)):
                slice_p = t[:, p] if t.dim() > 1 else t
                fin = torch.isfinite(slice_p).all().item()
                nan = torch.isnan(slice_p).any().item()
                zero = (slice_p == 0).all().item()
                print(f"  [{name}] pos {p}: fin={fin} nan={nan} zero={zero}")
    return hook

l0.input_layernorm.register_forward_hook(make_hook("ln1"))
l0.self_attn.q_proj.register_forward_hook(make_hook("q_proj"))
l0.self_attn.k_proj.register_forward_hook(make_hook("k_proj"))
l0.self_attn.v_proj.register_forward_hook(make_hook("v_proj"))
l0.self_attn.o_proj.register_forward_hook(make_hook("o_proj"))
l0.self_attn.register_forward_hook(make_hook("self_attn"))
l0.post_attention_layernorm.register_forward_hook(make_hook("ln2"))
l0.mlp.gate_proj.register_forward_hook(make_hook("gate_proj"))
l0.mlp.up_proj.register_forward_hook(make_hook("up_proj"))
l0.mlp.down_proj.register_forward_hook(make_hook("down_proj"))
l0.mlp.register_forward_hook(make_hook("mlp"))
l0.register_forward_hook(make_hook("layer0"))

with torch.no_grad():
    out = model(input_ids=input_ids)
