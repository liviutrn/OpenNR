# Build3 restart checkpoint

This restart derives from OpenNR `64432d0442066715fa442660a0848cf4963640b0`.
Provenance references:

- Baseline workflow run: `38453012351`
- Baseline artifact: `11842620175` (`Joey-101226-Clean-Baseline-Build-3.zip`)
- Backend: `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6`
- SDK: `joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596`
- Frontend: `joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091`

The prior v48 and v49 runs both fell back to Mono. Neither is evidence about
moving-gaze stability. The Mono path remains the default in this restart.

## Implemented first renderer control

`Stable Source / Moving Mask` takes one stable full-frustum Mono image and
samples that same image into both output halves. Full-detail samples are chosen
inside a deterministic mask and coarser samples outside it. This is an
image-processing control only: it saves no scene-render work, is not DuoView,
and does not create two engine views. It is opt-in through
`UEVR_STABLE_SOURCE_MASK=fixed|step|ramp|alternating`; unset or `off` preserves
the original Mono callback path. The variable must be present in the target
game process environment before launch. Setting it only in an injector process
after the game has started has no effect on the target process. Optional
summary logs can be enabled independently with `UEVR_DUOVIEW_DIAGNOSTICS=1`.

The first opted-in GPU callback prepares its D3D12 shader and pipeline and
falls back to the Mono copy as a warmup frame. Unsupported resources, queue or
device mismatches, unsupported color formats, unavailable command-context
retirement, and pipeline errors fall back to Mono and retain an explicit
reason. D3D12 command recording, the copy API return, and accepted copy status
are separate observations. Accepted here means only the OpenXR copy boundary;
it does not mean `xrEndFrame` or headset presentation accepted the image.

The observed frame value is the D3D12 component's `frame_count` at the Mono
copy call site. Its relation to engine source generation, projection frame,
and gaze pose is unproven, and those fields are explicitly marked unavailable.
When opt-in diagnostics or the control is active, the existing logger emits
no more than one aggregate summary per elapsed second, even if the fallback
reason changes every frame. The summary contains the omitted observation count
and fallback, submission-failure, and observed-path counts for that interval.
The portable fixed ring is not connected to the renderer and is not exported.
There is no rolling crash history or causal GPU-boundary capture in this
increment.

## Identical full-frustum two-view comparison (not implemented)

The pinned backend already has an ordinary `Native Stereo` rendering method
(method ID 0); its desired-view hook returns two for the non-Mono native path.
Mono is method ID 5 and requests one view. Strict Synchronized/AFR normally
returns one view, aside from an existing bounded two-frame Ghosting bootstrap
pulse. These source facts make ordinary Native Stereo the candidate path for a
future two-view ownership experiment; they do not prove it is safe or active in
the target game.

Before changing camera geometry, a target run must observe two distinct
engine-owned view states and their generations, stereo roles and render rects,
plus independent shading/history consumption. STALKER 2 UE5.5.4 DX12 has a
lazy ViewState path in strict Synchronized mode: the pinned adapter explicitly
avoids replaying `LocalPlayer::PostInitProperties`, because that path does not
allocate the states; `CalcSceneViewInitOptions` does. That runtime-specific
fact is not a license to manufacture or copy view states. The existing
two-entry eye-state tracker is evidence infrastructure, not proof of distinct
target histories.

The safe experiment order is: first inspect the ordinary two full-frustum
sources, engine roles, rects and state/history owners without changing their
lifecycle; then, only after those observations are valid, test a unified
validated Mono pose/projection while keeping both engine-owned roles and
owners intact. Compare the resolved source views before changing XR output.
XR-calibrated output mapping is a separate validation gate, so a source-view
comparison cannot be reported as a correct submitted stereo image. This cloud
workspace has no STALKER 2 process or headset runtime; none of these probes has
run here.

The Windows workflow is responsible for running the portable replay and
patcher tests, D3D12 WARP oracle tests, the existing compatibility suite, the
matching frontend tests/build, and a generated-source hash verifier. A WARP
test skip is treated as blocked validation, not a pass. Until that workflow
completes, this branch's adapter has not been validated by a Windows build.

## Remaining gates

The identical-full-frustum two-engine-view comparison needs proof of distinct
engine-owned view state and an independently owned shading/history consumer.
The current baseline establishes only its single-view Mono producer and
double-wide copy. No STALKER 2 process, OpenXR headset runtime, or PSVR2 device
is available in this cloud environment, so no real game/headset runtime result
can be claimed here.
