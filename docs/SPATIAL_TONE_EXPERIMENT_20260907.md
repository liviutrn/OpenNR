# Spatial tone/color versus global transform

Responds to user-observed dim highlights, lifted shadows and color mismatch, supported by signed tone diagnostics. Frozen verified retained seed352 step400 parent; head inputs are RGB input, parent prediction, native guides and context only. No teacher inference inputs. Identity-initialized low-resolution12-channel RGB affine coefficients, smooth bilinear upsampling; bounded matrix and bias followed by output clamp. No channel normalization. Global control uses identical network but spatially averages coefficients before applying them. Parent causal state is unchanged by head outputs.

Both arms: seed356,1200 steps, width48, AdamW1e-4, mixture50/30/20, eight-frame windows/two-frame warm-up, L1+.5 pooled16 RGB L1+.12 temporal-error delta. Three-cohort validation at0/400/800/1200. All three must improve retained parent for candidate saving; select mean relative MAE. Tests pass for exact identity, gradient flow, bounds/channel behavior, frozen parent/state. Head checkpoints require recorded parent and are not standalone runtime artifacts.

Local baseline prior/high-effect/latest:0.019445660 /0.017931557 /0.015411406. Step400:0.019403834 /0.017792115 /0.015370497. Step800:0.019468696 /0.017909225 /0.015331584 (prior regression). Step1200:0.019439945 /0.017918448 /0.015352941. Step400 remains best mean-relative all-cohort candidate: small gains, no visual acceptance yet.

Local output E:/OpenNR_Training/spatial_tone_local_20260907 completed; global output E:/OpenNR_Training/spatial_tone_global_20260907 starts afterward in same live execution13102. No frozen tests, cloud spend or runtime changes. Next finish matched global control, reload selected heads, measure signed tone and show direct teacher comparisons; do not equate tiny MAE improvements with solved color/skin fidelity. Full0.011 goal remains active.

## Both training arms completed

Session13102 exited zero. Global step400 MAE0.019399028 /0.017788008 /0.015379369; step8000.019444051 /0.017898330 /0.015375811; step12000.019417232 /0.017887235 /0.015386044. Step400 is the best global all-cohort checkpoint. At selected step400, global is marginally better on prior/high-effect and local on latest; no clear local-transform advantage. Improvements are too small to claim the user-observed appearance gap solved.

User additionally identifies nose/cheek highlights, mouth interior, under-eye/hood shadows and vibrant realistic skin as explicit inspection targets. The coarse smooth-affine head may lack local specificity; this is a hypothesis until verified face comparisons. tools/verify_spatial_tone.py now checks parent and head-source hashes, strict reloads the head, and replays full validation MAE/PSNR/temporal metrics before gallery generation. No deployment or test access.

## Verification and native-size gallery completed

Verification session61500 exited zero; both heads reproduce all saved validation MAE/PSNR/temporal metrics. Gallery session73367 exited zero. Output E:/OpenNR_Training/verified_tone_gallery_20260907/index.html, with16 previously selected validation eye images (3prior+3high-effect+2latest sequences, both eyes), frame32 after causal history. Each column is native512 pixels; no exposure or color display changes. Model/checkpoint and selection hashes recorded. tone_metrics.json records signed metrics for these exact examples, not an all-validation aggregate.

Inspected prior seq-1788671399304-47 eye0 and seq-1788705227244-60 eye1: local/global changes are subtle and teacher facial shading/skin texture remain visibly different. These examples do not establish complete coverage of hood shadows or mouth interiors. Do not promote the tone heads as solving user feedback. Next investigate finer content-dependent corrections and quantify specific facial regions, preserving the coarse-head comparison as a completed small-gain result.
