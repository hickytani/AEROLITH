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

system_msg = (
    "You are AEROLITH's engineering parameter extraction and constraint model. "
    "Output one valid JSON object adhering strictly to the required schema. "
    "Never invent unmentioned dimensions or make unsubstantiated safety claims."
)
messages = [
    {"role": "system", "content": system_msg},
    {"role": "user", "content": json.dumps({"task_category": sample["task_category"], "input": sample["input"]})},
    {"role": "assistant", "content": json.dumps(sample["expected_output"])},
]

rendered = tok.apply_chat_template(messages, tokenize=False)
enc = tok(rendered, return_tensors="pt")
input_ids = enc["input_ids"][0]

with torch.no_grad():
    out = model(input_ids=enc["input_ids"])
    logits = out.logits[0]  # [seq_len, vocab_size]

for pos in range(15):
    t_id = input_ids[pos].item()
    t_str = tok.decode([t_id])
    l_row = logits[pos]
    is_finite = torch.isfinite(l_row).all().item()
    has_nan = torch.isnan(l_row).any().item()
    is_zero = (l_row == 0).all().item()
    min_v = l_row.min().item()
    max_v = l_row.max().item()
    print(f"Pos {pos:2d} | Token {t_id:6d} {repr(t_str):<15} | finite={is_finite} has_nan={has_nan} is_zero={is_zero} min={min_v:.2f} max={max_v:.2f}")

# Also check last 5 positions:
print("---")
for pos in range(len(input_ids)-5, len(input_ids)):
    t_id = input_ids[pos].item()
    t_str = tok.decode([t_id])
    l_row = logits[pos]
    is_finite = torch.isfinite(l_row).all().item()
    has_nan = torch.isnan(l_row).any().item()
    is_zero = (l_row == 0).all().item()
    min_v = l_row.min().item()
    max_v = l_row.max().item()
    print(f"Pos {pos:2d} | Token {t_id:6d} {repr(t_str):<15} | finite={is_finite} has_nan={has_nan} is_zero={is_zero} min={min_v:.2f} max={max_v:.2f}")
