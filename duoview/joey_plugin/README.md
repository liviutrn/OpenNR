# DuoView Mono — owned-copy integration candidate

DuoView uses the two Native Stereo views as a high-detail crop and a low-detail full-field periphery from one camera. The original Joey `101226HELLRAISERp1` backend remains byte-identical. This revision replaces the engine-atlas overwrite with an owned composite recorded in Joey's acquired OpenXR image command context.

Use OpenXR, Native Stereo (ID 0), Native Fix and compatibility modes off. Mode 2 is fixed fovea; Mode 3 reads PSVR2 Toolkit gaze. Mode 1's old diagnostic is retired. Settings apply on restart. The Scripts panel shows requested mode, copy-contract status, pairing, composites, XR acceptance and fallback reason.

Before any cropped producer, the plugin verifies a native image copied through the actual scene-to-OpenXR boundary and accepted by xrEndFrame, then reserves one of four prewarmed GPU slots. Busy slots leave the entire producer native. Missing/invalid modified producers use a retained coherent image with its actual original pose and stop subsequent modified producers. No pose-time/submit-time equality is required. Actual D3D12/XR/device faults stop the modified path; an image without a copy proof is never advertised as valid.

The copy hook uses the exact embedded-commit C++ signature, including optional std::function objects and shared_ptr, and the exact CommandContext header. Windows tests include cross-DLL ABI forwarding/destruction, copy decisions/proof, and owned-copy WARP pixel readback with the D3D12 debug layer and SRVMask source restoration. These tests do not replace STALKER 2 headset validation or prove a measured FPS/PPD gain.

Install with `powershell -ExecutionPolicy Bypass -File .\Install-DuoView.ps1 -Mode 2` while STALKER 2 is closed, then inject with `JoeyOriginal\UEVRInjector.exe`. Remove the profile plugin and script to restore ordinary Joey. The installer backs up previous DuoView files and leaves other plugins untouched.

The older modified-backend version delivered approximately 50 PPD, useful FPS, and gaze tracking according to Liviu, but hitched. Those results remain the quality/performance reference. This candidate must establish a coherent fixed-fovea scene first. Defaults preserve baseline foveal density while reducing nominal scene pixels; increasing internal density alone cannot exceed the output image's sampling capacity.
