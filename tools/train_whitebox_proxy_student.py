#!/usr/bin/env python3
"""Train an isolated small OpenNR student against white-box proxy targets.

The cache must contain both ``proxy.npy`` and the original native teacher in
``rgb.npy[:, 1]``.  The native teacher is never used as the optimization
target in this trainer; it is evaluated as an independent guardrail on every
validation checkpoint and on the later frozen test run.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
import random
import time

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from opennr_student import OpenNRStudent, StudentConfig
from train_student import atomic_json, batch_to_device, loss_fn


class ProxyPatches(Dataset):
    def __init__(self, root: Path, split: str):
        self.root = Path(root)
        self.plan = json.loads((self.root / "patches.json").read_text(encoding="utf-8"))
        self.ids = [index for index, item in enumerate(self.plan) if item["split"] == split]
        self.rgb = np.load(self.root / "rgb.npy", mmap_mode="r")
        self.proxy = np.load(self.root / "proxy.npy", mmap_mode="r")
        if self.rgb.shape[0] != len(self.plan) or self.proxy.shape[0] != len(self.plan):
            raise ValueError("cache arrays and patch plan have different lengths")
        self.guides = np.load(self.root / "guides.npy", mmap_mode="r")
        self.context = np.load(self.root / "context.npy", mmap_mode="r")
        if self.proxy.shape[1:] != (3, 512, 512):
            raise ValueError(f"unexpected proxy shape {self.proxy.shape}")

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, index: int) -> dict[str, object]:
        patch_index = self.ids[index]
        item = self.plan[patch_index]
        row_index = int(item["row"])
        return {
            "rgb": torch.from_numpy(self.rgb[patch_index, 0].copy()),
            "target": torch.from_numpy(self.proxy[patch_index].copy()),
            "native_teacher": torch.from_numpy(self.rgb[patch_index, 1].copy()),
            "guides": torch.from_numpy(self.guides[patch_index].copy()),
            "context": torch.from_numpy(self.context[row_index].copy()),
            "seq": item["sequence_id"],
            "eye": int(item["eye"]),
            "index": patch_index,
        }


def metric_block(error_sum: float, square_sum: float, baseline_sum: float, baseline_square_sum: float, pixels: int) -> dict[str, float | int]:
    mae = error_sum / max(1, pixels)
    mse = square_sum / max(1, pixels)
    identity_mae = baseline_sum / max(1, pixels)
    identity_mse = baseline_square_sum / max(1, pixels)
    return {
        "mae": mae,
        "psnr": -10.0 * math.log10(max(mse, 1e-12)),
        "identity_mae": identity_mae,
        "identity_psnr": -10.0 * math.log10(max(identity_mse, 1e-12)),
        "improvement_pct": 100.0 * (identity_mae - mae) / max(identity_mae, 1e-12),
        "pixels": pixels,
    }


@torch.no_grad()
def evaluate_proxy(model: torch.nn.Module, loader: DataLoader, device: str) -> dict[str, object]:
    model.eval()
    totals = {name: [0.0, 0.0, 0.0, 0.0, 0] for name in ("proxy", "native")}
    by_sequence: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"proxy": [], "native": []})
    by_eye: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"proxy": [], "native": []})
    for batch in loader:
        rgb, target, guides, context = batch_to_device(batch, device)
        native = batch["native_teacher"].to(device, non_blocking=True).float() / 255.0
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=device == "cuda"):
            prediction = model(rgb, guides, context)
        for name, reference in (("proxy", target), ("native", native)):
            error = prediction.float() - reference.float()
            baseline = rgb.float() - reference.float()
            totals[name][0] += error.abs().sum().item()
            totals[name][1] += error.square().sum().item()
            totals[name][2] += baseline.abs().sum().item()
            totals[name][3] += baseline.square().sum().item()
            totals[name][4] += reference.numel()
            per_item = error.abs().mean((1, 2, 3)).cpu().tolist()
            for sequence, eye, value in zip(batch["seq"], batch["eye"].tolist(), per_item):
                by_sequence[str(sequence)][name].append(float(value))
                by_eye[str(eye)][name].append(float(value))
    return {
        "proxy": metric_block(*totals["proxy"]),
        "native": metric_block(*totals["native"]),
        "sequence_mae": {
            sequence: {name: float(np.mean(values[name])) for name in ("proxy", "native")}
            for sequence, values in by_sequence.items()
        },
        "eye_mae": {
            eye: {name: float(np.mean(values[name])) for name in ("proxy", "native")}
            for eye, values in by_eye.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name", choices=("rgb", "guided"), default="guided")
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--blocks", type=int, default=2)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--eval-every", type=int, default=250)
    parser.add_argument("--lr", type=float, default=0.0003)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()

    cache = args.cache.expanduser().resolve()
    output = args.output.expanduser().resolve()
    proxy_meta_path = cache / "proxy_complete.json"
    if not proxy_meta_path.is_file():
        raise FileNotFoundError(f"white-box proxy metadata is missing: {proxy_meta_path}")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output: {output}")
    if args.steps < 1 or args.batch < 1 or args.eval_every < 1:
        raise ValueError("steps, batch, and eval-every must be positive")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this training pilot")

    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    torch.backends.cudnn.benchmark = True
    device = "cuda"
    output.mkdir(parents=True, exist_ok=True)
    cache_report = json.loads((cache / "complete.json").read_text(encoding="utf-8"))
    proxy_meta = json.loads(proxy_meta_path.read_text(encoding="utf-8"))
    train = ProxyPatches(cache, "train")
    validation = ProxyPatches(cache, "validation")
    if not train or not validation:
        raise ValueError("proxy cache must have non-empty train and validation splits")
    generator = torch.Generator().manual_seed(args.seed)
    loader = DataLoader(train, batch_size=args.batch, shuffle=True, generator=generator, num_workers=args.workers, pin_memory=True)
    validation_loader = DataLoader(validation, batch_size=args.batch, num_workers=args.workers, pin_memory=True)
    config = StudentConfig(width=args.width, guided=args.name == "guided", blocks=args.blocks)
    model = OpenNRStudent(config).to(device)
    ema = deepcopy(model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0001)
    run = {
        "schema": "opennr-whitebox-proxy-training-v1",
        "target_kind": "whitebox_recovered_rgb_proxy",
        "cache": str(cache),
        "cache_complete": cache_report,
        "proxy_metadata": proxy_meta,
        "name": args.name,
        "config": asdict(config),
        "args": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "training_pairs": len(train),
        "validation_pairs": len(validation),
        "test_used_for_tuning": False,
        "native_teacher_used_as_loss_target": False,
        "started": time.time(),
    }
    atomic_json(output / "run.json", run)

    best_proxy = float("inf")
    best_native = float("inf")
    history_path = output / "history.jsonl"

    def save_checkpoint(name: str, step: int) -> None:
        payload = {
            "schema": "opennr-whitebox-proxy-student-checkpoint-v1",
            "target_kind": "whitebox_recovered_rgb_proxy",
            "config": asdict(config),
            "model": ema.state_dict(),
            "raw_model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "step": step,
            "best_proxy_validation_mae": best_proxy,
            "best_native_guardrail_mae": best_native,
            "cache": cache_report,
            "proxy_metadata": proxy_meta,
            "run": run,
        }
        torch.save(payload, output / f"{name}.pt")

    iterator = iter(loader)
    started = time.time()
    loss_acc: list[float] = []
    for step in range(1, args.steps + 1):
        try:
            batch = next(iterator)
        except StopIteration:
            iterator = iter(loader)
            batch = next(iterator)
        rgb, target, guides, context = batch_to_device(batch, device, augment=True)
        model.train()
        optimizer.zero_grad(set_to_none=True)
        lr = args.lr * (0.1 + 0.9 * 0.5 * (1.0 + math.cos(math.pi * (step - 1) / args.steps)))
        for group in optimizer.param_groups:
            group["lr"] = lr
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            prediction = model(rgb, guides, context)
            loss = loss_fn(prediction.float(), target)
        if not torch.isfinite(loss):
            raise RuntimeError(f"non-finite loss at step {step}")
        loss.backward()
        gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        if not torch.isfinite(gradient):
            raise RuntimeError(f"non-finite gradient at step {step}")
        optimizer.step()
        with torch.no_grad():
            decay = min(0.995, (1 + step) / (10 + step))
            for ema_parameter, parameter in zip(ema.parameters(), model.parameters()):
                ema_parameter.lerp_(parameter, 1 - decay)
        loss_acc.append(float(loss.item()))
        if step % 25 == 0 or step == 1:
            atomic_json(
                output / "status.json",
                {
                    "state": "training",
                    "step": step,
                    "total": args.steps,
                    "loss": float(np.mean(loss_acc)),
                    "lr": lr,
                    "seconds": time.time() - started,
                    "best_proxy_validation_mae": best_proxy if math.isfinite(best_proxy) else None,
                    "best_native_guardrail_mae": best_native if math.isfinite(best_native) else None,
                    "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30,
                },
            )
            print(json.dumps({"event": "training", "step": step, "total": args.steps, "loss": float(np.mean(loss_acc)), "seconds": time.time() - started}), flush=True)
            loss_acc = []
        if step % args.eval_every == 0 or step == args.steps:
            metrics = evaluate_proxy(ema, validation_loader, device)
            proxy_mae = float(metrics["proxy"]["mae"])
            native_mae = float(metrics["native"]["mae"])
            proxy_improved = proxy_mae < best_proxy
            best_proxy = min(best_proxy, proxy_mae)
            best_native = min(best_native, native_mae)
            record = {"step": step, "seconds": time.time() - started, "validation": metrics}
            with history_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            if proxy_improved:
                save_checkpoint("best", step)
            save_checkpoint("last", step)
            print(json.dumps({"event": "validation", "step": step, "proxy": metrics["proxy"], "native": metrics["native"]}), flush=True)
    atomic_json(
        output / "status.json",
        {
            "state": "completed",
            "step": args.steps,
            "best_proxy_validation_mae": best_proxy,
            "best_native_guardrail_mae": best_native,
            "seconds": time.time() - started,
        },
    )
    print(json.dumps({"event": "training_complete", "output": str(output), "best_proxy_validation_mae": best_proxy, "best_native_guardrail_mae": best_native}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
