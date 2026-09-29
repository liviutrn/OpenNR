# OpenNR-VR full-frame and repeated-pass visual test — 2026-09-04

This test rendered one captured full Skyrim frame through the trained POC
students. It used the complete `2496x2688` color image for both eyes from
`seq-1788507516449-6`, frame 100, with the captured `1664x1792` depth/MV guides
for the guided model.

The reference is the captured Feature 18/DLSSNR teacher output for the same
frame. The input is pre-NR MGO Skyrim, not a separate stock-vanilla install.

## What was tested

The best one-pass checkpoint was run once, then its output was fed back into
the same checkpoint three more times. This is a repeated application of the
same model, not a model trained specifically for four cascaded passes.

| Model | Eye | 1x time | 1x MAE | 4x time | 4x MAE |
| --- | ---: | ---: | ---: | ---: | ---: |
| RGB-only | 0 | 230.6 ms* | 0.03833 | 121.7 ms | 0.08959 |
| RGB-only | 1 | 122.2 ms | 0.03547 | 121.7 ms | 0.08190 |
| RGB + depth/MV | 0 | 141.8 ms* | 0.04818 | 123.4 ms | 0.10433 |
| RGB + depth/MV | 1 | 123.6 ms | 0.04131 | 123.5 ms | 0.08778 |

`*` The first pass includes one-time warm-up overhead. Warm passes are about
`122–124 ms` per eye. Four passes take about `0.5 seconds` per eye, or about
`1.0 second` for both eyes sequentially, before real application overhead.

## Visual conclusion

The 1x RGB-only image is the closest of the two POC variants on this frame.
After four applications, the RGB-only output loses color and contrast and
becomes visibly gray/dark. The guided output develops much stronger orange/teal
color shifts and dark facial regions. The numerical error rises sharply at 4x,
which matches the visual result.

Repeatedly applying a one-pass residual model is therefore not a useful
multi-pass strategy for this checkpoint. The model learned a correction from
pre-NR input toward the teacher; feeding its already-corrected output back in
causes it to apply another correction as if the correction had never happened.

## Artifacts

Generated under `out/opennr_poc/fullframe_4x`:

- `fullframe_rgb_stereo_1x_4x.png`
- `fullframe_guided_stereo_1x_4x.png`
- `fullframe_rgb_eye0_progression.png`
- `fullframe_guided_eye0_progression.png`
- `fullframe_render_metrics.json`

The render command is reproducible with:

    E:\OpenNR-VR-Poc-Venv\Scripts\python.exe tools\render_poc_fullframe.py --capture-root E:\MGO-RC3-fresh\overwrite\Root\OpenNR_Captures --checkpoint-dir D:\.CODEX_Projects\OpenNR-VR\out\opennr_poc --output-dir D:\.CODEX_Projects\OpenNR-VR\out\opennr_poc\fullframe_4x --sequence-id seq-1788507516449-6 --frame-id 100 --passes 4 --models rgb,guided

This remains an exploratory full-resolution stress/visual test. The model was
trained on `128x128` crops and has no temporal history, recurrent state, live
stereo integration, or VR frame-time acceptance.

## Speed scaling check

The current RGB-only checkpoint was also timed at reduced spatial sizes using
the same full-frame aspect ratio. These are model-forward timings only; they
exclude rendering, texture upload, output upsampling, and compositing.

| Input scale | Eye resolution | One eye | Two eyes sequentially |
| --- | ---: | ---: | ---: |
| 100% | 2496x2688 | 122.2 ms | 243.6 ms |
| 50% width/height | 1248x1344 | 30.6 ms | 61.1 ms |
| 25% width/height | 624x672 | 7.6 ms | 14.9 ms |

This demonstrates why the model is not inherently disqualified by the
full-resolution number: convolution cost follows pixel count, and the full
eye contains roughly 409 times as many pixels as one `128x128` training crop.
However, the reduced-size outputs were not quality-validated, and the current
model was not trained as a low-resolution-to-high-resolution upscaler.
