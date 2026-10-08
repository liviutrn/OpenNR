# OpenNR 2.20.1-v06-r7 eye tracking

OpenNR uses native OpenVR gaze automatically when a compatible provider is available. For PSVR2 on PC, keep PSVR2 Toolkit eye tracking active in your SteamVR/OpenVR session. The provider reads the game's existing OpenVR interface; this package does not install a separate OpenVR runtime or an OpenXR layer.

Enable foveated upscaling and DLSS, select a cropped region, and enable Neural Rendering. The crop follows gaze while keeping the selected crop dimensions. The adaptive controller changes crop size relative to that selection; it does not take ownership of the gaze centre.

## Controls

- **Gaze smoothing:** 0–250 ms. Zero adds no gaze smoothing. Start at zero for immediate response.
- **Crop movement quantization:** 0–64 input pixels. Zero turns optional movement quantization off. This does not disable the internal sampling-grid alignment needed to keep SR, depth and motion guides consistent.
- **Freeze crop at selected centre:** fixed-crop comparison. Turn it off to resume gaze following.
- **Diagnostics:** provider/API, focus, native-query validity, dynamic/static crop, fallback, history-reset state, query age/cost, crop-change/reset counters and filtered gaze coordinates.

There is no configurable gaze deadzone in this version. The motion/guide alignment and crop-history handling support moving gaze without requiring a deadzone. Small optional quantization can reduce tracker noise, but adds discrete movement; it is not required by the controller.

## Fallback and transitions

Invalid queries briefly retain the last valid crop, for up to 50 ms, before returning to the selected static crop. Availability, focus, menu/loading state and geometry checks can also select a static fallback. Diagnostics show whether gaze is dynamic or using fallback. Query age measures time since the last valid application query; it is not the headset sensor's age or end-to-end latency.

SR/NR crop sampling, guide offsets and motion compensation stay aligned as the crop moves. Compatible size changes use the resident allocation and residual handoff paths. Real route/layout changes and failures may still invalidate history. When NR returns from its suspended controller stage, it waits for committed crop geometry, resets stale NR history once and fades the neural correction back in.

For testing, use DLSS Performance (0.5 per axis), a Center 50% crop, zero gaze smoothing and zero optional quantization. Compare gaze following with Freeze crop, keeping the same scene and controller stage. Close the menu and let transitions settle before judging the image or frametime.

The provider and alignment checks are covered by source/CPU/software-D3D11 verification. Visual acceptance still requires the actual headset and runtime.
