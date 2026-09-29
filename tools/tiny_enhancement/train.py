"""Train one isolated tiny RGB-only OpenNR enhancement arm."""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch

from .dataset import TinyPairedCache, sha256_file
from .metrics import evaluate_model
from .models import build_model, identity_error, model_config, parameter_count


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _save_checkpoint(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    temporary.replace(path)


def _device(value: str) -> torch.device:
    if value == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    return torch.device(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", choices=["adaptive_3dlut", "svdlut", "zero_dce_supervised", "srvgg_same_res"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--eval-batch-size", type=int, default=2)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=812)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--no-amp", action="store_true")
    args = parser.parse_args()

    if args.steps < 1 or args.batch_size < 1 or args.eval_every < 1:
        raise ValueError("steps, batch-size, and eval-every must be positive")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    device = _device(args.device)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(args.seed)
        torch.backends.cudnn.benchmark = True
        torch.cuda.reset_peak_memory_stats(device)

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_hash = sha256_file(manifest_path)
    train_cache = TinyPairedCache(manifest_path, "train")
    validation_cache = TinyPairedCache(manifest_path, "validation")
    model = build_model(args.model).to(device)
    parameters = parameter_count(model)
    if device.type == "cuda":
        model_identity_error = identity_error(model, device)
        if model_identity_error > 0.005:
            raise RuntimeError(f"model is not near identity at initialization: {model_identity_error}")
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    use_amp = device.type == "cuda" and not args.no_amp
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)
    rng = np.random.default_rng(args.seed)
    started = time.time()
    history: list[dict] = []
    best_mae = math.inf
    best_step = 0

    run = {
        "schema": "opennr-tiny-enhancement-run-v1",
        "model": args.model,
        "model_config": model_config(model),
        "parameters": parameters,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "source_cache": manifest["source_cache"],
        "source_complete_sha256": manifest["source_complete_sha256"],
        "source_rows_file_sha256": manifest["source_rows_file_sha256"],
        "train_rows": len(train_cache),
        "validation_rows": len(validation_cache),
        "args": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "test_used_for_tuning": False,
        "selection": "lowest validation overall MAE; frozen test is not read by this script",
        "started_unix": started,
    }
    _atomic_json(output / "run.json", run)

    def evaluate_and_record(step: int, train_loss: float | None) -> None:
        nonlocal best_mae, best_step
        validation = evaluate_model(
            model,
            validation_cache,
            device,
            batch_size=args.eval_batch_size,
            use_autocast=False,
        )
        record = {
            "step": step,
            "seconds": time.time() - started,
            "train_l1": train_loss,
            "validation": validation,
            "gpu_peak_gib": torch.cuda.max_memory_allocated(device) / 2**30 if device.type == "cuda" else None,
        }
        history.append(record)
        _atomic_json(output / "history.json", history)
        payload = {
            "schema": "opennr-tiny-enhancement-checkpoint-v1",
            "architecture": args.model,
            "config": model_config(model),
            "model": model.state_dict(),
            "step": step,
            "validation": validation,
            "parameters": parameters,
            "manifest": str(manifest_path),
            "manifest_sha256": manifest_hash,
            "source_cache": manifest["source_cache"],
            "source_complete_sha256": manifest["source_complete_sha256"],
            "source_rows_file_sha256": manifest["source_rows_file_sha256"],
            "test_used_for_tuning": False,
            "run": run,
        }
        _save_checkpoint(output / "last.pt", payload)
        mae = float(validation["overall"]["mae"])
        if mae < best_mae:
            best_mae = mae
            best_step = step
            _save_checkpoint(output / "best.pt", payload | {"best_validation_mae": best_mae})
        print(json.dumps({
            "model": args.model,
            "step": step,
            "train_l1": train_loss,
            "validation_mae": mae,
            "validation_input_mae": validation["overall"]["input_mae"],
            "validation_delta_mae": validation["overall"]["temporal_delta_mae"],
            "best_step": best_step,
        }, separators=(",", ":")), flush=True)

    evaluate_and_record(0, None)
    model.train()
    for step in range(1, args.steps + 1):
        ids = train_cache.sample_indices(rng, args.batch_size)
        inputs, targets = train_cache.load_batch(ids, device)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
            predictions = model(inputs)
            loss = (predictions - targets).abs().mean()
        if not torch.isfinite(loss):
            raise RuntimeError(f"non-finite loss at step {step}")
        if use_amp:
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
        else:
            loss.backward()
            gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        if not torch.isfinite(torch.as_tensor(gradient)):
            raise RuntimeError(f"non-finite gradient at step {step}")
        if step % args.eval_every == 0 or step == args.steps:
            model.eval()
            evaluate_and_record(step, float(loss.detach().item()))
            model.train()

    run["completed_unix"] = time.time()
    run["best_step"] = best_step
    run["best_validation_mae"] = best_mae
    run["gpu_peak_gib"] = torch.cuda.max_memory_allocated(device) / 2**30 if device.type == "cuda" else None
    _atomic_json(output / "run.json", run)
    print(json.dumps({"completed": True, "model": args.model, "best_step": best_step, "best_validation_mae": best_mae}, indent=2))


if __name__ == "__main__":
    main()

