# TriView Stereo Atlas: engineering contract for Claude

**Status 2026-11-10: reference only; stereo atlas is not active.** NR Lite in this branch works through the existing safe separate-eye path. Keep B42 untouched.

## Goal
One Feature 18 NVIDIA NR evaluation for both stereo foveas with 1 pass, two evaluations total with 2 passes. Normal STALKER 2 native DLSS SR remains enabled. Cheeky NR runs before native SR; mono periphery bypasses NR. Keep original NR settings and two saved templates. Eliminate unnecessary intermediate allocations and do not block a GPU queue.

## Important observed fact
Pinned Cheeky src/hooks.cpp creates NativeNrInputScope inside process_d3d12_evaluation_impl and hook_evaluate_d3d12_c, individually for each game native DLSS SR call. In src/dlss_nr_input.cpp, prepare_dlss_nr_input does source copy -> individual NR -> original native SR in the same recording. We cannot safely postpone the first original SR call, or sample a second eye texture from an earlier frame, because other UE5 render-graph passes might consume the first output before the second evaluation arrives. Both eyes being presented together is not proof they were rendered/prepared together before the first SR call.

## Precise question to Claude
Find the **earliest UE5 RDG / UEVR TriView stage where BOTH fovea raw color, depth and motion views from the CURRENT FRAME are completed, but NEITHER has undergone native DLSS SR**. Identify concrete classes/functions and pass ordering in STALKER 2 / B42. Can UEVR expose a small callback that supplies the two ID3D12Resource* sources, guide rectangles, GPU state and a command list for pack -> atlas NGX NR -> split, all BEFORE both native SR evaluations? If the two native SR calls occur interleaved with rendering, determine whether a minimal safe RDG scheduling change is possible, and which dependent passes must move. Please show verified evidence from code or trace; do not infer readiness from xrEndFrame.

## Planned API and implementation after verified callback
- Publish paired DlssNrFrame descriptors with two verified fovea IDs and the same-frame ID; fail closed on missing/mismatching frames or dimensions.
- Pack color/depth/motion in a horizontal atlas: LEFT / left-edge replication / right-edge replication / RIGHT. 16-64px guard; never use opposite-eye pixels within a guard half.
- Verify color-space conversion, depth format and **motion-vector X scale** for double-width atlas. The copied Skyrim shaders are reference only; Cheeky NrGuidePass uses normalized guide motion, so do not assume a direct copy is valid without checking motion scaling.
- Allocate one atlas scratch set per in-flight recording and only an optional second pass ping-pong texture; create one NGX NR history for pass 1, second for pass 2. Reuse encoded input and guide pack across passes.
- Split final NR output back into private per-eye native SR Color inputs. Restore original NGX settings after each native SR call. No SR image quality or motion-history modifications.
- Keep atlas temporal history separate from separate-eye histories. One-time valid reset when switching routes, never reset on every frame. On failure, return original input for both eyes, not a partly corrected pair.
- Use existing NrLifetime recording/allocator+queue fences to retire resources. No CPU waits, no blocking queue drain, no reading previous-frame eye inputs.
- GPU timestamp pack + model pass(es) + split, VRAM tracked bytes and opaque NGX model counts, atlas success/fallback diagnostics.

## Existing Skyrim reference
The three shader files here are copied from OpenNR commit 067376ac. Related fixed/stability logic resides in scripts/v01/apply-stereo-atlas.ps1, scripts/v01/apply-atlas-safety.ps1, scripts/v02/apply-atlas-motion-stability.ps1, and scripts/v02/apply-pass2-stability.ps1 on the v02 historical branch. Those were D3D11/D3D12 interop, not directly applicable to Cheeky's D3D12 hook.

## Width and performance
At 4096x3072 per eye, 0.5x0.5 fovea, 1.0 foveal density and DLSS Performance, input is ~1024x768 per fovea; 32px-guard atlas ~2080x768. Measure actual NGX Width/Height because density can differ. Call-count savings reduce fixed model overhead but not the total pixel count; benchmark on RTX 5070.

## Already implemented on NR Lite branch
Cheeky private D3D12 SR is bypassed, native SR remains; original 1/2 pass NR and saved templates remain. Pass-2 scratch and obsolete pass model features are retired after proper GPU lifetime. Cold completed scratch is trimmed conservatively. Sparse [CheekyNR][VRAM] includes scratch/private inputs/features; [CheekyNR][AtlasProbe] records hook call order and source identity, but does NOT prove GPU readiness.
