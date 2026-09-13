# DLSS5 / DLSSNR setup

## Supplied runtime

This project is already staged with the operator-provided file:

```text
runtime\dlssnr\nvngx_dlssnr.dll
```

The original descriptive filename is retained beside it. The player loads the
canonical name. To test another authorized runtime without changing the
package, pass an explicit path:

```bat
DLSSVideoPlayer.exe "D:\Videos\test.mkv" --mode dlssnr --dlssnr "D:\private\nvngx_dlssnr.dll"
```

The supplied file reports version `310.8.0.0` and is experimental. Its
Authenticode state is modified/unverified on this machine; keep it private and
do not redistribute it. Do not mix an unrelated standard `nvngx_dlss.dll`
with a neural runtime unless you are deliberately testing that combination.

## What the player calls

The player uses two independent paths:

1. standard NVIDIA NGX Feature 1 (Super Resolution/DLAA), using
   `runtime\nvngx_dlss.dll`;
2. experimental NGX Feature 18 (DLSSNR), using the supplied neural DLL.

In DLSSNR mode, a resolution change is handled as:

```text
decoded video -> approximate guides -> standard DLSS SR -> final-size guides
               -> Feature 18 NR -> desktop presentation
```

The direct Feature 18 path is used for same-size processing. The tested
runtime returns `0xBAD00005` for the mismatched direct upscaling contract, so
the player uses the two-stage path and records a safe fallback if either stage
is unavailable.

## Recommended checks

Start with standard DLSS:

```bat
DLSSVideoPlayer.exe "D:\Videos\test.mkv" --mode dlss --quality quality
```

Then test the supplied neural path:

```bat
DLSSVideoPlayer.exe "D:\Videos\test.mkv" --mode dlssnr --quality balanced
```

Look in `DLSSVideoPlayer.log` for:

```text
NGX capability: SuperSampling.Available=1
RAW NGX EvaluateFeature_C SUCCESS
DLSSNR ready: ... version=310.8.0.0
[DLSSNR] Feature 18 evaluate success
```

An unavailable runtime does not prevent ordinary video playback. A failed NR
evaluation falls back to the standard DLSS or converted input frame.

## Live NR controls

The **Image adjustments** panel (`Ctrl+E`, or `Ctrl+Alt+C` when ReShade owns the
normal input path) exposes the controls forwarded to Feature 18:

- intensity, local tone, local structure and skin structure (`-1..2`);
- style (`0..2`) and the experimental private preset index (`0..3`);
- automatic mask and UI correction;
- depth convention, frame guidance (both / zero / motion-only / depth-only),
  and motion-vector X/Y scale (`-4..4`).

The control values are saved in the `[DLSSNR]` section of
`DLSSVideoPlayer.ini`. The preset/style fields are visible because the runtime
advertises them, but the supplied 310.8.0.0 build may keep them inert; the
player logs the requested values but cannot claim a visual difference without
an A/B comparison on that runtime. UI correction also lacks a real separated
game HUD/control-mask buffer for ordinary video.

The video path disables synthetic camera jitter and uses VSync presentation to
reduce temporal shimmer and swapchain tearing. A control change while paused
re-renders the current displayed frame and resets temporal history.

## Why this is not the complete game DLSS suite

Generic video has no original G-buffer, ray-hit data, object motion vectors or
engine display-timing contract. Therefore this player exposes the DLSS
operations that can be represented honestly for a decoded movie: SR/DLAA and
the experimental Feature 18 neural pass. It does not fabricate Frame
Generation or Ray Reconstruction inputs, and it cannot supply separated UI,
UI-alpha, backbuffer or distortion-field resources from a composited movie.
