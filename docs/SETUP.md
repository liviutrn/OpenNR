# OpenNR 2.15.0 setup

## Runtime build

Use Visual Studio 2022 C++ tools and its bundled CMake (3.31 or later), Windows SDK/FXC, Git and 7-Zip. The local build wrapper discovers Visual Studio with `vswhere`, initializes the MSVC environment, builds Release, and explicitly disables auto-deployment. Standard output is `E:/OpenNR_Builds/2.15.0`.

External dependencies are consolidated at `C:/OpenNR/Dependencies/runtime-2.15.0`: CommonLib source, a toolset-checked optional prebuilt bundle, FidelityFX source, Streamline/NGX headers, NVAPI, pinned Catch2 and ImGuiVRHelper sources, hde64, CUDA headers and the installed vcpkg dependency tree. The dependency manifest records snapshot hashes. CMake rejected the older CommonLib prebuilt's incompatible compiler version and successfully compiled the source instead.

`private-runtime` contains the locally supplied `nvngx_dlssnr.dll` and `imgui-vr-helper.dll`. The native carrier's SHA-256 is `E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E`; its NVIDIA Authenticode signature was valid. Private inputs are not committed or publicly redistributed.

```powershell
.\tools\Build-OpenNR.ps1
.\tools\Build-OpenNR.ps1 -Targets @('CommunityShaders','cpp_tests','Package-AIO-Manual')
.\native\teacher_bench\build.ps1
.\native\teacher_sequence_bench\build.ps1
```

Use `-Dependencies`, `-BuildRoot` and `-SourceRoot` on the build wrapper for another declared external dependency snapshot or clean source checkout. Dependency installation is intentionally separate from building: the validated local vcpkg tree is used with manifest installation disabled. Native submodules retain their upstream URLs and pins for provenance; a new machine must provision and verify the dependency inputs before building.

## Python research

The validated local interpreter is `C:/OpenNR/Tools/OpenNRTrainVenv/Scripts/python.exe` (Python 3.11.9, PyTorch 2.7.1+cu128, NumPy 1.26.4). Optional model-export/research stacks remain separate; ONNX Runtime is not installed in this training environment and is not required by the ONNX checker validation.

```powershell
$python = 'C:\OpenNR\Tools\OpenNRTrainVenv\Scripts\python.exe'
& $python tools/test_student_v1.py
& $python tools/test_fast_student_v1.py
& $python tools/test_raw_crop_cache.py
& $python tools/test_temporal_capture.py
& $python tools/test_aligned_native_guides.py
& $python tools/test_resume_joint_teacher.py
& $python tools/train_student.py --help
& $python tools/export_fast_student_runtime.py --help
python -m unittest discover -s tests -p test_paths.py -v
```

Do not move virtual environments blindly or install conflicting research stacks over this environment. Record package versions, data manifest hashes, split identity, model configuration and runtime identity for each new run.

## Storage and recovery

Use C: for data/training/tools and E: for native build/package output. Existing compatibility junctions preserve older command paths while resolving physical payloads externally. The canonical Git object database is also on C: through `.git/objects`; refs/index remain in the project. Back up the external object store together with the small Git metadata directory.

Missing H: capture roots remain unavailable. Historical results that depend on them are not currently reproducible. Do not replace those cohorts or reset state silently.
