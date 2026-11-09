import sys
from pathlib import Path
import json
import torch
import torch.nn.functional as F

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
user_payload = {
    "task_category": sample["task_category"],
    "input": sample["input"],
    "context": sample.get("context", {}),
}
assistant_payload = sample["expected_output"]

messages = [
    {"role": "system", "content": system_msg},
    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    {"role": "assistant", "content": json.dumps(assistant_payload, ensure_ascii=False)},
]

rendered = tok.apply_chat_template(messages, tokenize=False)
enc = tok(rendered, return_tensors="pt")
input_ids = enc["input_ids"]

with torch.no_grad():
    out = model(input_ids=input_ids)
    logits = out.logits[0]  # [seq_len, vocab_size]

print("Logits shape:", logits.shape)
print("Logits finite:", torch.isfinite(logits).all().item())
print("Logits min:", logits.min().item(), "max:", logits.max().item(), "mean:", logits.float().mean().item())

# Manual causal LM loss:
# Shift so that tokens < n predict n
shift_logits = logits[:-1, :].contiguous()
shift_labels = input_ids[0, 1:].contiguous()

print("shift_logits shape:", shift_logits.shape)
print("shift_labels shape:", shift_labels.shape)

# Cross entropy loss token-by-token
loss_per_token = F.cross_entropy(shift_logits.float(), shift_labels, reduction='none')
print("Loss per token count:", len(loss_per_token))
print("Loss per token mean:", loss_per_token.mean().item())
print("Loss per token min:", loss_per_token.min().item(), "max:", loss_per_token.max().item())
print("First 10 token losses:", [round(x, 4) for x in loss_per_token[:10].tolist()])
print("Last 10 token losses:", [round(x, 4) for x in loss_per_token[-10:].tolist()])
