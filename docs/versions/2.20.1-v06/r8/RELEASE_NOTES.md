Experimental OpenNR r8 adds **gradual exterior neural sampling** to the current stereo-atlas, gaze-tracked SR/NR pipeline.

- Run SR over an expanded region around the selected crop.
- Keep normal central NR sampling at the controller's current 100%, 85% or 70% resolution.
- Compress exterior pixels before the same single atlas NR evaluation, with a continuous curve from normal sampling near the centre to configurable 1–20× edge compression.
- Reconstruct the matched neural residual over sharp SR; configure exterior strength and its outer fade.
- Map current/previous warped coordinates, eye origins, depth and motion guides. Retain central pixel anchoring, direct central displacement, stable native atlas guide-layout mode, controller handoffs and near-black protection.
- Bypass the extension in the NR-off stage. The option is **off by default**.

The package includes the plugin, shaders, configurations and bundled dependencies. **`nvngx_dlssnr.dll` is excluded**; keep your compatible copy at `Data/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll`.

Start with **DLSS 5 → Experimental neural feather**: expansion 50%, edge compression 10×, curve 2, exterior strength 1, fade 0.25. Keep your existing SR, crop, gaze and NR tuning. Compare the same scene with the toggle off/on, first in forced stage 1, then stages 3–6 and Auto. Close the menu and allow transitions to settle before measuring.

CPU geometry/motion tests, actual HLSL execution on software D3D11, retained controller/near-black tests, full Windows compilation and payload audit are build gates. Headset image quality and hardware GPU overhead remain in-game checks. **No 0.3–0.4 ms cost is claimed**: a larger SR region adds real cost. At 50% expansion, 10× edge compression and curve 2, the ideal neural pixel count is about 26.6% above the centre alone and the SR area is 2.25× larger, before rounding/guards. Lower expansion can reduce the extra work.

This is a **prerelease** for in-game comparison; the stable r7 release remains unchanged. The bundled README describes the complete current feature set and controls. Package hashes and audits are attached.
