# Injector-5 periodic hitch investigation — 2026-10-13

## Corrected runtime evidence

User's working package: original `DuoView-Experimental-Windows-Injector-5`, build run 38316421524, source bd74b21f46aa51c6d535680a005682e2572d6965. The user removed the old STALKER UEVR profile and reports that the package launches and seems to work. The earlier injection failure must not be treated as proof that this public backend is inherently incompatible. The exact stale profile setting responsible has not been identified.

User reports frequent clockwork-like hitches and supplied a SteamVR beta 2.18.3 screenshot at 120 Hz displaying 11.2 ms against an 8.3 ms budget, with repeated bands of activity and low activity. The screenshot does not expose both CPU and GPU histories, actual frame submissions, blocking calls or their timestamps. It cannot establish the root cause or an FPS gain.

## Source inspection

- The original producer/consumer frame gate rejects incomplete or mismatched two-view packets and never intentionally reuses stale atlas output. Rejected packets are a candidate for visible stalls; observe actual frame IDs/rejection state before changing the gate.
- The original DX12 path has blocking xrWaitSwapchainImage and command-context fence retirement. These are necessary ownership barriers, not evidence by themselves of a bug. Removing them would risk GPU resource corruption.
- The compositor caches resources and compiled shaders per retired command slot. Stable dimensions/device/format reuse the pipeline; continuous recompilation is not established by this source path.
- The native gaze bridge retries initialization at a one-second interval until connected. If gaze is unavailable, failed probing could add periodic CPU work. This is a hypothesis, not a demonstrated hitch cause. Disabling gaze is a minimal controlled test.
- XR frame timing and engine work/Lumen/temporal effects remain alternatives. The diagram-like periodic pattern should be correlated with current injector logs or a CPU/GPU frame trace, rather than blamed on ordinary average GPU load.

## Minimum next evidence

Keep the same game scene and output resolution. Compare DuoView with Toolkit gaze disabled, then ordinary Mono. Record whether the periodic pattern persists in each. Obtain current UEVR.log from the post-reset running session, not just Stalker2.log or the old crash reports. If those logs do not expose the waits/rejections, add bounded timing counters to the actual Injector-5 backend before selecting a functional patch. Keep source, fences, paired frame ownership and the user's working package intact.

The compiled Joey-preserving plugin is parallel fallback work. It must not be confused with this user-validated public-backend package. No hitch fix is currently proven or delivered.
