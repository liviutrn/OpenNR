# Cheeky v0.6.3 — minimal DuoView NR view selector

Pinned upstream source: ClarkCheekyKent/CheekyFoveatedDLSS v0.6.3, commit 39bfc96214498e5e21cf861f0eb21f875697b428.
Proven source patch: OpenNR r13, commit ad2d43336318ac3c35f4ad42d1032c258e8f3cfc.

Modes: Both (default/unchanged), View 0 only (DuoView fovea), View 1 only.
Port only applies r13's view-selector gate to native NGX DX11, DX12 and Streamline.
The excluded source executes native game DLSS; UEVR continues to render both views.
Other Cheeky features and upstream 0.6.3 settings are not modified.
Unknown and shared-mono role mappings stay native, never guessed.

The gate is intentionally before private Cheeky SR/NR allocations: therefore it
also bypasses SR/FG interception on the excluded view when those features are
enabled. This matches the working r13 approach. In DuoView NR-only use, this
is precisely the requested effect.

CI: .github/workflows/cheeky-v063-nr-view.yml
Script: CheekyPort/scripts/apply_v063_nr_view.py

Only a successful CI run provides an installable test package. A CI green check
does not prove correct in-headset source ordering or image quality.
