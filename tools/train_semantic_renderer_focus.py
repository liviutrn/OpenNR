"""Run a bounded renderer-pilot-focused continuation from the finetune candidate.

This is a target-exposure probe, not a promotion run.  It keeps all six older
cohorts available for sampling, gives the ordinary renderer-pilot cohort 25%
of draws instead of the standard 10%, and excludes the currently mismatched
clean7 cohort.  The existing old-only recovery control is the comparison
reference; all validation and temporal gates remain broad.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

import train_semantic_recovery_pair as recovery
from prepare_conditioning_pilot import save, sha
from train_semantic_ablation import cohort


FOCUS_PROBABILITIES = np.asarray([0.30, 0.15, 0.25, 0.15, 0.10, 0.05], dtype=np.float64)
WINDOW = recovery.WINDOW
BURN_IN = recovery.BURN_IN
BATCH = recovery.BATCH
LABELS = recovery.LABELS


def _write_json(path: Path, value) -> None:
    save(Path(path), value)


def _make_schedule(train, steps: int, seed: int):
    rng = np.random.default_rng(seed)
    rows = []
    draws = [0 for _ in train]
    digest = hashlib.sha256()
    for step in range(1, steps + 1):
        old_index = int(rng.choice(len(train), p=FOCUS_PROBABILITIES))
        _, _, ids = train[old_index].sample_window(rng, BATCH, WINDOW)
        draws[old_index] += 1
        digest.update(np.asarray([step, old_index], dtype="<i8").tobytes())
        digest.update(np.asarray(ids, dtype="<i8").tobytes())
        rows.append(
            {
                "step": step,
                "old_index": old_index,
                "old_ids": np.asarray(ids, dtype=np.int64).tolist(),
                "use_new": False,
                "new_ids": None,
            }
        )
    return rows, {
        "seed": int(seed),
        "steps": int(steps),
        "window": WINDOW,
        "burn_in": BURN_IN,
        "batch": BATCH,
        "old_probability": FOCUS_PROBABILITIES.tolist(),
        "new_probability": 0.0,
        "old_draws": draws,
        "new_draws": 0,
        "digest_sha256": digest.hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-checkpoint", type=Path, required=True)
    parser.add_argument("--old-cohort", action="append", type=Path, required=True)
    parser.add_argument("--new-cohort", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--status-every", type=int, default=50)
    parser.add_argument("--eval-batch", type=int, default=1)
    parser.add_argument("--seed", type=int, default=909)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    parser.add_argument("--parent-learning-rate", type=float, default=5e-6)
    parser.add_argument("--freeze-parent", action="store_true")
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if len(args.old_cohort) != 6:
        raise ValueError("Renderer focus expects the six older cohorts")
    if args.steps < 1 or args.eval_every < 1 or args.status_every < 1 or args.eval_batch < 1:
        raise ValueError("Steps, intervals, and eval batch must be positive")
    if args.steps % args.eval_every:
        raise ValueError("Steps must be divisible by eval-every")
    if args.learning_rate <= 0 or args.parent_learning_rate <= 0:
        raise ValueError("Learning rates must be positive")
    args.base_checkpoint = args.base_checkpoint.resolve()
    args.new_cohort = args.new_cohort.resolve()
    args.output_root = args.output_root.resolve()
    old_roots = [root.resolve() for root in args.old_cohort]
    roots = old_roots + [args.new_cohort]
    if not args.base_checkpoint.is_file() or any(not root.is_dir() for root in roots):
        raise FileNotFoundError("Starting checkpoint or cohort is missing")
    if args.output_root.exists():
        raise FileExistsError(args.output_root)

    recovery.scratch._validate_cohorts(roots)
    base_sha = sha(args.base_checkpoint)
    base_payload, base_run, parent_path, protected_reference, base_validation = recovery._check_base_contract(
        args.base_checkpoint, old_roots, args.new_cohort
    )
    train = [cohort(root, "train") for root in roots]
    validation = [cohort(root, "validation") for root in roots]
    schedule, schedule_meta = _make_schedule(train[:6], args.steps, args.seed)

    args.output_root.mkdir(parents=True)
    schedule_path = args.output_root / "focus_schedule.json"
    _write_json(
        schedule_path,
        {
            "metadata": schedule_meta,
            "rows": schedule,
            "cohort_labels": LABELS,
            "cohort_complete_sha256": [sha(root / "complete.json") for root in roots],
            "test_used": False,
        },
    )
    schedule_sha = sha(schedule_path)
    schedule_meta = dict(schedule_meta, serialized_sha256=schedule_sha)
    _write_json(
        args.output_root / "experiment.json",
        {
            "architecture": "semantic_renderer_focus_v1",
            "base_checkpoint": str(args.base_checkpoint),
            "base_checkpoint_sha256": base_sha,
            "base_step": int(base_payload["step"]),
            "protected_checkpoint": str(Path(base_run["base_checkpoint"]).resolve()),
            "protected_checkpoint_sha256": base_run["base_checkpoint_sha256"],
            "parent": str(parent_path),
            "parent_sha256": sha(parent_path),
            "old_cohorts": [str(root) for root in old_roots],
            "new_cohort_excluded_from_training": str(args.new_cohort),
            "cohort_labels": LABELS,
            "focus_probability": FOCUS_PROBABILITIES.tolist(),
            "new_probability": 0.0,
            "steps": int(args.steps),
            "eval_every": int(args.eval_every),
            "eval_batch": int(args.eval_batch),
            "status_every": int(args.status_every),
            "seed": int(args.seed),
            "learning_rate": float(args.learning_rate),
            "parent_learning_rate": float(args.parent_learning_rate),
            "freeze_parent": bool(args.freeze_parent),
            "schedule_sha256": schedule_sha,
            "schedule_metadata": schedule_meta,
            "comparison_control": "C:\\OpenNR\\Training\\semantic_recovery_from_finetune1600_20260910_retry1\\control",
            "source_sha256": {
                "train_semantic_renderer_focus.py": sha(Path(__file__)),
                "train_semantic_recovery_pair.py": sha(Path(__file__).with_name("train_semantic_recovery_pair.py")),
            },
            "protected_reference_source": "base_checkpoint_payload.protected_reference_validation",
            "test_used": False,
        },
    )
    _write_json(args.output_root / "status.json", {"state": "starting", "test_used": False})

    # The recovery helper's non-arm mode always selects the old schedule.  A
    # distinct name keeps this output visibly separate from the paired run.
    args.new_probability = 0.0
    result = recovery._train_arm(
        "renderer_focus",
        args,
        args.base_checkpoint,
        base_sha,
        base_payload,
        base_run,
        parent_path,
        protected_reference,
        base_validation,
        roots,
        train,
        validation,
        schedule,
        schedule_meta,
        args.output_root / "focus",
    )
    _write_json(
        args.output_root / "status.json",
        {"state": "complete", "focus": result["status"], "test_used": False},
    )


if __name__ == "__main__":
    main()
