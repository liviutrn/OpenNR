# Troubleshooting

## Start with the log

The log is beside the running executable. Useful milestones are:

```text
Video decoder selected: FFmpeg
NGX capability: SuperSampling.Available=1
RAW NGX EvaluateFeature_C SUCCESS
DLSSNR ready: ...
[DLSSNR] Feature 18 evaluate success
```

The title/status bar separates standard SR and NR state. A loaded DLL or a
smooth desktop frame is not by itself proof that every neural frame was used;
check the evaluation milestones in the log.

## DLSS is unavailable

Check that `nvngx_dlss.dll` is beside the EXE and that the GPU driver supports
the requested NGX path. The player continues with its D3D12 conversion/fallback
path if capability probing or feature creation fails.

Use `F6` after external tooling has finished initializing. `DLSSVideoPlayer.log`
will show the NGX result code.

## DLSSNR is unavailable or fails

Check:

- `dlssnr\nvngx_dlssnr.dll` exists beside the EXE;
- the file is the intended authorized runtime;
- standard DLSS is available for an upscaled DLSSNR run;
- the log reports `DLSSNR ready` and a Feature 18 evaluation success.

The direct mismatched input/output contract is known to return
`0xBAD00005` on the tested runtime. The player avoids that as its normal
upscale route by running standard DLSS first and evaluating Feature 18 at the
final size. A remaining error is reported and the last usable image is shown.

## No audio

The player launches the staged `ffmpeg\ffmpeg.exe` and converts the first audio
stream to stereo 48 kHz PCM. If audio does not start, check the log for
`Audio: FFmpeg PCM/WaveOut path started`; files with unusual stream layouts may
need to be tested with another audio stream or container.

## Video does not open

FFmpeg is tried first, followed by Media Foundation. Confirm that the FFmpeg
folder contains its EXE and dependent DLLs. The Open dialog accepts all files;
drag-and-drop can bypass extension filters.

## Playback drops frames

The audio clock remains authoritative and late video frames are dropped rather
than slowing the movie. Try Balanced or Performance quality, reduce the output
size, or use standard DLSS instead of NR. `drop N` in the status bar reports
the count.

## Flicker or shimmer during playback

The current video build presents with VSync and does not add camera jitter to
decoded frames. Update/rebuild so the log contains:

```text
Video present pacing: VSync (tearing disabled for stable playback)
```

Then compare `1` (Final), `2` (DLSS input), `3` (motion) and `4` (depth). If
the input is stable but Final flickers, try **Frame guidance: Zero guides**,
then **Motion only** or **Depth only**. Reconstructed guides are estimates, so
cuts, fast camera motion, compression noise and overlays can still make the
experimental Feature 18 runtime shimmer. Seeking and any tuning change reset
its temporal history.

## VR

VR presentation is paused in the current video-only build. `--vr`,
`--vr-layout`, `V` and `Ctrl+Alt+V` are intentionally
unavailable. The OpenVR presenter, headers/import library and loader remain
preserved for a later phase.

## Seek or close hangs

Seeking stops the audio/decoder workers, waits for in-flight GPU work, resets
temporal history and reopens the decoder. If a file still fails, include the
container/codec information and the last part of `DLSSVideoPlayer.log`.
