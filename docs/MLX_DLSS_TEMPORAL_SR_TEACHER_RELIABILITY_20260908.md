# OpenNR-VR: September 8 MLX-DLSS temporal SR and teacher-reliability recommendation

Recorded September 8, 2026. This is a technical decision record and recommendation
report. It evaluates the user-provided research note, the public MLX-DLSS commit
6499d59, the public DLSS-NR measurement work referenced in that note, and the
current OpenNR-VR state. No Skyrim profile, capture contract, runtime DLL,
training target, or dataset lineage was changed for this assessment.

## Technical summary

The update is useful, but it does not change the OpenNR production or teacher
boundary.

1. **The recovered temporal DLSS-SR implementation is a high-value architecture
   reference and a low-value direct teacher candidate.** It exposes a concrete
   recurrent state design—previous color, previous luminance, and a hidden
   feature tensor—plus an eight-phase shifted-window schedule, native motion/depth
   handling in the recovered path, and an eleven-stage attention network. That is
   enough to justify one narrow state-decomposition ablation against the current
   OpenNR temporal student. It is not DLSS Neural Rendering, does not use our
   nvngx_dlssnr.dll, and does not establish a SkyrimVR runtime path.

2. **The teacher-reliability result is more directly relevant to training
   methodology than the SR graph is.** The attached note reports that DLSSNR
   recovered more reference-correlated detail in bright regions than in dark
   regions, while its invention component stayed roughly flat. If independently
   replicated, that supports a reference-aware confidence map or auxiliary loss.
   It does not justify immediately gating native teacher targets by luminance:
   our project does not yet have a generally aligned high-resolution reference
   for the current recurrent cohorts, and the cited brightness result is
   presently one controlled scene.

3. **Native Feature 18 remains the only accepted Skyrim teacher.** The local
   isolated MLX-DLSS Neural Rendering replay already found that the active local
   DLL has an unknown hash despite the expected version string, and that a
   three-sequence recovered-to-native comparison improved the aggregate only
   slightly while regressing individual sequences. This is a useful parity
   warning, not a reason to relabel native data. A different SR network has an
   even weaker claim to be a replacement.

4. **The immediate action is bounded research, not integration.** Register a
   state-decomposition ablation using the existing strict temporal cache, then—
   only if the diagnostic is promising—build a small, separately labeled
   reference micro-cohort for real-detail versus invention analysis. Do not start
   a cloud run, install an external proxy into MGO, replace native targets, or
   expand the active capture root because of this update.

The short recommendation is: **borrow the state decomposition and the
reference-aware evaluation method; do not borrow the SR runtime, its optical-flow
fallbacks, or its teacher labels.**

## What changed upstream, and what is actually verified

The source-verified development is [MLX-DLSS commit 6499d59, “Restore temporal
DLSS SR in the native video pipeline”](https://github.com/iamwavecut/MLX-DLSS/commit/6499d59).
The commit is dated September 8, 2026 and adds 28 files with 1,907 additions and
67 deletions. It restores an experimental **DLSS SDK 310.7.0, preset K, LDR, 2x**
super-resolution path for video. The project describes the path as experimental,
not a game integration, and says that its model packages are prepared from the
user's own NVIDIA library rather than redistributed.

The implementation is inspectable in the [recovered DLSSSuperResolution.swift
source](https://raw.githubusercontent.com/iamwavecut/MLX-DLSS/6499d59/Sources/DLSSMLX/DLSSSuperResolution.swift):

- The model identifier is dlss-sr-310.7.0-k-ldr-2x.
- The eleven stage channel widths are
  32 -> 64 -> 64 -> 96 -> 128 -> 160 -> 128 -> 96 -> 64 -> 64 -> 32.
- The attention-head counts are
  2 -> 2 -> 2 -> 4 -> 4 -> 8 -> 4 -> 4 -> 2 -> 2 -> 2.
- Each head uses 32-wide Q/K/V projections and a 64x64 positional tensor.
  Feed-forward layers expand to four times the stage width. Early stages merge
  into the down/up path, and the final stage projects 32 channels to a 48-channel
  reconstruction representation.
- The per-stream state is explicitly a tuple of previous color history, previous
  luminance, and a hidden neural feature tensor. A reset clears all three.
- The frame phase advances modulo eight, with an explicit eight-entry shifted
  window schedule. This is a concrete temporal organization, not a claim that
  eight frames are sufficient for every game.
- The low-level interface accepts current-to-previous motion in input-pixel
  units and also carries a depth resource into the flow/rejection preparation.
  The convenience video path, however, uses estimated optical flow, flat depth,
  and zero jitter. The public documentation explicitly marks game integration,
  other presets, scale factors, and HDR as unsupported.

The [commit's super-resolution documentation](https://raw.githubusercontent.com/iamwavecut/MLX-DLSS/6499d59/docs/super-resolution.md)
also states that the recovery still requires a one-time CUDA capture from the
original Linux libnvidia-ngx-dlss.so.310.7.0 library. Its reported reference
checks are eight moving 512x384-to-1024x768 frames at 59.8–72.2 dB PSNR, with
the explicit caveat that this is not Windows DLL parity and that rare channel
errors can reach 0.19 when a different reconstruction filter is selected.

Those facts support a strong architecture-reading claim and a weak deployment
claim:

| Claim | Status |
| --- | --- |
| A recurrent temporal DLSS-SR graph is now publicly inspectable | Verified from upstream source and documentation |
| The graph has three retained state forms and an eight-phase schedule | Verified from upstream source |
| The public SR path is a SkyrimVR-compatible Feature 18 replacement | False / unsupported by the evidence |
| Its 310.7.0 source library is equivalent to our 310.8.0.0 DLSSNR teacher | False: different network, task, library and version boundary |
| Its ordinary optical-flow video path is a substitute for native Skyrim motion resources | False for OpenNR acceptance |
| The recovered state design may help a compact temporal student | Plausible hypothesis; requires a matched ablation |

## The teacher-reliability finding is valuable, but its evidence class matters

The attached research note reports a second development in
edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass: a pixel-aligned
high-resolution reference analysis separating teacher edits that correlate with
the reference from edits absent in the reference. The note reports:

| Reported quantity | Author-reported result | Evidence status for OpenNR |
| --- | ---: | --- |
| Reference-correlated detail | 7.70 -> 8.61 (+11.8%) | User-pasted result; not independently rerun in this assessment |
| Invention component | 5.15 -> 6.23 (+21%) | User-pasted result; not independently rerun in this assessment |
| Recovered detail in darkest quarter | 0.454 -> 0.464 (+0.9%) | User-pasted result; one-scene generalization is open |
| Recovered detail in brightest quarter | 0.777 -> 0.889 (+11.1%) | User-pasted result; one-scene generalization is open |
| Brightness-bin pattern | Gain increased monotonically with brightness; invention stayed roughly flat | User-pasted result; useful hypothesis, not a project-wide law |

The methodology is the important part even before the exact values are replicated:

- keep a base render, native DLSSNR output, and independently aligned reference;
- decompose the teacher edit rather than treating every teacher pixel as equally
  trustworthy;
- stratify by luminance/exposure and inspect low-effect regions separately;
- use the decomposition to propose a confidence map, not just a global loss weight;
- preserve the native-teacher objective as a guardrail if the project still wants
  teacher-like behavior.

The public [THERMOTRON/OptiScaler DLSSNR repository](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass)
supports the general warning behind this method: its own documentation says that
block-luminance variation can count invented grain as detail, and that a
reference-based comparison would be stronger. That corroborates the methodological
direction, but it does not independently verify the attached note's exact
7.70/8.61 measurements.

This distinction changes the recommendation. The current OpenNR objective is
native Feature 18 agreement, while the new method introduces a second possible
objective: reference-supported visual quality. Those objectives can disagree.
Therefore, a future reference-aware student must be named and evaluated as a
separate research arm. It must not silently replace the canonical teacher target.

## Usefulness to the current OpenNR project

The following scores are planning scores, not performance or quality metrics.
They mean: 3 = supports an immediate bounded OpenNR experiment, 2 = useful
architecture or diagnostic reference after prerequisites, 1 = speculative or
wrong runtime target.

| Development | Direct project value | Recommended use | Do not infer |
| --- | --- | --- | --- |
| Recovered temporal DLSS-SR graph | **2 / 3** | Design a state-decomposition ablation: current hidden + previous output versus explicit luminance and motion-reprojected history | That SR can generate DLSSNR labels, that 310.7.0 is our teacher, or that its Metal speed transfers to CUDA/TensorRT/VR |
| Teacher real-detail versus invention analysis | **3 / 3 conditional** | Register a reference-aligned diagnostic and later a confidence-weighted auxiliary objective | That luminance gating is universal, or that a brighter result is automatically more teacher-equivalent |
| SR-to-DLSSNR multi-task pretraining | **1 / 3** | Keep as a future hypothesis after parity and state ablations | That shared attention or history shapes imply compatible features or useful transfer |
| DLSS-SR runtime integration in SkyrimVR | **0 / 3** | Do not pursue in the current phase | That a public reconstruction is a live D3D11/Feature 18/SteamVR path |

The overall effect is therefore **moderate research value, near-zero immediate
runtime value, and no change to the current promotion gate**.

## Fit against the local OpenNR baseline

Several local facts constrain how much weight this update should carry.

1. The pinned project teacher is the working Open Shaders Feature 18 path, not
   DLSS SR. The baseline records nvngx_dlssnr.dll file version 310.8.0.0.
   The isolated parity follow-up found the active file hash
   e16bcf15e16e13f527491cdf7845b2fe6521a738d8f7c9c721866a8496e1fc8e,
   which does not match the MLX-DLSS known hash set. Version equality therefore
   cannot be used as an identity claim.

2. The local three-sequence calibrated MLX-DLSS Neural Rendering replay changed
   input-to-native MAE from 0.0234133062 to 0.0233862410, but the direction
   was not stable: one sequence improved while validation sequence 25 and frozen
   sequence 31 regressed. The local record correctly kept reconstructed output
   in a separate lineage and did not authorize relabeling or runtime promotion.

3. The current OpenNR target remains unmet. The latest local findings report that
   every six-cohort candidate remains above the 0.011 MAE target, and the
   latest joint/mixture endpoints are research checkpoints rather than
   promotions. Longer training, semantic conditioning, and renderer-context
   pilots have produced useful diagnostics but not a broad acceptance result.

4. The current temporal student already has a causal hidden state and previous
   prediction. The local tools/temporal_student.py implementation initializes
   a zero hidden tensor and previous RGB state, while the strict trainer uses
   reset-qualified clips and eight-frame windows. The SR recovery therefore
   suggests a narrow, testable extension—not a reason to replace the student
   with an eleven-stage transformer.

The local records are [the MLX-DLSS performance relevance decision](MLX_DLSS_PERFORMANCE_RELEVANCE_20260908.md),
[the current OpenNR findings](OPENNR_LATEST_FINDINGS_20260908.md),
[the pinned teacher baseline](BASELINE_OPEN_SHADERS_0.4.5.md), and the
[current temporal student](../tools/temporal_student.py).

## Recommended bounded experiments

### A. Run a state-decomposition ablation before any new capture

This is the highest-value use of the new SR architecture and can be performed
against the existing strict temporal cache.

Keep the verified parent, sample schedule, six ordinary validation cohorts,
eight-frame windows, exact initial reset, and native motion/depth resources
unchanged. Compare:

1. **Control:** current temporal student with hidden state plus previous output.
2. **Luma-state arm:** add a separately warped or updated luminance history state,
   initialized to identity on reset.
3. **Motion-history arm:** make the previous-output history explicitly
   motion-reprojected using the already validated native MV convention, with
   invalid/out-of-bounds rejection and a confidence channel.
4. **Combined arm:** add both only if the single-intervention arms are
   interpretable.

An eight-phase local-window schedule may be a later diagnostic, but it should not
be introduced in the same run as the state changes. The first test should answer
whether an explicit luma/history decomposition reduces temporal error without
trading away the six-cohort MAE gate. It should not attempt to reproduce the
full SR graph.

Acceptance requires exact step-zero equality, independent checkpoint replay,
improvement against the common start and matched control, no broad temporal
regression, and preserved visual/color review. A fit improvement on training
subsets alone is insufficient.

### B. Build a small reference micro-cohort for teacher reliability

Do this only after the state ablation is registered and only if the project
needs to pursue reference-supported quality rather than strict teacher imitation.
The micro-cohort should be separate from current recurrent training data and
should contain:

- the same frozen scene/camera and frame identity in base, native teacher and
  higher-quality reference renders;
- both eyes, native source rectangles, exposure/HDR metadata and exact reset
  state;
- at least two scene/content types and multiple luminance ranges, including
  deep shadow, mid-tone and bright material regions;
- a retained native motion/depth pair for any temporal extension;
- an immutable manifest that makes alignment, supersampling, route and any
  post-processing differences explicit.

Compute a teacher-edit map and a reference-support map before changing training.
Report the result by luminance band, effect band, sequence and eye. If the
reference alignment is not exact, stop at a diagnostic report and do not produce
confidence labels.

### C. Use dual guardrails if a reference-aware student is later trained

If the micro-cohort confirms a reproducible pattern, train a separately named
reference-aware arm with two explicit objectives:

- native-teacher agreement remains the primary compatibility guardrail;
- reference-supported detail and low-invention behavior are secondary objectives
  or spatial weights, with the weighting rule fixed before endpoint inspection.

The candidate must be compared with both the canonical native-teacher student and
the common start on all ordinary cohorts. A reference-quality improvement that
drifts from Feature 18, regresses temporal stability, or breaks stereo is not an
OpenNR promotion; it is a separate visual-quality experiment.

### D. Keep SR-to-NR pretraining as a later, optional hypothesis

Do not spend cloud budget on multi-task pretraining now. If the state ablation and
reference micro-cohort both produce useful evidence, then test whether an
intermediate temporal representation transfers from SR-style history inputs to
DLSSNR targets. Start with a frozen or low-rank adapter and a small fixed
comparison. Require a one-step gradient smoke, memory measurement, deterministic
replay, and both-cohort improvement before considering a longer run.

## Recommended execution order and non-goals

| Priority | Action | Gate | Explicit non-goal |
| --- | --- | --- | --- |
| P0 | Preserve the current native Feature 18 teacher, native labels, active profile and existing strict cache | Hashes, manifests and rollback remain unchanged | No profile edit, DLL replacement, target relabeling or cloud rental |
| P1 | Register the luma/history state ablation on existing strict temporal data | Exact reset, common-start comparison, six-cohort MAE and temporal retention | No full SR-graph rewrite or optical-flow substitution |
| P1 | If needed, capture a small aligned reference micro-cohort | Both eyes, exact frame alignment, native guides, scene/content and luminance coverage | No large sparse capture and no mixing reference rows into current cohorts by filename |
| P2 | Evaluate a reference-aware confidence/gated objective | Native-teacher guardrail plus reference quality and temporal/stereo review | No universal luminance gate from one scene |
| P3 | Test SR-to-NR adapter or multi-task transfer | Parity, gradient, memory, deterministic replay and two-cohort improvement | No blind width scaling or Runpod spend |

## Limitations, uncertainty and safety boundaries

- The SR source is a different network and task from DLSSNR. Its input
  conventions and recurrent state are useful evidence, not an OpenNR contract.
- The published SR reference checks use a Linux 310.7.0 source library and
  synthetic/moving video cases. They do not establish Windows, CUDA, TensorRT,
  D3D11, D3D12, stereo, SteamVR, OpenXR or headset acceptance.
- The ordinary MLX-DLSS video path uses optical flow, flat depth and zero jitter.
  OpenNR acceptance must keep exact native motion vectors, depth and reset
  semantics. Optical flow may be a diagnostic comparison only.
- The attached teacher-reliability numbers are author-reported from the user
  note. The exact experiment was not reproduced here, and the one-scene
  brightness relationship is not a general law.
- Reference-aware training can improve perceptual or high-frequency scores while
  moving away from the native teacher. The two objectives must remain visible as
  separate metrics.
- Extracted vendor weights and binaries remain private, locally owned inputs.
  Do not commit or redistribute them, and do not install an unverified proxy or
  recovered runtime into the known-good MGO profile.
- Static replay, offline inference speed, source/package health, and model
  parity are separate from live renderer ownership, stereo delivery, headset
  appearance, compositor timing, audible/UI behavior and VR frame-time.

## Further questions

1. Can a two- or four-scene Skyrim reference micro-cohort reproduce the reported
   brightness dependence after exact eye/frame/source-rectangle alignment?
2. Does explicit luma history improve holdout temporal error, or does it only
   improve fit because the current student lacks a useful exposure state?
3. Which native Feature 18 resources explain the remaining student error after
   current RGB, depth and motion inputs are held constant?
4. Does a recovered MLX-DLSS intermediate feature correlate with native teacher
   residuals after the local DLL hash and preprocessing contract are fixed?
5. Can a reference-aware arm improve low-effect shadow quality without losing
   teacher agreement, color, stereo balance or temporal stability?
6. If a future adapter is useful, can it be trained entirely from private local
   artifacts while preserving the source and vendor-license boundary?

## Bottom line

The new MLX-DLSS temporal SR recovery is a meaningful technical development
because it exposes a second modern NVIDIA recurrent neural-graphics design. Its
OpenNR value is architectural: use it to formulate a small, interpretable
history/luminance ablation. The teacher-reliability result is potentially even
more important for long-term quality, but it requires an independently aligned
reference before it can influence supervision.

Keep native Feature 18 and the strict two-cohort/temporal/stereo gates
authoritative. Borrow the ideas, not the runtime assumptions: **state
decomposition and reference-aware measurement are recommended; SR integration,
teacher relabeling, universal luminance gating, blind multi-task pretraining and
new cloud spend are not recommended.**

### Evidence inventory

- User-provided attachment: pasted-text.txt, reviewed September 8, 2026. The
  exact DLSSNR real-detail/invention numbers are labeled author-reported above.
- [MLX-DLSS 6499d59 commit](https://github.com/iamwavecut/MLX-DLSS/commit/6499d59).
- [MLX-DLSS recovered SR source at 6499d59](https://raw.githubusercontent.com/iamwavecut/MLX-DLSS/6499d59/Sources/DLSSMLX/DLSSSuperResolution.swift).
- [MLX-DLSS SR documentation at 6499d59](https://raw.githubusercontent.com/iamwavecut/MLX-DLSS/6499d59/docs/super-resolution.md).
- [MLX-DLSS README at 6499d59](https://raw.githubusercontent.com/iamwavecut/MLX-DLSS/6499d59/README.md).
- [THERMOTRON/OptiScaler DLSSNR repository](https://github.com/edgarbatjr/OptiScaler_DLSSNR-THERMOTRON-multipass).
- [Local MLX-DLSS performance relevance record](MLX_DLSS_PERFORMANCE_RELEVANCE_20260908.md).
- [Local OpenNR latest findings](OPENNR_LATEST_FINDINGS_20260908.md).
- [Local pinned Feature 18 baseline](BASELINE_OPEN_SHADERS_0.4.5.md).
- [Local temporal student implementation](../tools/temporal_student.py).
