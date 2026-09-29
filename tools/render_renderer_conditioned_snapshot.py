"""Fixed validation gallery for the renderer-conditioned student."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from audit_conditioning_content import picture, sheet
from multilayer_teacher_mode import set_conditioned_teacher_mode as set_teacher_mode
from prepare_conditioning_pilot import save, sha
from renderer_conditioned_stable import RendererFeatureAlignedCohort, load_renderer_checkpoint
from verify_spatial_tone import load_tone_checkpoint


@torch.no_grad()
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    digest = sha(args.checkpoint)
    model, payload = load_renderer_checkpoint(args.checkpoint)
    if sha(args.checkpoint) != digest:
        raise ValueError("Snapshot changed during load")
    warm_path = Path(payload["run"]["initial_head"])
    if sha(warm_path) != payload["run"]["initial_head_sha256"]:
        raise ValueError("Warm reference changed")
    warm, warm_payload = load_tone_checkpoint(warm_path)
    if warm_payload["run"]["parent_sha256"] != payload["run"]["parent_sha256"]:
        raise ValueError("Warm reference uses a different parent")
    args.output.mkdir(parents=True)
    pages = []
    picks = []
    for label, root, mode in zip(
        payload["run"]["cohort_labels"],
        payload["run"]["cohorts"],
        payload["run"]["teacher_pass_counts"],
    ):
        if label not in ("prior", "fresh_session", "two_pass"):
            continue
        cache = RendererFeatureAlignedCohort(Path(root), "validation", expected_pass_count=mode)
        known_face = "seq-1788671399304-47"
        seq = known_face if label == "prior" and known_face in cache.sequence_ids else cache.sequence_ids[0]
        picks.append({"cohort": label, "sequence": seq, "teacher_pass_count": mode})
        for eye in (0, 1):
            state = None
            for index in cache.streams[seq, eye][:32]:
                def tensor(value):
                    return torch.from_numpy(np.array(value, copy=True)).cuda().float()

                color = tensor(cache.rgb[index : index + 1]) / 255.0
                rgb, target = color[:, 0], color[:, 1]
                guides = tensor(cache.guides[index : index + 1])
                context = tensor(cache.context[index : index + 1])
                conditioning = tensor(cache.load_window(np.asarray([[index]]) )[4])[:, 0]
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    base, state = model.parent.forward_temporal(rgb, guides, context, state)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                reference = warm.head(rgb, base, guides, context)
                set_teacher_mode(model.head, 1)
                normal = model.head(rgb, base, guides, context, conditioning)
                set_teacher_mode(model.head, 2)
                amplified = model.head(rgb, base, guides, context, conditioning)
            views = [
                ("input", rgb),
                (f"teacher {mode}x", target),
                ("warm U-Net 5600 (1x)", reference),
                (f"renderer student step{payload['step']} mode1x", normal),
                (f"renderer student step{payload['step']} mode2x", amplified),
            ]
            if any(not torch.isfinite(value).all() for _, value in views):
                raise ValueError("Nonfinite gallery view")
            filename = f"{label}-{seq}-eye{eye}.png"
            sheet(
                [(name, picture(value[0].float().cpu().numpy().transpose(1, 2, 0))) for name, value in views],
                5,
                args.output / filename,
                512,
            )
            pages.append(f'<h2>{label}, {seq}, eye{eye}, frame32, target{mode}x</h2><a href="{filename}"><img src="{filename}"></a>')
    (args.output / "index.html").write_text(
        "<!doctype html><meta charset=\"utf-8\"><title>Renderer-conditioned progress</title>"
        "<style>body{background:#181a20;color:#eee;font:16px system-ui;margin:24px}img{max-width:100%}</style>"
        "<h1>Renderer-conditioned student</h1><p>Native512 tiles; input / captured teacher / warm U-Net / current mode1 / current mode2. Fixed validation progress only; no headset or runtime acceptance.</p>"
        + "".join(pages),
        encoding="utf-8",
    )
    save(
        args.output / "provenance.json",
        {
            "checkpoint": str(args.checkpoint),
            "sha256": digest,
            "step": payload["step"],
            "warm_reference": str(warm_path),
            "warm_sha256": sha(warm_path),
            "selection": picks,
            "test_used": False,
            "full_replay_verified": False,
            "images": len(pages),
        },
    )
    print(json.dumps({"state": "complete", "step": payload["step"], "images": len(pages)}), flush=True)


if __name__ == "__main__":
    main()
