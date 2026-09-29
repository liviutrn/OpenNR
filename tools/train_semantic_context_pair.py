"""Paired spatial context study on the audited full-resolution masters.

Two arms start from the same verified semantic joint-parent checkpoint and use
the same deterministic patch schedule.  The full-eye arm keeps the cached
whole-eye RGB thumbnail; the crop arm replaces only those three RGB context
planes with a thumbnail of the 512x512 input crop.  Input/target crops, guides,
context-guide planes, weights, optimizer, and schedule are otherwise matched.

This is a spatial transfer study.  The source pilot is not a strict temporal
cohort, so its result cannot by itself establish recurrent temporal acceptance.
The test split is never read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F

from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import save, sha


def thumbnail(array: np.ndarray) -> np.ndarray:
    image = Image.fromarray(np.ascontiguousarray(array))
    return (
        np.asarray(image.resize((96, 96), Image.Resampling.BOX), dtype=np.float32)
        .transpose(2, 0, 1)
        / 255.0
    ).astype(np.float16)


def spatial_loss(error: torch.Tensor) -> torch.Tensor:
    return error.abs().mean() + 0.5 * F.avg_pool2d(error, 16).abs().mean()


class PatchSet:
    """Lazy view over patch-indexed memmaps; never copies the full 15 GiB RGB array."""

    def __init__(self, cache: Path, patches: list[dict], split: str):
        rows = json.loads((cache / "rows.json").read_text())
        selected = [(index, patch) for index, patch in enumerate(patches) if patch["split"] == split]
        if not selected:
            raise ValueError(f"No {split} patches")
        for _, patch in selected:
            if rows[patch["row"]]["split"] != split:
                raise ValueError("Patch/row split mismatch")
        self.patch_indices = np.asarray([index for index, _ in selected], dtype=np.int64)
        self.row_indices = np.asarray([patch["row"] for _, patch in selected], dtype=np.int64)
        self.sequence = [patch["sequence_id"] for _, patch in selected]
        self.eye = [int(patch["eye"]) for _, patch in selected]
        self.rgb = np.load(cache / "rgb.npy", mmap_mode="r")
        self.guides = np.load(cache / "guides.npy", mmap_mode="r")
        self.contexts = np.load(cache / "context.npy", mmap_mode="r")

    def __len__(self):
        return len(self.patch_indices)

    def batch(self, local_indices, variant: str):
        local_indices = np.asarray(local_indices, dtype=np.int64)
        global_indices = self.patch_indices[local_indices]
        row_indices = self.row_indices[local_indices]
        inputs = np.array(self.rgb[global_indices, 0], copy=True)
        targets = np.array(self.rgb[global_indices, 1], copy=True)
        guides = np.array(self.guides[global_indices], copy=True)
        contexts = np.array(self.contexts[row_indices], copy=True)
        if variant == "crop":
            for offset, input_patch in enumerate(inputs):
                contexts[offset, :3] = thumbnail(input_patch.transpose(1, 2, 0))
        elif variant != "full":
            raise ValueError(f"Unknown context variant: {variant}")
        return inputs, targets, guides, contexts


def metric(model, data: PatchSet, variant: str, batch: int, device: str):
    model.eval()
    abs_sum = sq_sum = 0.0
    count = 0
    by_sequence = defaultdict(list)
    by_eye = defaultdict(list)
    with torch.no_grad():
        for begin in range(0, len(data), batch):
            end = min(begin + batch, len(data))
            input_np, target_np, guide_np, context_np = data.batch(range(begin, end), variant)
            value = torch.from_numpy(input_np).to(device).float() / 255.0
            target = torch.from_numpy(target_np).to(device).float() / 255.0
            guide = torch.from_numpy(guide_np).to(device).float()
            context = torch.from_numpy(context_np).to(device).float()
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                prediction, _ = model.forward_temporal(value, guide, context, None)
            error = prediction.float() - target
            absolute = error.abs()
            abs_sum += float(absolute.sum().item())
            sq_sum += float(error.square().sum().item())
            count += int(target.numel())
            for offset, value_mae in enumerate(absolute.mean((1, 2, 3)).cpu().tolist()):
                by_sequence[data.sequence[begin + offset]].append(float(value_mae))
                by_eye[str(data.eye[begin + offset])].append(float(value_mae))
    return {
        "mae": abs_sum / count,
        "rmse": math.sqrt(sq_sum / count),
        "patches": len(data),
        "pixels": count,
        "sequence_mae": {key: float(np.mean(values)) for key, values in by_sequence.items()},
        "eye_mae": {key: float(np.mean(values)) for key, values in by_eye.items()},
    }


def train_arm(initial: Path, data: PatchSet, validation: PatchSet, output: Path, variant: str, schedule, args, scientific):
    output.mkdir(parents=True)
    model, payload = load_joint_checkpoint(initial)
    device = "cuda"
    parent = model.parent
    head = model.head
    optimizer = torch.optim.AdamW(
        [
            {"params": [p for p in head.parameters() if p.requires_grad], "lr": args.learning_rate},
            {"params": list(parent.parameters()), "lr": args.parent_learning_rate},
        ],
        weight_decay=1e-4,
    )
    optimizer.load_state_dict(payload["optimizer"])
    for group, lr in zip(optimizer.param_groups, (args.learning_rate, args.parent_learning_rate)):
        group["lr"] = lr
    model.train()
    history = []
    started = time.time()

    def checkpoint(name, step, validation_metrics):
        save_payload = {
            "architecture": "semantic_context_pair_v1",
            "variant": variant,
            "parent_model": parent.state_dict(),
            "head": head.state_dict(),
            "optimizer": optimizer.state_dict(),
            "step": step,
            "validation": validation_metrics,
            "run": scientific,
            "test_used": False,
            "schedule_sha256": scientific["schedule_sha256"],
        }
        torch.save(save_payload, output / (name + ".tmp"))
        (output / (name + ".tmp")).replace(output / name)

    for step in range(0, args.steps + 1):
        if step == 0 or step % args.eval_every == 0 or step == args.steps:
            values = metric(model, validation, variant, args.batch, device)
            record = {"step": step, "validation": values, "seconds": time.time() - started}
            history.append(record)
            save(output / "history.json", history)
            checkpoint("last.pt", step, values)
            save(output / "status.json", {"state": "evaluating" if step < args.steps else "complete", "step": step, "steps": args.steps, "test_used": False})
            if step == args.steps:
                break
        model.train()
        indices = schedule[step - 1]
        input_np, target_np, guide_np, context_np = data.batch(indices, variant)
        value = torch.from_numpy(input_np).to(device).float() / 255.0
        target = torch.from_numpy(target_np).to(device).float() / 255.0
        guide = torch.from_numpy(guide_np).to(device).float()
        context = torch.from_numpy(context_np).to(device).float()
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            prediction, _ = model.forward_temporal(value, guide, context, None)
            loss = spatial_loss(prediction.float() - target)
        if not torch.isfinite(loss):
            raise ValueError(f"Nonfinite loss at step {step}")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(head.parameters(), 1.0, error_if_nonfinite=True)
        torch.nn.utils.clip_grad_norm_(parent.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        if step == 1 or step % 25 == 0:
            save(output / "status.json", {"state": "training", "step": step, "steps": args.steps, "loss": float(loss.detach()), "seconds": time.time() - started, "gpu_peak_gib": torch.cuda.max_memory_allocated() / 2**30, "test_used": False})
    del model, parent, head, optimizer
    torch.cuda.empty_cache()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--eval-every", type=int, default=200)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=3e-5)
    parser.add_argument("--parent-learning-rate", type=float, default=3e-6)
    parser.add_argument("--seed", type=int, default=2609)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.steps < 1 or args.eval_every < 1 or args.batch < 1:
        raise ValueError("Positive steps, eval interval, and batch required")
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required")
    meta = json.loads((args.cache / "complete.json").read_text())
    patches = json.loads((args.cache / "patches.json").read_text())
    if any(patch["split"] == "test" for patch in patches if patch["split"] not in ("train", "validation", "test")):
        raise ValueError("Unexpected split")
    train = PatchSet(args.cache, patches, "train")
    validation = PatchSet(args.cache, patches, "validation")
    rng = np.random.default_rng(args.seed)
    schedule = rng.integers(0, len(train), size=(args.steps, args.batch), dtype=np.int64)
    schedule_sha = hashlib.sha256(schedule.tobytes()).hexdigest()
    scientific = {
        "architecture": "semantic_context_pair_v1",
        "initialize": str(args.initialize.resolve()),
        "initialize_sha256": sha(args.initialize),
        "cache": str(args.cache.resolve()),
        "cache_complete_sha256": sha(args.cache / "complete.json"),
        "cache_rows_sha256": meta["rows_sha256"],
        "seed": args.seed,
        "steps": args.steps,
        "eval_every": args.eval_every,
        "batch": args.batch,
        "learning_rate": args.learning_rate,
        "parent_learning_rate": args.parent_learning_rate,
        "loss": "RGB L1 + .5 pooled16 L1; independent spatial reset",
        "train_patches": len(train),
        "validation_patches": len(validation),
        "train_sequences": sorted(set(train.sequence)),
        "validation_sequences": sorted(set(validation.sequence)),
        "schedule_sha256": schedule_sha,
        "source_sha256": sha(Path(__file__)),
        "test_used": False,
    }
    args.output.mkdir(parents=True)
    save(args.output / "run.json", scientific)
    # Both arms load the immutable initializer, then consume this exact schedule.
    train_arm(args.initialize, train, validation, args.output / "full_eye", "full", schedule, args, scientific | {"variant": "full_eye"})
    train_arm(args.initialize, train, validation, args.output / "crop", "crop", schedule, args, scientific | {"variant": "crop"})
    save(args.output / "pair.json", {"full_eye": str((args.output / "full_eye").resolve()), "crop": str((args.output / "crop").resolve()), "schedule_sha256": schedule_sha, "test_used": False})
    save(args.output / "status.json", {"state": "complete", "steps": args.steps, "test_used": False})


if __name__ == "__main__":
    main()
