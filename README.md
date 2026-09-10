[![Latest Release](https://img.shields.io/github/v/release/olekspa/OpenNR)](https://github.com/olekspa/OpenNR/releases)
[![License](https://img.shields.io/github/license/olekspa/OpenNR)](./COPYING)
[![Last Commit](https://img.shields.io/github/last-commit/olekspa/OpenNR)](https://github.com/olekspa/OpenNR/commits/dev)
[![Build Status](https://img.shields.io/github/actions/workflow/status/olekspa/OpenNR/release-build.yaml)](https://github.com/olekspa/OpenNR/actions/workflows/release-build.yaml)
[![Open Issues](https://img.shields.io/github/issues/olekspa/OpenNR)](https://github.com/olekspa/OpenNR/issues)
[![Contributors](https://img.shields.io/github/contributors/olekspa/OpenNR)](https://github.com/olekspa/OpenNR/graphs/contributors)
[![Stars](https://img.shields.io/github/stars/olekspa/OpenNR?style=social)](https://github.com/olekspa/OpenNR/stargazers)

[![Pre-commit CI](https://results.pre-commit.ci/badge/github/olekspa/OpenNR/dev.svg)](https://results.pre-commit.ci/latest/github/olekspa/OpenNR/dev)
![CodeRabbit Pull Request Reviews](https://img.shields.io/coderabbit/prs/github/olekspa/OpenNR?utm_source=oss&utm_medium=github&utm_campaign=olekspa%2FOpenNR&labelColor=171717&color=FF570A&link=https%3A%2F%2Fcoderabbit.ai&label=CodeRabbit+Reviews)

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/alandtse/open-shaders)

# OpenNR

**A Neural Rendering-focused Open Shaders fork with future support for custom Neural Rendering DLSS models.**

OpenNR is the public name for this Open Shaders fork and its DLSSNR-focused Skyrim VR distribution. The related **OpenNR Capture** feature/package remains a separate capture mechanism that shares the runtime compatibility layer; it is not the name of the core fork.

[OpenNR repository](https://github.com/olekspa/OpenNR) · [GitLab group](https://gitlab.com/groups/opennr) · [Upstream Open Shaders](https://github.com/alandtse/open-shaders) · [Upstream Community Shaders](https://github.com/community-shaders/skyrim-community-shaders)

## About this fork

**OpenNR is a downstream fork of [Open Shaders](https://github.com/alandtse/open-shaders), which itself is a fork of [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders).** The architecture, shader pipeline, feature framework, and most inherited code originated in those upstream projects. Copyright notices, authorship, GPL terms, and third-party licenses remain in force; see [BRANDING_AND_ATTRIBUTIONS.md](./BRANDING_AND_ATTRIBUTIONS.md) for the complete lineage and distribution policy.

**Naming convention used throughout this repo and the in-game UI:**

| Term                                                             | Refers to                                                                                                                                 |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Community Shaders                                                | The upstream project (`community-shaders/skyrim-community-shaders`, Nexus mod 86492)                                                      |
| Open Shaders                                                     | The immediate upstream fork (`alandtse/open-shaders`)                                                                                     |
| OpenNR                                                           | This project (`olekspa/OpenNR`), focused on neural rendering and VR                                                                        |
| `CommunityShaders` (as a path / filename / identifier in source) | Runtime-compat identifier; intentionally kept identical to upstream so settings, themes, and SKSE plugin discovery work without migration |

OpenNR does not reuse the upstream Open Shaders or Community Shaders logos. Its original wordmark is distributed under the separate policy in [`.github/assets/logo/LICENSE`](./.github/assets/logo/LICENSE). Runtime compatibility names remain unchanged intentionally.

Install from [OpenNR GitHub releases](https://github.com/olekspa/OpenNR/releases) or build from source.

## Requirements

-   Any terminal of your choice (e.g., PowerShell)
-   [Visual Studio Community 2026](https://visualstudio.microsoft.com/)
    -   Desktop development with C++
    -   CMake Tools for Windows
    -   HLSL Tools
-   [Git](https://git-scm.com/downloads)
    -   Edit the `PATH` environment variable and add the Git.exe install path as a new value

## Optional Requirements

```
CMake & Vcpkg comes with Visual Studio in Developer Command Prompts already.
Install them manually only if you want them in everywhere.
```

-   [CMake](https://cmake.org/)
    -   No need to install manually if you have Visual Studio CMake Tools installed
    -   CMake 4.2+ is **required** now
    -   Edit the `PATH` environment variable and add the cmake.exe install path as a new value
    -   Instructions for finding and editing the `PATH` environment variable can be found [here](https://www.java.com/en/download/help/path.html)
-   [Vcpkg](https://github.com/microsoft/vcpkg)
    -   Install vcpkg using the directions in vcpkg's [Quick Start Guide](https://github.com/microsoft/vcpkg#quick-start-windows)
    -   After install, add a new environment variable named `VCPKG_ROOT` with the value as the path to the folder containing vcpkg
    -   Make sure your local vcpkg repo matches the commit id specified in `builtin-baseline` in `vcpkg.json` otherwise you might get another version of a non pinned vcpkg dependency causing undefined behaviour

## User Requirements

-   [Address Library for SKSE](https://www.nexusmods.com/skyrimspecialedition/mods/32444)
    -   Needed for SSE/AE
-   [VR Address Library for SKSEVR](https://www.nexusmods.com/skyrimspecialedition/mods/58101)
    -   Needed for VR

## Build Instructions

### Clone the Repository with submodules

To clone the repository with all submodules, run the following command in your terminal:

```bash
git clone https://github.com/olekspa/OpenNR.git --recursive
cd OpenNR
```

> The DLL filename is `CommunityShaders.dll` and the SKSE plugin directory is `SKSE/Plugins/CommunityShaders/` — identical to both upstream projects, so user settings, themes, and mod-manager profiles remain drop-in compatible. The public and in-game branding is OpenNR.

### Visual Studio build

To build the project, just open `./open-shaders` with Visual Studio's "Open Folder" feature. (Ensure you have `CMake Tools for Windows` selected when installing VS)

Follow the prompts to `Configure` and `Build` the project.
It should generate the AIO package in the `./build/ALL/aio` folder by default.

#### Zip package & Optional targets

If you change the `Solution Explorer` into `CMake Targets View`, you can find optional targets to create zip packages for each feature.
Right click on the target and select `Build` to create the zip package in `./dist/`.

### Advanced build with CMake in command line

Open the "Developer PowerShell for VS 2026" or the "x64 Native Tools Command Prompt" (these set up the Visual Studio toolchain for you).

Then from the repository root run:

```pwsh
# Generate the build files (uses the ALL preset)
cmake --preset ALL

# Build using the preset
cmake --build --preset ALL

# Install an AIO package somewhere, e.g. $MOD_FOLDER
cmake --install --preset ALL -- --prefix $MOD_FOLDER
```

# Notes

-   If you prefer to run the VC environment manually, launch Developer PowerShell or the x64 Native Tools prompt instead of calling vcvarsall.bat directly from PowerShell.
-   The convenience wrapper `BuildRelease.bat` also captures these steps.

#### Build a zip package

You can build zip packages for optional cmake targets.
Currently support `AIO_ZIP_PACKAGE`, `Package-AIO-Manual`, `Package-Core`, and `Package-<Feature>`:

```pwsh
# Create a AIO package in ./dist/
# Automated AIO zip (requires AIO_ZIP_TO_DIST=ON)
cmake --build ./build/ALL --config Release --target AIO_ZIP_PACKAGE

# Manual AIO package (install + tar)
cmake --build ./build/ALL --config Release --target Package-AIO-Manual

# Create a CommunityShaders core package in ./dist/
cmake --build ./build/ALL --config Release --target Package-Core

# Create a feature package in ./dist/ (example: GrassLighting)
cmake --build ./build/ALL --config Release --target Package-GrassLighting
```

The AIO bundles only features marked `autoupload = true` in their feature `.ini` — features not yet ready for release are built but excluded from the AIO. To include everything in a local build, see the `AIO_INCLUDE_NON_AUTOUPLOAD` CMake option.

For more details about packaging targets, options, and the difference between automated and manual packaging, see the ["Manual Packaging Targets"](docs/development/release-process.md#manual-packaging-targets) section in the Release Process guide.

#### CMAKE Options (optional)

If you want an example CMakeUserPreset to start off with you can copy the `CMakeUserPresets.json.template` -> `CMakeUserPresets.json`

#### AUTO_PLUGIN_DEPLOYMENT

-   This option is default `"OFF"`
-   Make sure `"AUTO_PLUGIN_DEPLOYMENT"` is set to `"ON"` in `CMakeUserPresets.json`
-   Change the `"CommunityShadersOutputDir"` value to match your desired outputs, if you want multiple folders you can separate them by `;` is shown in the template example

#### TRACY_SUPPORT

-   This option is default `"OFF"`
-   This will enable tracy support, might need to delete build folder when this option is changed

When using custom preset you can call BuildRelease.bat with an parameter to specify which preset to configure eg:
`.\BuildRelease.bat ALL-WITH-AUTO-DEPLOYMENT`

When switching between different presets you might need to remove the build folder

### Build with Docker

For those who prefer to not install Visual Studio or other build dependencies on their machine, this encapsulates it. This uses Windows Containers, so no WSL for now.

1. Install [Docker](https://www.docker.com/products/docker-desktop/) first if not already there.
2. In a shell of your choice run to switch to Windows containers and create the build container:

```pwsh
& 'C:\Program Files\Docker\Docker\DockerCli.exe' -SwitchWindowsEngine; `
docker build -t open-shaders .
```

3. Then run the build:

```pwsh
docker run -it --rm -v .:C:/open-shaders open-shaders:latest
```

4. Retrieve the generated build files from the `build/aio` folder.
5. In subsequent builds only run the build step (3.)

#### Troubleshooting Build with Docker

If you run into `Access violation` build errors during step 3, you can try adding [`--isolation=process`](https://learn.microsoft.com/en-us/virtualization/windowscontainers/manage-containers/hyperv-container):

```pwsh
docker run -it --rm --isolation=process -v .:C:/open-shaders open-shaders:latest
```

### Build on Linux/macOS (cross-compile, build-only)

For contributors who want to verify their C++ changes compile clean without a Windows machine, install Visual Studio, or use WSL: a Linux/macOS host can cross-compile to the same Windows PE/MSVC-ABI output using `clang-cl`+`lld-link` against an `xwin`-generated Windows SDK/CRT sysroot.

```sh
cmake --preset Linux-ClangCL
cmake --build --preset Linux-ClangCL
```

This proves the toolchain compiles clean; it does not produce a package runnable in-game (struct-layout or vtable mismatches between clang-cl and real MSVC compile fine and only surface as an in-game crash). One-time host setup (xwin, wine, llvm-mingw, vcpkg) is documented in `extern/CommonLibSSE-NG/examples/linux-cross-compile/README.md`.

## Debugging

### Launching MO2-SKSE-Skyrim from commandline

1. Open Steam
2. Close ModOrganizer GUI
3. Add `ModOrganizer.exe` (MO2 Folder) to your PATH, or use the path of it
4. Run the commands:

```pwsh
# Change Working Directory
cd "C:/Program Files (x86)/Steam/steamapps/common/Skyrim Special Edition"
# Launch SKSE with MO2
ModOrganizer.exe --log run "C:\Program Files (x86)\Steam\steamapps\common\Skyrim Special Edition\skse64_loader.exe"
```

### Capture with RenderDoc

In Launch Application Menu, use the following settings:

-   Executable Path: `PATH/TO/ModOrganizer.exe`
-   Working Directory: `C:/Program Files (x86)/Steam/steamapps/common/Skyrim Special Edition`
-   Command-line Arguments: `--log run "C:\Program Files (x86)\Steam\steamapps\common\Skyrim Special Edition\skse64_loader.exe"`
-   [x] **Capture Child Process**

## License

### Default

[GPL-3.0-or-later](COPYING) WITH [Modding Exception AND GPL-3.0 Linking Exception (with Corresponding Source)](EXCEPTIONS.md).  
Specifically, the Modded Code includes:

-   Skyrim (and its variants)
-   Hardware drivers to enable additional functionality provided via proprietary SDKs, such as [Nvidia DLSS](https://developer.nvidia.com/rtx/dlss/get-started) and [AMD FidelityFX FSR3](https://gpuopen.com/fidelityfx-super-resolution-3/)

The Modding Libraries include:

-   [SKSE](https://skse.silverlock.org/)
-   Commonlib (and variants).

### Shaders

See LICENSE within each directory; if none, it's [Default](#default)

-   [Features Shaders](features)
-   [Package Shaders](package/Shaders/)

### Icons

Open Shaders does not ship the upstream Community Shaders logo. The upstream logo is non-GPL, not trademark-licensed, and may only be used in unmodified form with the Community Shaders team's permission — none of which extends to forks. Action icons and category icons are bundled as before; the upstream Discord banner has been removed since the fork has no affiliated Discord channel. The menu renders without a logo image when none is present (the load path is null-safe).

Open Shaders' own logo ([.github/assets/logo](.github/assets/logo)), used in the FOMOD installer header, is non-GPL and unmodified-use only — see the LICENSE file in that directory.
