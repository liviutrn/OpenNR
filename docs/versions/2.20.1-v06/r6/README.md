# OpenNR 2.20.1-v06-r6 — inside NR black protection and wider controls

Build and package audit pending. GPU timing and headset quality require an in-game comparison.

## Changes from r5

- Move near-black protection **inside the NR region**. Retire the misplaced outside control. Existing r5 outside-black values are ignored; the new inside control defaults to zero and is enabled explicitly.
- Apply protection after NR result shaping, before crop compositing. The outside seam estimator samples this protected output. It also works with outside tone transfer disabled and ordinary result shaping disabled.
- Reduce positive NR edits on originally near-black pixels. Preserve darker edits and bright source pixels; use the original RGB peak so saturated highlights are not mistaken for black. This targets gray lift and associated brightening artifacts, not general denoising.
- Smooth the onset around zero NR brightening to avoid a hard color switch. No new temporal filtering, gaze smoothing, deadzone, native history reset or NR evaluation.
- Keep stabilization history in the unprotected raw NR domain. Changing protection strength/threshold/onset does not invalidate that history or native NR/SR history.
- Extend brightness, color, contrast, nonlinear response, dither, edge protection and sample focus up to **2.0**. Above 1, edge protection uses bounded stronger affinity rejection rather than extrapolating to negative confidence.
- Broaden fade width, sample width, tone/offset limits, falloff and boundary ramp. Existing values and the seam preset retain their previous meaning. Fractional smoothing and contrast reach stay at 0–1; hold reaches 0.95 while retaining a final fade.
- Add separate NR postprocess timing controls. Measurement selections are exclusive so one capture request does not overwrite another.

## Controls

**Neural Rendering → NR near-black protection**:

| Control | Range | Meaning |
|---|---:|---|
| Protection strength | 0–2 | 0 off; 1 normal; 2 protects more of the threshold range; attenuation never reverses NR edits |
| Dark threshold | 0.001–0.25 | Protection fades away as original RGB peak approaches this value; default 0.035 |
| Positive lift onset | 0.00001–0.05 | Smooth protection onset as NR brightening increases; default 0.001; higher values preserve more tiny edits |

Start with strength **1**, threshold **0.035**, onset **0.001**. Compare strength 0 and 1 in the same dark scene. Raise strength toward 2 or threshold gradually if gray lift remains. This also suppresses legitimate shadow lifting, and can reduce neural detail in the darkest pixels. It preserves the original game pixels rather than recovering unavailable NR detail.

**Foveated / Edge Blend → Outside NR tone transfer**:

| Control | r6 range |
|---|---:|
| Brightness, color, contrast, shadow/highlight curve, static dither | 0–2 |
| Outside edge protection, near-boundary sample preference | 0–2 |
| Fade width | 8–1024 px |
| Falloff | 0.25–4 |
| Boundary ramp | 0.5–128 px |
| Tone limit | 0–2 stops |
| Brightness offset limit | 0–0.5 |
| Boundary sample width | 4–256 px |
| Map smoothing, contrast reach | 0–1 |
| Hold before final fade | 0–0.95 |

For 2× brightness/color to be visible, the tone/offset limits may need raising too. Those limits still constrain the resulting correction. Wider fades cover more pixels and cost more; higher sample width still uses at most 64 sample pairs per map cell.

All controls persist and apply live. Developer command **configureNeuralBlackProtection** accepts strength, threshold and liftSoftness atomically; **neuralRenderingOutputStatus** reports them. The outside command rejects the retired blackProtection argument and directs callers to the inside command. Its other ranges match the UI and runtime validation.

## Integration and performance

The shared output stage covers full-eye, cropped stereo/atlas, reduced NR resolution after resolve, sequential final output and supported temporal residual reuse. Crop/mask geometry, controller policy, native guide transforms and the r2 gaze fix are unchanged. Native SR performance mode (0.5 × 0.5 render size) is not modified.

When result shaping/stabilization already runs, protection adds arithmetic to that same pass. Otherwise enabling it adds **one postprocess dispatch per eye**, with the existing reusable output texture. It adds no NR evaluation, spatial image blur, new history or readback. It is not guaranteed to be free.

**Measure NR postprocess GPU cost** reports the shared ResultShaping pass, including existing shaping/stabilization and the eyes that ran. Compare strength 0 with the chosen strength in the same scene. **Measure outside tone GPU cost** remains separate. Disable measurement after tuning.

The requested 0.3–0.4 ms budget is an in-game measurement target, not a verified cap. Large fade widths can exceed it. This build has no hardware GPU timing or headset acceptance evidence yet.

## Verification

Build gates include exact r5 patch replay, twelve CPU/HLSL layouts, retained gaze/grid/controller policies, 16 matching UI/load/runtime/command range contracts, 10,000 bounded protection cases, expanded-width compact-ring coverage, actual ResultShaping and seam shader execution on software D3D11, full Windows compilation and r5-to-r6 archive comparison.

Native DLSS5 appearance and in-headset stability need an in-game A/B. Source and software checks cannot establish universal visual correctness or a measured GPU budget.

[r5 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r5) · [r4 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r4) · [r2 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r2)

OpenNR is a fork with upstream lineage from [Open Shaders](https://github.com/alandtse/open-shaders) and [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders).
