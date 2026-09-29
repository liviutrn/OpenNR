# Building

## Requirements

- Windows 10/11 x64;
- Visual Studio 2022 with Desktop development with C++;
- Visual Studio CMake tools and a Windows SDK;
- staged NVIDIA DLSS SDK headers/import library under `external\DLSS`;
- staged FFmpeg/FFprobe under `runtime\ffmpeg`;
- standard DLSS under `runtime\nvngx_dlss.dll`;
- the user-supplied DLSSNR runtime under `runtime\dlssnr`.

The project does not fetch or redistribute the NVIDIA/experimental runtime
files. This keeps the private runtime supplied by the operator separate from
the source build.

## One-click build

From Command Prompt:

```bat
build_windows.bat
```

The script validates the staged files, configures a Visual Studio 2022 x64
generator, and builds:

```text
build\Release\DLSSVideoPlayer.exe
```

CMake's post-build step copies the executable's video runtime package,
including FFmpeg, standard DLSS, DLSSNR and documentation.

## Manual build

```bat
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DDLSS_SDK="%CD%\external\DLSS"
cmake --build build --config Release --parallel
```

The build links only against the SDK import library. FFmpeg and the runtime
DLLs are loaded at runtime from the staged package.

## Dependency layout

```text
external\DLSS\include\nvsdk_ngx.h
external\DLSS\lib\Windows_x86_64\x64\nvsdk_ngx_d.lib
runtime\nvngx_dlss.dll
runtime\dlssnr\nvngx_dlssnr.dll
runtime\ffmpeg\ffmpeg.exe
runtime\ffmpeg\ffprobe.exe
```

The long-name DLSSNR file may remain beside its canonical copy for provenance;
the player loads `nvngx_dlssnr.dll`. OpenVR headers/import/runtime files may
remain in the workspace as deferred groundwork, but are not part of the
active target or Release package.

## Verification

Use a short H.264 file first, then test the intended container/codec. Check
`build\Release\DLSSVideoPlayer.log` for:

```text
NGX capability: SuperSampling.Available=1
RAW NGX EvaluateFeature_C SUCCESS
DLSSNR ready: ... version=310.8.0.0
[DLSSNR] Feature 18 evaluate success
Audio: FFmpeg PCM/WaveOut path started
```

VR is intentionally paused in this video-only phase. Build verification covers
desktop video playback, standard DLSS and DLSSNR; headset validation belongs to
a later phase after the preserved presenter is reactivated.
