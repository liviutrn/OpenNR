# Correct A/B baseline for working DuoView v13

This archive is an **independently compiled Mono-only control build**, NOT
official Joey UEVR and NOT DuoView. It shares the exact pinned accessible
public backend, UESDK, and frontend revisions used by the user-tested
DuoView Injector-5 / v13:
- praydog/UEVR: 4ee5c6b6162dee2291fc75f9dfc57667f6d45a2d (2026-08-30)
- elliotttate/UESDK-RenderDoc: 418729025bad57b094bf6b2e2b55734454c97de6
- joeyhodge/uevr-frontend: 60be4b0f9a646109fd9fdf448bacd41477234091
- Mono algorithm references in Joey: becc96692839f0087ccef238f03af618051fb765
  and db6729dd9f5745705b1cdec2ec6f51bdc9570983 (2026-09-26)

**Only** `duoview/apply_public_mono.py` (the public Joey-inspired Mono ID 5
port) is applied to the backend. We DO NOT apply `apply_public_duoview.py`,
`apply_working_stability.py`, or `apply_frame_pacing_v14.py`.
This creates a *controlled test of our base Mono port*, not a replacement
for a real Joey release. It necessarily has the older public backend's
capabilities and excludes all DuoView foveation.

The frontend is built from the exact same pinned joeyhodge frontend used
by the DuoView injector, with unavailable DIBR IDs 3/4 hidden and Mono ID
5 retained. It does NOT display experimental DuoView mode ID 6.

## Use
1. Extract the complete ZIP to a separate directory. Do not overwrite your
   known-smooth October 11 Joey or your DuoView v13/v14 installations.
2. Disable external DuoViewJoey.dll plugin in the game UEVR profile.
3. Start SteamVR, game and inject using the **included** UEVRInjector.exe.
4. OpenXR, Native Stereo 0 first; check for the SteamVR background appearing
   during any drops for 2-3 minutes.
5. Change to Mono ID 5; check the same scene 2-3 minutes. If startup/Mono
   switching itself fails, record that as an important baseline failure.
6. **Do not** try to select DuoView ID 6. This is intentionally Mono-only.

Compare to:
- Official Joey's original 2026-09-26 Mono release:
  https://github.com/joeyhodge/UEVR/releases/tag/092726MONOMODEUEVR
- Official Joey's recent 2026-10-11 release:
  https://github.com/joeyhodge/UEVR/releases/tag/101226HELLRAISERp1
- DuoView user-confirmed foveated v13:
  https://github.com/liviutrn/OpenNR/releases/tag/duoview-working-prototype-stability-v13-build-10

If official Sept Joey runs smoothly but this Mono-only control hitches,
the cause is likely in the *port or older public base*, even before DuoView.
If this Mono-only control runs smoothly but DuoView hitches, isolate the
DuoView-specific view gating/Atlas/GPU copy changes. Neither inference
alone proves a specific root cause.

This control does not fix the headset. It isolates the origin of failures.
