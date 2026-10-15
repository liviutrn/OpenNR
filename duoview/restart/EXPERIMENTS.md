# Build3 restart experiment status

Baseline: OpenNR `64432d0442066715fa442660a0848cf4963640b0`; backend
`joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6`; SDK
`joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596`; frontend
`joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091`.

`Stable Source / Moving Mask` is a diagnostic control only: a single stable,
full-frustum Mono render is used for both eye outputs, and a replay-driven mask
chooses full-detail source samples inside the mask and reduced-detail samples
from that same frame outside it. It does not save scene-render work and does
not mean DuoView or two engine views are active.

The recorded v48 and v49 runs did not activate DuoView; both fell back to Mono.
They provide no moving-gaze stability observation. Runtime results must report
the requested method, the observed effective producer path, and a reason for
each fallback. A successful build alone is not a headset or game-runtime test.

The identical-full-frustum two-engine-view comparison is blocked until the
backend proves distinct engine-owned view state and an independently owned
shading/history consumer. Current Build3 evidence only establishes the original
single-view Mono producer and its double-wide copy.

Replay patterns are deterministic in producer-frame space: fixed, step, ramp,
and four-corner alternating. The mask is associated with the source producer
frame; stale or unavailable source frames must use the original Mono copy and
record the exact reason. The current checkpoint implements only the portable
replay/mapping/observation core; the GPU experiment remains pending.
