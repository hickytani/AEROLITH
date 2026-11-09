import sys
from pathlib import Path
import torch

REPO_ROOT = Path('.').resolve()
sys.path.insert(0, str(REPO_ROOT / 'ml-training/scripts'))
from model_loader import load_model_no_mmap
from transformers import AutoTokenizer

MODEL_PATH = Path(r'C:\Users\prasu\.cache\hf_direct\Qwen2.5-0.5B-Instruct')
model, tok = load_model_no_mmap(MODEL_PATH, target_dtype=torch.bfloat16, verbose=False)

# Test various sequence lengths
for L in [10, 30, 50, 70, 90, 110, 130, 150, 160]:
    input_ids = torch.randint(100, 1000, (1, L), dtype=torch.long)
    with torch.no_grad():
        out = model(input_ids=input_ids)
        logits = out.logits
        fin = torch.isfinite(logits).all().item()
        nan = torch.isnan(logits).any().item()
        zero = (logits == 0).any().item()
        print(f"L={L:3d}: finite={fin} has_nan={nan} has_zero={zero} min={logits.float().min().item():.2f} max={logits.float().max().item():.2f}")
