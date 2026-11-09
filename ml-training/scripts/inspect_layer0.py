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

with open('data/learning/engineering-v2.2.0/train.jsonl', 'r', encoding='utf-8') as f:
    sample = json.loads(f.readline())

system_msg = "You are AEROLITH's engineering parameter extraction and constraint model."
messages = [
    {"role": "system", "content": system_msg},
    {"role": "user", "content": sample["input"]},
    {"role": "assistant", "content": json.dumps(sample["expected_output"])},
]

rendered = tok.apply_chat_template(messages, tokenize=False)
enc = tok(rendered, return_tensors="pt")
input_ids = enc["input_ids"]

print(f"Sequence length: {input_ids.shape[1]}")

# Hook into layer 0 components:
l0 = model.model.layers[0]

def inspect_tensor(name, t):
    if isinstance(t, tuple):
        t = t[0]
    for pos in [0, 1, 2, 3, 4, 5, 6, 10]:
        row = t[0, pos].float()
        fin = torch.isfinite(row).all().item()
        nan = torch.isnan(row).any().item()
        zero = (row == 0).all().item()
        norm = row.norm().item()
        print(f"  {name} Pos {pos:2d}: fin={fin} nan={nan} zero={zero} norm={norm:.4f}")

h = model.model.embed_tokens(input_ids)
print("\n--- Embed Tokens ---")
inspect_tensor("emb", h)

# Check attention
pos_ids = torch.arange(input_ids.shape[1]).unsqueeze(0)
rotary = model.model.rotary_emb(h, pos_ids)
cos, sin = rotary
print(f"cos shape: {cos.shape}, fin={torch.isfinite(cos).all().item()}, zero={(cos==0).all().item()}")

norm_h = l0.input_layernorm(h)
print("\n--- After Input Layernorm ---")
inspect_tensor("ln1", norm_h)

attn_out = l0.self_attn(norm_h, position_embeddings=(cos, sin))[0]
print("\n--- After Self Attention ---")
inspect_tensor("attn", attn_out)

h2 = h + attn_out
print("\n--- After Residual 1 ---")
inspect_tensor("res1", h2)

mlp_in = l0.post_attention_layernorm(h2)
print("\n--- After Post Attention Layernorm ---")
inspect_tensor("ln2", mlp_in)

mlp_out = l0.mlp(mlp_in)
print("\n--- After MLP ---")
inspect_tensor("mlp", mlp_out)

h3 = h2 + mlp_out
print("\n--- After Layer 0 Output ---")
inspect_tensor("l0_out", h3)
