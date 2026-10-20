# v182 fused Glamarye fovea sharpening (experimental)

Unchanged archived baseline: https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v182

This experimental branch fuses the Glamarye v0.1 intelligent-sharpen algorithm into the existing native DuoView composition shader. It works on already-DLSS-upscaled foveal samples, in units of final output pixels, instead of adding an extra OpenXR layer pass over both eyes.

- UI: DuoViewGlamaryeFoveaStrength (0–2), default 1.0 on new profiles (0 fully disables sharpening; existing saved profiles retain their saved values); 0.4 was the initial v0.1 comparison strength.
- Foveal source Unreal view 0 or 1 is selected through original v182 settings. Final Mono output is copied to both headset eyes unchanged.
- Larger radius, jagged-edge protection, max change 0.10 and FXAA bias 0.02 reproduce v0.1 settings.
- Enabled sharpening forces the existing single-width composition-and-copy route (not the duplicated double-wide direct-XR raster path). No additional OpenXR hook, GPU copy, queue synchronization or shader compilation on the XR render thread.
- External Glamarye OpenXR layer must be disabled when testing fused sharpening; otherwise it will sharpen twice.

Quality caveat: center-pixel sampling scale matches v0.1. At feather/crop boundaries the operations differ: this version sharpens focus *before* mixing, while v0.1 sharpens the final blended image. Foveal sample neighborhoods are clamped to the native source texture. Validate image appearance in the headset.

At 3136x2768 per eye with a 50%x50% fovea, sharpening arithmetic covers ~2.17M focus pixels instead of ~17.36M double-wide XR output pixels. This is work-area math, NOT a validated performance or FPS claim. The compositing raster still covers the full Mono image.

Tests: compile offline DXBC (including native fused pixel shader); independent state/config tests; WARP raster tests; full backend/SDK injector build on Windows CI. Run same-scene PSVR2 visual and timing comparisons before calling it validated.

Other investigations: avoid unconditional periphery sampling inside solid focus; reduce full-output color/composition passes; profile hidden full-size Unreal intermediate and G-buffer passes; evaluate accurate lower-cost SDR transfer functions; avoid adding GPU readback/fence waits.