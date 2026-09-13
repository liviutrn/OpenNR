# Architecture

## Frame path

```text
video file
  |
  +--> FFmpeg BGRA decode ---------> audio PCM -> WaveOut clock
  |
  +--> compact temporal analysis
          |
          +--> motion / depth / disocclusion guide grid
                         |
                         v
                    D3D12 guide expansion
                         |
                         +--> linear FP16 color
                         +--> RG16F motion
                         +--> D32/R32 depth
                         +--> R8 correspondence mask
                                      |
                 +--------------------+-------------------+
                 |                                        |
          standard DLSS SR                         Feature 18 NR
          render -> output                         same-size contract
                 |                                        |
                 +--------------------+-------------------+
                                      |
                             post-processing shader
                                      |
                             desktop swapchain
```

`VideoDecoder` prefers the bundled FFmpeg helper because it covers more
containers/codecs consistently. It falls back to Windows Media Foundation if
FFmpeg probing or process startup fails. Audio is decoded separately to
stereo 48 kHz PCM and drives the playback clock when available.

## Temporal guides

`TemporalGuideGenerator` keeps a compact luma history, estimates current-to-
previous motion, derives a conservative depth proxy and marks uncertain
correspondences. The compact RGBA32F grid is uploaded each frame. D3D12
expands it to the exact render size using a fullscreen pass, then writes depth
directly into the typeless resource passed to NGX.

The guides are reconstructed from video. They are not the original scene
depth, motion-vector or material buffers from a game engine.

The guide expansion has a player-side frame-guidance mode: both guides, zero
guides, motion only, or depth only. The mode still binds valid resources because
Feature 18 expects resource parameters even when a guide is intentionally
neutralized.

## DLSS and DLSSNR

`DLSSBackend` uses the official NGX SDK declarations/import library for
Super Resolution. It keeps the raw `CreateFeature` and `_C` evaluate entry
points visible so external inspection/add-on tooling can observe the normal
DLSS contract.

`DLSSNRBackend` loads the supplied `nvngx_dlssnr.dll` separately, locates the
NGX core parameter allocator and invokes Feature 18. The parameter wrapper
uses the verified raw slot mapping from the ComfyUI bridge because the
driver-created wrapper's slot order differs from the public C++ declaration
order for this experimental runtime.

The live tuning block forwards the reference bridge's scalar parameters
(`Intensity`, `LocalToneStrength`, `LocalStructureStrength`,
`SkinStructureStrength`, `UseAutoMask`, `Style`, `UICorrection`) and the
runtime-advertised preset hint. It also forwards depth convention and motion
scale values. The player does not bind `UI`, `UIAlpha`, `ControlMask`,
`Backbuffer` or `BidirectionalDistortionField`, because a normal movie has no
separated versions of those game resources.

The runtime accepts a reliable same-size contract on the tested GPU/runtime.
When render and output sizes differ, `D3D12Renderer` first evaluates standard
DLSS into the output-sized FP16 resource, expands a second set of guides at
that size, and invokes Feature 18 with final-size color/depth/motion/output.
This avoids repeatedly submitting the rejected direct upscaled contract.

## GPU lifetime

The renderer owns three command allocators, upload buffers and frame fences.
Resource states are tracked explicitly for copy, render-target, depth-read,
non-pixel-shader-read, UAV and presentation use. NGX feature creation is
flushed once before the first evaluation; ordinary frame rendering remains
asynchronous.

## Deferred VR groundwork

`src/VRPresenter.*` remains as isolated groundwork for a later headset phase.
It is intentionally not compiled or linked by the active target, and the
current frame path ends at the desktop swapchain. This keeps the present
acceptance surface limited to video decoding, desktop presentation, DLSS and
DLSSNR.

## Presentation and diagnostics

The final shader converts linear FP16 output back to sRGB and applies the
user's brightness, contrast, saturation, gamma, temperature and tint. Debug
views select the input, motion, depth or bias resources. Decoded video uses
zero synthetic camera jitter and a VSync swapchain; while paused, the existing
frame is re-presented without decoding, except when a user changes a tuning
control, which triggers one explicit re-evaluation.
