# Local bridge build

The supplied NIGos v1.0.18 source builds with the installed Visual Studio 2022
MSVC toolchain and Windows SDK. The reproducible wrapper is:

```powershell
& 'D:\.CODEX_Projects\DLSS_5_SKYRIM\scripts\Build-DLSS5Bridge.ps1'
```

Output is written to:

`build\dlss5-dx11-bridge-v1.0.18\dlss5-dx11-bridge.addon64`

The feature-input-size probe build completed on 2026-08-29 with version
`1.0.19.0`, size `275,456` bytes, and SHA-256
`3641348B1F92EE486F621736A0309ABFA0A7B4CA4F813C77079E5518C9E99659`.
The staged prototype uses `feature_input=1` in `dlss5-dx11-bridge.cfg`, which
uses `DLSS.Render.Subrect.Dimensions` for feature creation. The previous staged
array-aware binary is preserved under
`backups\prototype-bridge-before-feature-size-20260829`.

The runtime-created array conversion shaders are checked independently with:

```powershell
& 'D:\.CODEX_Projects\DLSS_5_SKYRIM\scripts\Compile-BridgeShaders.ps1'
```

That test currently compiles the depth and motion-vector `Texture2DArray`
passes to Shader Model 5.0.

The upstream source command needs `advapi32.lib` for `RegGetValueW`; the wrapper
adds that library. The original staged release binary is preserved under
`backups\prototype-bridge-before-array-20260829`; the array-aware build is the
one staged in the isolated prototype mod.
