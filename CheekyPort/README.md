# Cheeky PSVR2/OpenNR r10 experimental port

Status: experimental source integration, not yet headset-validated.

Cheeky source pinned at ClarkCheekyKent/CheekyFoveatedDLSS v0.5.5 (4e47eefe51a512dcaf76bbdc672dcdab5251fc71).
OpenNR policy copied verbatim from r10 stable (3a403d6fea9cc73818b1cdd7473bd6fd9cb5cb98).
OpenNR stable release and Cheeky upstream are not modified.

## Fix A
Fallback for missing OpenXR gaze, dynamically reading PSVR2 Toolkit psvr2_toolkit_capi.dll through its C API.
OpenXR game controller action sets remain untouched. Automatic Steam install lookup or optional PSVR2TK_CAPI_PATH full path.
The 0x148-byte SDK layout, gaze-valid flags, blink status, axis conversion and binocular projections must be checked on the headset.

## Fix B
OpenNR r10 GazeCropPolicy.h is copied without modifications.
r10 filters fixation noise under 2 pixels, bypasses smoothing for deliberate eye movement, and holds crop origin inside its central guard.
Cheeky already corrects motion vectors for overlapping moving crops. Frequent default 12.5%-crop history resets are replaced with
no-overlap resets; remapped views and incompatible crop dimensions still reset. Never force incompatible history.
This is a first port, not a claim of complete r10 render-pipeline equivalence or proven SR/NR regeneration elimination.

## Build and tests
GitHub Actions workflow on this branch clones pinned Cheeky, runs the strict patch script and builds on Windows with MSVC.
It packages Standalone, UEVR and the matching OpenXR installer, uploaded to Actions as test artifacts. No automatic public release.
Verify a successful workflow and matching installer before installation. Existing PSVR2 driver is never replaced.

## Diagnostics
Compare fixed gaze, slow gaze and rapid saccades for DLSS SR alone, NR alone and combined.
Trace VR gaze history resets, D3D12 canonical history reset/correction and DLSS-NR history reset reasons per eye.
Verify gaze projection calibration and left/right mapping in both UEVR and Standalone modes.

Cheeky is GPL-3.0; PSVR2 Toolkit DLL is loaded from user's installation, not redistributed.