import sys
from pathlib import Path
import torch

REPO_ROOT = Path('.').resolve()
sys.path.insert(0, str(REPO_ROOT / 'ml-training/scripts'))
from model_loader import load_model_no_mmap

MODEL_PATH = Path(r'C:\Users\prasu\.cache\hf_direct\Qwen2.5-0.5B-Instruct')
model, tok = load_model_no_mmap(MODEL_PATH, target_dtype=torch.bfloat16, verbose=False)

def check_tensor(name, t):
    if isinstance(t, tuple):
        t = t[0]
    if torch.is_tensor(t):
        fin = torch.isfinite(t).all().item()
        mean_val = t.float().mean().item() if fin else float('nan')
        has_nan = torch.isnan(t).any().item()
        has_inf = torch.isinf(t).any().item()
        print(f"  {name}: shape={list(t.shape)}, finite={fin}, has_nan={has_nan}, has_inf={has_inf}, mean={mean_val:.4f if fin else 0.0}")

for idx, layer in enumerate(model.model.layers):
    def hook_fn(m, inp, outp, layer_idx=idx):
        t_out = outp[0] if isinstance(outp, tuple) else outp
        fin = torch.isfinite(t_out).all().item()
        if not fin or layer_idx < 3:
            print(f"Layer {layer_idx:2d} output: finite={fin}, has_nan={torch.isnan(t_out).any().item()}")
    layer.register_forward_hook(hook_fn)

x = tok("Hello world", return_tensors="pt")["input_ids"]
print("Calling model forward...")
with torch.no_grad():
    out = model(input_ids=x)
    logits = out.logits
    print("Final logits finite:", torch.isfinite(logits).all().item())
    print("Final logits has_nan:", torch.isnan(logits).any().item())
    print("Final logits has_inf:", torch.isinf(logits).any().item())
