# OpenNR branding and attributions

OpenNR is the public name of this repository and its DLSSNR-focused Skyrim VR distribution.

> A Neural Rendering-focused Open Shaders fork with future support for custom Neural Rendering DLSS models.

## Project lineage

OpenNR is a downstream fork of [Open Shaders](https://github.com/alandtse/open-shaders). Open Shaders is itself a fork of [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders). The inherited architecture, shader pipeline, feature framework, APIs, and much of the source remain attributable to those projects and their contributors.

OpenNR adds and maintains neural-rendering and VR work, including the DLSSNR integration, VR grass-culling improvements, foveated-render fallback safety, and isolated beta/alpha experiment branches. The related feature/package named **OpenNR Capture** is a separate capture mechanism; it is related to this fork but is not the name of the core runtime.

## Compatibility identity

The following names are intentionally retained for binary and mod compatibility:

- `CommunityShaders.dll`
- `SKSE/Plugins/CommunityShaders/`
- `CommunityShaders.log`
- `CommunityShaders` SKSE messages, API names, and interface identifiers

Those compatibility strings do not indicate that OpenNR is the upstream project. They prevent settings, themes, dependent plugins, and existing mod-manager profiles from breaking during the branding transition.

## Licenses and marks

- Source inherited from the fork lineage is distributed under the GNU GPL, as documented in [`COPYING`](./COPYING) and the inherited source headers.
- OpenNR source changes are distributed under the same GPL terms unless a file states otherwise.
- The OpenNR wordmark and icon are project-specific branding assets. They are not part of the GPL-covered source and may be redistributed unchanged only to identify an OpenNR source tree or package. See [`.github/assets/logo/LICENSE`](./.github/assets/logo/LICENSE).
- The upstream Open Shaders logo is intentionally not redistributed or used by OpenNR. Open Shaders and Community Shaders names, logos, Nexus assets, and other marks remain the property of their respective contributors/maintainers.
- Third-party components retain their own licenses. Preserve the license files shipped beside them, including CommonLibSSE-NG, FidelityFX, Streamline, RenderDoc, fonts, ImGui VR Helper, and any vendor runtime notices.
- NVIDIA DLSS/DLSSNR, Streamline, Reflex, and related runtime binaries are vendor components. Their distribution is subject to the vendor license files included with the package; OpenNR does not claim ownership of those binaries.

## Fork obligations

When redistributing OpenNR or publishing a derivative:

1. Keep this notice, [`COPYING`](./COPYING), inherited source headers, and third-party notices.
2. Identify the exact OpenNR, Open Shaders, and Community Shaders source revisions used for a binary package.
3. Do not present OpenNR branding as official Open Shaders or Community Shaders branding.
4. Keep `CommunityShaders.dll` and the compatibility path unless you are making a deliberate ABI-breaking fork and have documented a migration plan.
5. Do not bundle optional proprietary runtimes or experimental alpha features without labeling the package and preserving their licenses.

## Source references

- [OpenNR GitHub repository](https://github.com/olekspa/OpenNR)
- [OpenNR GitLab group](https://gitlab.com/groups/opennr)
- [Open Shaders](https://github.com/alandtse/open-shaders)
- [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders)
- [Open Shaders contributors](https://github.com/alandtse/open-shaders/graphs/contributors)
- [Community Shaders contributors](https://github.com/community-shaders/skyrim-community-shaders/graphs/contributors)
