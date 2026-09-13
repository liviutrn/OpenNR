# Nasal Convergence 70% change - pending baseline confirmation

The user corrected the current package version to 0.5.7. Intended next package version: 0.5.8.
The checkout and installed MO2 folder located in this run identify 0.5.2 packages; the 0.5.7 source/package location is pending user clarification. Do not distribute or install the preliminary 0.5.3 binary from this run.

Prepared changes:
- Add Nasal Convergence 70% with left UV (0.3, 0.15, 0.7, 0.7), right UV (0, 0.15, 0.7, 0.7).
- Make it the first-run named region; retain Oval mask and Feather blend defaults.
- Lower default NR Intensity, Local Tone, Local Structure from 2.00 to 1.70; the Default UI preset uses those same defaults.
- Update devbench settings description with the geometry and controls.
- Add packager checks for DLL version, preset marker, capture implementation marker, and absence of personal SettingsUser.json.

Verification so far:
- Optimized /O2 LAN variant compiled successfully in the existing Dev-Fast build directory, with SC_DEVFAST_OPTS=OFF and automatic deployment disabled.
- Subrect utility tests: 19 cases, 59 assertions passed.
- No packages created, no installed mod/profile files changed, no game launched.
- In-game SE/VR devbench and headset acceptance remain unverified.

Backup: D:\.CODEX_Projects\DLSS_5_SKYRIM\backups\nasal70-before-0.5.3-20260905-110840
Build log: vendor/open-shaders-dlssnr-vr-091bfb4d/build/build-0.5.3-lan.log