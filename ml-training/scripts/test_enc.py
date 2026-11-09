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
user_payload = {"task_category": sample["task_category"], "input": sample["input"]}
assistant_payload = sample["expected_output"]

messages = [
    {"role": "system", "content": system_msg},
    {"role": "user", "content": json.dumps(user_payload)},
    {"role": "assistant", "content": json.dumps(assistant_payload)},
]

rendered = tok.apply_chat_template(messages, tokenize=False)
enc = tok(rendered, return_tensors="pt")
input_ids = enc["input_ids"]
attention_mask = enc["attention_mask"]

print(f"input_ids shape: {input_ids.shape}, min: {input_ids.min().item()}, max: {input_ids.max().item()}")
print(f"attention_mask shape: {attention_mask.shape}")

with torch.no_grad():
    out1 = model(input_ids=input_ids)
    print("out1 (no attention_mask) finite:", torch.isfinite(out1.logits).all().item())
    
    out2 = model(input_ids=input_ids, attention_mask=attention_mask)
    print("out2 (with attention_mask) finite:", torch.isfinite(out2.logits).all().item())
    if not torch.isfinite(out2.logits).all().item():
        print("out2 has nan:", torch.isnan(out2.logits).any().item())
        print("out2 has inf:", torch.isinf(out2.logits).any().item())
        # Find where the inf or nan is:
        print("nan positions:", torch.isnan(out2.logits).nonzero()[:10])
        print("inf positions:", torch.isinf(out2.logits).nonzero()[:10])
