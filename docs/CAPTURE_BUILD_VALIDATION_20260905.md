# OpenNR capture build validation — 2026-09-05

The isolated Dev-Fast teacher build is ready for a native temporal capture pass.
No production MGO files were replaced.

Validated source checkout:

```text
D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d
```

Validated build directory:

```text
build\Dev-Fast
```

The generated CMake cache has `BUILD_OPENNR_CAPTURE=ON` and
`AIO_INCLUDE_OPENNR_CAPTURE=ON`. The generated Ninja definitions contain
`OPENNR_CAPTURE_ENABLED`, and the AIO contains the `OpenNRCapture.ini` feature
registration.

The build was rechecked with:

```powershell
cmd /d /c 'call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul && cmake --build build\Dev-Fast --target CommunityShaders AIO --parallel 12'
```

Result: `ninja: no work to do` with exit code 0.

The capture-ready DLL is:

```text
D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d\build\Dev-Fast\aio\SKSE\Plugins\CommunityShaders.dll
```

Its SHA-256 is:

```text
7FAC8BC641EC7BA04FCC308238DD892BA9ABA34D6AE5F454A5646C432CCAFF0A
```

The machine-readable evidence is [out/capture_build_validation_20260905/manifest.json](../out/capture_build_validation_20260905/manifest.json).

The temporal configuration template also passed the project validator:

```powershell
python tools\validate_capture_config.py config\opennr_capture_temporal.example.json
```

The next action is a live capture in an isolated test profile using
`config/opennr_capture_temporal.example.json`. Copying or deploying this build to
the production MGO profile remains a separate decision and has not been done.
