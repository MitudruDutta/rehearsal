"""Rehearsal Kaggle kernel: LoRA fine-tuning on verified trajectories, then GGUF export.

Inputs (attached private dataset): config.json, train.jsonl (optional in
convert_base mode). Outputs in /kaggle/working:
  model.gguf     quantized model (merged adapter, or the base model)
  adapter/       LoRA adapter (train mode)
  metrics.json   training metrics, token counts, versions
  manifest.json  sha256 of every output file

The loss covers assistant turns only. Masks are derived from the tokenizer's
own chat template by rendering each prefix, so the trained text is exactly the
text the model will see at inference.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.request
from pathlib import Path

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")
SCRATCH = Path("/kaggle/temp") if Path("/kaggle/temp").exists() else Path("/tmp/rh-scratch")
LLAMA_TAG = "b11515"
PINS = ["transformers==5.5.4", "peft==0.18.0", "accelerate==1.6.0", "bitsandbytes==0.49.2", "gguf>=0.17", "sentencepiece", "protobuf"]


def log(msg: str) -> None:
    print(f"[rehearsal {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_input() -> Path:
    for cfg in INPUT.rglob("config.json"):
        if (cfg.parent / "train.jsonl").exists() or json.loads(cfg.read_text()).get("mode") == "convert_base":
            return cfg.parent
    raise SystemExit("config.json not found in attached datasets")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(name: str, data: dict) -> None:
    (WORK / name).write_text(json.dumps(data, indent=1, default=str))


def install() -> None:
    log("installing pinned packages")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *PINS], check=True)


def llama_tools() -> tuple[Path, Path | None]:
    """llama.cpp converter script (source at tag) and the quantize binary."""
    root = SCRATCH / "llama.cpp"
    if not root.exists():
        log(f"fetching llama.cpp {LLAMA_TAG}")
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", LLAMA_TAG, "https://github.com/ggml-org/llama.cpp", str(root)], check=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(root / "gguf-py")], check=False)
    quant = None
    try:
        url = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/llama-{LLAMA_TAG}-bin-ubuntu-x64.tar.gz"
        tgz = SCRATCH / "llama-bin.tar.gz"
        urllib.request.urlretrieve(url, tgz)
        with tarfile.open(tgz) as tar:
            tar.extractall(SCRATCH / "llama-bin", filter="data")
        found = list((SCRATCH / "llama-bin").rglob("llama-quantize"))
        if found:
            quant = found[0]
            quant.chmod(0o755)
    except Exception as exc:  # noqa: BLE001 - fall back to an unquantized export
        log(f"quantize binary unavailable ({exc}); exporting f16")
    return root / "convert_hf_to_gguf.py", quant


def to_gguf(model_dir: Path, quant_type: str) -> dict:
    convert, quant = llama_tools()
    f16 = SCRATCH / "model-f16.gguf"
    subprocess.run([sys.executable, str(convert), str(model_dir), "--outfile", str(f16), "--outtype", "f16"], check=True)
    out = WORK / "model.gguf"
    if quant is not None:
        env = {**os.environ, "LD_LIBRARY_PATH": f"{quant.parent}:{os.environ.get('LD_LIBRARY_PATH', '')}"}
        subprocess.run([str(quant), str(f16), str(out), quant_type], check=True, env=env)
        f16.unlink()
        return {"gguf_type": quant_type}
    shutil.move(str(f16), out)
    return {"gguf_type": "F16"}


def masked_examples(tokenizer, rows: list[dict], max_length: int) -> tuple[list[dict], dict]:
    examples, skipped, assistant_tokens = [], 0, 0
    for row in rows:
        msgs, tools = row["messages"], row.get("tools") or None
        for m in msgs:
            for c in m.get("tool_calls") or []:
                args = c["function"].get("arguments")
                if isinstance(args, str):
                    try:
                        c["function"]["arguments"] = json.loads(args or "{}")
                    except json.JSONDecodeError:
                        pass
        ids, labels = [], []
        prev: list[int] = []
        ok = True
        for i, m in enumerate(msgs):
            full = tokenizer.apply_chat_template(msgs[: i + 1], tools=tools, tokenize=True, add_generation_prompt=False)
            full = full["input_ids"] if isinstance(full, dict) else full
            if full[: len(prev)] != prev:
                ok = False  # template is not prefix-stable here; drop rather than mis-mask
                break
            new = full[len(prev):]
            if m["role"] == "assistant":
                head = tokenizer.apply_chat_template(msgs[:i], tools=tools, tokenize=True, add_generation_prompt=True) if i else []
                head = head["input_ids"] if isinstance(head, dict) else head
                gen_start = max(0, len(head) - len(prev))
                ids += new
                labels += [-100] * gen_start + new[gen_start:]
                assistant_tokens += len(new) - gen_start
            else:
                ids += new
                labels += [-100] * len(new)
            prev = full
        if not ok or len(ids) > max_length or all(x == -100 for x in labels):
            skipped += 1
            continue
        examples.append({"input_ids": ids, "labels": labels})
    return examples, {"examples": len(examples), "skipped": skipped, "assistant_tokens": assistant_tokens}


def train(cfg: dict, data_dir: Path) -> dict:
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer, TrainingArguments

    base = cfg["base_model"]
    tok = AutoTokenizer.from_pretrained(base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    rows = [json.loads(line) for line in (data_dir / "train.jsonl").read_text().splitlines() if line.strip()]
    examples, stats = masked_examples(tok, rows, cfg.get("max_length", 6144))
    log(f"{stats}")
    if not examples:
        raise SystemExit("no trainable examples after masking")
    model = AutoModelForCausalLM.from_pretrained(
        base,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True),
        torch_dtype=torch.float16,
        device_map={"": 0},
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    lora = cfg.get("lora", {})
    model = get_peft_model(model, LoraConfig(r=lora.get("r", 16), lora_alpha=lora.get("alpha", 32), lora_dropout=lora.get("dropout", 0.05), target_modules=lora.get("targets", ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]), task_type="CAUSAL_LM"))

    def collate(batch: list[dict]) -> dict:
        n = max(len(b["input_ids"]) for b in batch)
        ids = torch.full((len(batch), n), tok.pad_token_id)
        lab = torch.full((len(batch), n), -100)
        att = torch.zeros((len(batch), n), dtype=torch.long)
        for i, b in enumerate(batch):
            L = len(b["input_ids"])
            ids[i, :L] = torch.tensor(b["input_ids"])
            lab[i, :L] = torch.tensor(b["labels"])
            att[i, :L] = 1
        return {"input_ids": ids, "labels": lab, "attention_mask": att}

    args = TrainingArguments(
        output_dir=str(SCRATCH / "ckpt"), per_device_train_batch_size=1, gradient_accumulation_steps=cfg.get("grad_accum", 8),
        num_train_epochs=cfg.get("epochs", 2), learning_rate=cfg.get("lr", 1e-4), warmup_ratio=0.05, lr_scheduler_type="cosine",
        logging_steps=5, save_strategy="no", fp16=True, report_to=[], gradient_checkpointing=True, remove_unused_columns=False, seed=cfg.get("seed", 17),
    )
    trainer = Trainer(model=model, args=args, train_dataset=examples, data_collator=collate)
    result = trainer.train()
    adapter = WORK / "adapter"
    model.save_pretrained(adapter)
    tok.save_pretrained(adapter)
    del model, trainer
    torch.cuda.empty_cache()
    log("merging adapter into fp16 base")
    from peft import PeftModel

    full = AutoModelForCausalLM.from_pretrained(base, torch_dtype=torch.float16, device_map={"": "cpu"})
    merged = PeftModel.from_pretrained(full, adapter).merge_and_unload()
    merged_dir = SCRATCH / "merged"
    merged.save_pretrained(merged_dir, safe_serialization=True)
    tok.save_pretrained(merged_dir)
    return {**stats, "train_loss": result.training_loss, "log_history": trainer_history(result), "merged_dir": str(merged_dir)}


def trainer_history(result) -> dict:
    return {"global_step": result.global_step, "metrics": result.metrics}


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    status = {"started": time.time(), "ok": False}
    try:
        data_dir = find_input()
        cfg = json.loads((data_dir / "config.json").read_text())
        status["config"] = cfg
        install()
        if cfg["mode"] == "convert_base":
            from huggingface_hub import snapshot_download

            model_dir = Path(snapshot_download(cfg["base_model"], local_dir=str(SCRATCH / "base"), allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken", "*.jinja"]))
            status["train"] = None
        else:
            status["train"] = train(cfg, data_dir)
            model_dir = Path(status["train"].pop("merged_dir"))
        status["export"] = to_gguf(model_dir, cfg.get("quant", "Q4_K_M"))
        status["ok"] = True
    except BaseException as exc:  # noqa: BLE001 - always publish evidence
        status["error"] = f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc()[-6000:]}"
        log(status["error"])
    status["finished"] = time.time()
    write_json("metrics.json", status)
    write_json("manifest.json", {str(p.relative_to(WORK)): sha(p) for p in sorted(WORK.rglob("*")) if p.is_file() and p.name != "manifest.json"})
    if not status["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
