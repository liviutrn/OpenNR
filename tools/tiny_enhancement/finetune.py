"""Continue a frozen tiny-enhancement checkpoint on the train split only.

This is deliberately separate from ``train.py`` so a continuation cannot
overwrite the original run.  The parent checkpoint and manifest identity are
recorded in the new output root, validation selects ``best.pt``, and the test
split is never opened by this script.
"""

from __future__ import annotations

import argparse
import hashlib
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
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=2400, help="additional optimization steps")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--eval-batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=1812)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--no-amp", action="store_true")
    args = parser.parse_args()

    if args.steps < 1 or args.batch_size < 1 or args.eval_every < 1:
        raise ValueError("steps, batch-size, and eval-every must be positive")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to write continuation into non-empty output: {output}")
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
    checkpoint_path = args.checkpoint.resolve()
    manifest_hash = sha256_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parent_hash = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    if checkpoint.get("manifest_sha256") != manifest_hash:
        raise ValueError(
            "parent checkpoint manifest identity does not match continuation manifest: "
            f"{checkpoint.get('manifest_sha256')} != {manifest_hash}"
        )
    architecture = str(checkpoint["architecture"])
    model = build_model(architecture, checkpoint.get("config")).to(device)
    model.load_state_dict(checkpoint["model"], strict=True)
    parameters = parameter_count(model)
    if int(checkpoint.get("parameters", parameters)) != parameters:
        raise ValueError("parent checkpoint parameter count mismatch")
    if device.type == "cuda" and identity_error(model, device) > 0.25:
        raise RuntimeError("parent checkpoint does not load as a bounded enhancement model")

    train_cache = TinyPairedCache(manifest_path, "train")
    validation_cache = TinyPairedCache(manifest_path, "validation")
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    use_amp = device.type == "cuda" and not args.no_amp
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)
    rng = np.random.default_rng(args.seed)
    started = time.time()
    parent_step = int(checkpoint.get("step") or 0)
    history: list[dict] = []
    best_mae = math.inf
    best_step = parent_step

    run = {
        "schema": "opennr-tiny-enhancement-finetune-run-v1",
        "model": architecture,
        "model_config": model_config(model),
        "parameters": parameters,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "source_cache": manifest["source_cache"],
        "parent_checkpoint": str(checkpoint_path),
        "parent_checkpoint_sha256": parent_hash,
        "parent_step": parent_step,
        "train_rows": len(train_cache),
        "validation_rows": len(validation_cache),
        "args": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "test_used_for_tuning": False,
        "selection": "lowest validation overall MAE; test is never opened by this script",
        "started_unix": started,
    }
    _atomic_json(output / "run.json", run)

    def evaluate_and_record(step: int, train_loss: float | None, phase: str) -> None:
        nonlocal best_mae, best_step
        validation = evaluate_model(
            model,
            validation_cache,
            device,
            batch_size=args.eval_batch_size,
            use_autocast=False,
        )
        mae = float(validation["overall"]["mae"])
        record = {
            "step": step,
            "phase": phase,
            "seconds": time.time() - started,
            "train_l1": train_loss,
            "validation": validation,
            "gpu_peak_gib": torch.cuda.max_memory_allocated(device) / 2**30 if device.type == "cuda" else None,
        }
        history.append(record)
        _atomic_json(output / "history.json", history)
        payload = {
            "schema": "opennr-tiny-enhancement-checkpoint-v1",
            "architecture": architecture,
            "config": model_config(model),
            "model": model.state_dict(),
            "step": step,
            "validation": validation,
            "parameters": parameters,
            "manifest": str(manifest_path),
            "manifest_sha256": manifest_hash,
            "source_cache": run["source_cache"],
            "source_complete_sha256": manifest["source_complete_sha256"],
            "source_rows_file_sha256": manifest["source_rows_file_sha256"],
            "test_used_for_tuning": False,
            "parent_checkpoint": str(checkpoint_path),
            "parent_checkpoint_sha256": parent_hash,
            "run": run,
        }
        _save_checkpoint(output / "last.pt", payload)
        if mae < best_mae:
            best_mae = mae
            best_step = step
            _save_checkpoint(output / "best.pt", payload | {"best_validation_mae": best_mae})
        print(
            json.dumps(
                {
                    "model": architecture,
                    "phase": phase,
                    "step": step,
                    "train_l1": train_loss,
                    "validation_mae": mae,
                    "validation_input_mae": validation["overall"]["input_mae"],
                    "validation_delta_mae": validation["overall"]["temporal_delta_mae"],
                    "best_step": best_step,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )

    evaluate_and_record(parent_step, None, "parent")
    model.train()
    for local_step in range(1, args.steps + 1):
        step = parent_step + local_step
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
        if local_step % args.eval_every == 0 or local_step == args.steps:
            model.eval()
            evaluate_and_record(step, float(loss.detach().item()), "finetune")
            model.train()

    run["completed_unix"] = time.time()
    run["best_step"] = best_step
    run["best_validation_mae"] = best_mae
    run["gpu_peak_gib"] = torch.cuda.max_memory_allocated(device) / 2**30 if device.type == "cuda" else None
    _atomic_json(output / "run.json", run)
    print(
        json.dumps(
            {
                "completed": True,
                "model": architecture,
                "parent_step": parent_step,
                "best_step": best_step,
                "best_validation_mae": best_mae,
                "output": str(output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
