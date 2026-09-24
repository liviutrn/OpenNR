# OpenNR 2.16.0 release-candidate validation

Date: 2026-09-22. This record is for the local source/build/package update.
It does not authorize remote publication, game installation, or a SkyrimVR/HMD
run.

## Source snapshot

- OpenNR branch: `codex/opennr-upstream-refresh-20260922`
- Open Shaders `dev`: `fd6350ca7e82a52a8f578c8aaa62def53f051f72`
- Internal PR #606 head: `edf1dc9e29f875b68555f82de35b322e66966e19`
- CommonLibVR: `adb3e2c4dff61d151370a6777ed9e77f8e005c62`
- Streamline-DX12: `2122257e0fce486f91b385aa63b9a09b0a34b363`
- Version: `2.16.0`

## Deliverable

- Expected AIO: `E:/OpenNR_Builds/2.16.0/dist/OpenNR 2.16.0.7z`
- Archive bytes: `228749798` (219 MiB, 7-Zip 7z/LZMA2)
- Archive SHA-256: `E66DF09862624F2942A2B3E55DBC84A5B65B95444C2BDA22CEEE5D68818C346D`
- DLL version: `2.16.0.0` (`CommunityShaders.dll`, 23,439,872 bytes)
- DLL SHA-256: `7B80C24A42E9861161EF1ECF7EC8026A7E89137634C054CF7B49515AFBAB9961`
- DLSSNR carrier SHA-256: `E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E`

## Validation evidence

The following fields are intentionally filled only from the fresh local run:

- Configure/build: passed with Visual Studio 2022/MSVC 19.44.35228, CMake 3.31,
  `CommunityShaders` and `cpp_tests` targets, and the generated scene-settings
  catalog (`1046` entries).
- C++ tests and assertions: passed — `227` test cases and `9481` assertions.
- CTest: passed — `CppUtilTests` `1/1`.
- Shader/config/source-contract validation: passed — OpenNR source-contract
  validation passed during the plugin build; the AIO/package validator passed
  for the complete staged tree and the lean release stage.
- Package manifest and staged-file validation: passed — complete AIO tree has
  `526` files; the lean release archive has `521` files and exactly one
  versioned changelog (`OPENNR-2.16.0-CHANGELOG.md`).
- 7-Zip integrity and extracted-file hash comparison: passed — `7z t` reports
  `Everything is Ok`; extraction produced `521` files, with matching SHA-256
  for `CommunityShaders.dll`, `nvngx_dlssnr.dll`, and the 2.16.0 changelog.
  The archive contains no stale 2.15.1 changelog.

## Acceptance boundary

No game or headset run is included. Even a clean source/build/package result
does not establish stereo correctness, full-eye/subrect behavior, eye-tracking
response, temporal appearance, native reset cost, SteamVR compositor behavior,
or sustained VR frame time. No model, teacher capture, optical-flow route, or
closed carrier is promoted by this package.
