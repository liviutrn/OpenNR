#!/usr/bin/env python3
"""Verify exact Stage 2-4 added/edited source and unchanged original SDK."""
import argparse, hashlib, json, subprocess
from pathlib import Path

EDITED_BACKEND = {
 "src/mods/vr/MonoRenderingPolicy.hpp", "src/mods/vr/CompatibilityPolicy.hpp",
 "src/mods/VR.hpp", "src/mods/VR.cpp",
 "src/mods/vr/FFakeStereoRenderingHook.cpp", "src/mods/vr/D3D12Component.hpp",
 "src/mods/vr/D3D12Component.cpp", "src/mods/vr/runtimes/OpenVR.cpp",
 "tests/MonoRenderingTests.hpp",
}
ADDED_BACKEND = {
 "src/mods/vr/DuoViewGeometry.hpp", "src/mods/vr/DuoViewGaze.hpp",
 "src/mods/vr/DuoViewPSVR2Gaze.hpp", "src/mods/vr/DuoViewCropStability.hpp",
 "src/mods/vr/DuoViewFrame.hpp", "src/mods/vr/DuoViewConfig.hpp",
 "src/mods/vr/DuoViewState.hpp", "src/mods/vr/DuoViewD3D12.hpp",
 "src/mods/vr/DuoViewMonoCopyD3D12.hpp", "src/mods/vr/DuoViewShaderSource.hpp",
}
EDITED_FRONTEND = {"UEVR/RenderingModeOptions.cs", "tests/RenderingModes/Program.cs"}
GENERATED_FRONTEND = {"UEVR/FilteredExecutables.json"}

def git(root,*args):
 return subprocess.check_output(["git","-C",str(root),*args],text=True).strip()
def sha(p):
 return hashlib.sha256(p.read_bytes()).hexdigest()
def tracked(root):
 return set(git(root,"diff","--name-only","HEAD").splitlines())
def untracked(root):
 return set(git(root,"ls-files","--others","--exclude-standard").splitlines())

def main():
 p=argparse.ArgumentParser()
 p.add_argument("backend",type=Path)
 p.add_argument("frontend",type=Path)
 p.add_argument("evidence",type=Path)
 p.add_argument("--final",action="store_true")
 a=p.parse_args()
 assert git(a.backend,"rev-parse","HEAD")=="5ac7edc207866569334175e4ed8a7517971547f6"
 assert git(a.frontend,"rev-parse","HEAD")=="60be4b0f9a646109fd9fdf448bacd41477234091"
 sdk=a.backend/"dependencies/submodules/UESDK"
 assert git(sdk,"rev-parse","HEAD")=="3cffbc82429b6165ceec2714f0f0d9ae48f55596"
 if git(sdk,"status","--porcelain"): raise RuntimeError("SDK source not clean")
 bdiff=tracked(a.backend)
 if bdiff!=EDITED_BACKEND: raise RuntimeError(f"Wrong backend edited paths: {bdiff ^ EDITED_BACKEND}")
 buntracked=untracked(a.backend)
 if buntracked!=ADDED_BACKEND: raise RuntimeError(f"Unexpected added backend paths: {buntracked ^ ADDED_BACKEND}")
 fdiff=tracked(a.frontend)
 if fdiff - (EDITED_FRONTEND|GENERATED_FRONTEND) or not EDITED_FRONTEND.issubset(fdiff):
  raise RuntimeError(f"Unexpected frontend tracked changes: {fdiff}")
 if untracked(a.frontend): raise RuntimeError("Unexpected untracked frontend source")
 geometry=(a.backend/"src/mods/vr/DuoViewGeometry.hpp").read_text(encoding="utf-8")
 if '.fovea = {0, 0, fw, fh}' not in geometry or '.periphery = {fw, 0, pw, ph}' not in geometry:
  raise RuntimeError("Legacy atlas order must be preserved in applied source")
 # A shipping DuoView must never compile shaders on the OpenXR copy path.
 compositor=(a.backend/"src/mods/vr/DuoViewD3D12.hpp").read_text(encoding="utf-8")
 shaders=(a.backend/"src/mods/vr/DuoViewShaderSource.hpp").read_text(encoding="utf-8")
 if "D3DCompile(" in compositor or "shader_source" in compositor:
  raise RuntimeError("Runtime shader compiler still in production compositor")
 if "DuoViewState.hpp" not in (a.backend/"src/mods/VR.hpp").read_text(encoding="utf-8"):
  raise RuntimeError("Production VR headers missing DuoView frame state")
 vr_cpp=(a.backend/"src/mods/VR.cpp").read_text(encoding="utf-8")
 vr_header=(a.backend/"src/mods/VR.hpp").read_text(encoding="utf-8")
 if (".eye_tracked=false" not in vr_cpp or
     ".fixed_center_v=m_duo_center_v->value()" not in vr_cpp or
     "m_duo_gaze->draw(" in vr_cpp):
  raise RuntimeError("Fixed-center production control must not expose eye tracking")
 for token in ('m_duo_center_v->draw(', 'm_duo_width->draw(', 'm_duo_height->draw(', 'm_duo_periphery->draw(',
               'm_duo_density->draw(', 'm_duo_feather->draw(', 'm_duo_debug_source->draw('):
  if token not in vr_cpp: raise RuntimeError("DuoView quality UI missing "+token)
 for token in ('"DuoViewCropWidth"', '"DuoViewPeripheralScale"', '"DuoViewFovealDensity"',
               '"DuoViewCropSmoothingMs"', '"DuoViewCropSmoothingMs"'):
  if token not in vr_header: raise RuntimeError("Persisted DuoView setting missing "+token)
 hook=(a.backend/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
 if "frame->config.settings.fovea_view" not in hook or "duo_frame->config.settings.fovea_view" not in hook:
  raise RuntimeError("Actual source index and UE projection must follow frozen source-view selection")
 if ("apply_frame_projection(double_matrix,*frame" not in hook or
     "can_native_fix_secondary_source(key,state)" not in hook or
     "views_original_count=views->count" not in hook):
  raise RuntimeError("DuoView source-parity constructor transaction or original-family restoration contract absent")
 # An incomplete DuoView atlas must never be presented as a full mono scene.
 # Persistent failure must request genuine mode5 on the game thread, never ID0.
 backend_copy=(a.backend/"src/mods/vr/D3D12Component.cpp").read_text(encoding="utf-8")
 if "duoview_quarantined" in vr_header or "duoview_quarantined" in vr_cpp:
  raise RuntimeError("Prohibited DuoView-to-Mono quarantine detected")
 if "m_openxr.duoview_compositors" not in backend_copy or "duoview_abort" not in backend_copy:
  raise RuntimeError("OpenXR DuoView fault handling missing")
 if ("DuoView OpenVR compositor" not in backend_copy or
     "OpenVR paired-source composition unavailable" not in backend_copy):
  raise RuntimeError("OpenVR two-view DX12 presentation path missing")
 if "can_native_fix_secondary_source" not in (a.backend/"src/mods/vr/DuoViewState.hpp").read_text(encoding="utf-8"):
  raise RuntimeError("Dedicated guarded Native Fix source pair proof missing")
 if ("m_duoview_ever_presented" not in vr_header or
     "should_fallback_to_mono(failures,ever_presented)" not in vr_cpp or
     "OpenXR frame/projection gate not ready" not in backend_copy or
     "m_duoview_consecutive_failures" not in vr_cpp or
     "m_duoview_fallback_requested.exchange(false" not in vr_cpp or
     "m_rendering_method->request(RenderingMethod::MONO)" not in vr_cpp or
     "m_rendering_method->request(RenderingMethod::NATIVE_STEREO)" in vr_cpp or
     "should_fallback_to_mono(failures)" not in vr_cpp):
  raise RuntimeError("DuoView failure must request genuine Joey Mono ID5 only from game thread")
 if "m_openvr.copy_left_to_right(backbuffer.Get(),scene_source_state)" not in backend_copy:
  raise RuntimeError("OpenVR Joey Mono must duplicate complete first scene half to second eye")
 if 'duoview_abort("D3D12 setup/device/swapchain preparation failed")' not in backend_copy:
  raise RuntimeError("DX12 prewarm/RT setup errors must trigger DuoView-to-Mono policy")
 if "owner->is_using_mono()" not in (a.backend/"src/mods/vr/runtimes/OpenVR.cpp").read_text(encoding="utf-8"):
  raise RuntimeError("OpenVR Mono ID5 missing shared binocular optical calibration")
 if ".openxr = runtime != nullptr && (runtime->is_openxr() || runtime->is_openvr())" not in vr_cpp:
  raise RuntimeError("Original Joey Mono ID5 fallback is not legal on SteamVR OpenVR")
 if "m_duo_center_v->value()" not in vr_cpp or "m_duoview_autostart_done" not in vr_header:
  raise RuntimeError("Startup or fixed-center vertical control not connected")
 openvr=(a.backend/"src/mods/vr/runtimes/OpenVR.cpp").read_text(encoding="utf-8")
 if ("uevr::mono::geometry(optical)" not in openvr or
     "owner->is_using_mono()" not in openvr or
     "this->view_bounds[eye][edge]=common->bounds[eye][edge]" not in openvr):
  raise RuntimeError("OpenVR shared Mono optical calibration or per-eye submission bounds missing")
 if ".fovea_view=static_cast<uint32_t>(m_duo_fovea_view->value())" not in vr_cpp:
  raise RuntimeError("UE source selector must be connected to immutable frame settings")
 if "vertex_shader_bytecode[]" not in shaders or "pixel_shader_bytecode[]" not in shaders:
  raise RuntimeError("Precompiled DXBC shader arrays missing")
 inputs = sorted(EDITED_BACKEND | ADDED_BACKEND)
 hashes = {"backend":{k:sha(a.backend/k) for k in inputs},
           "frontend":{k:sha(a.frontend/k) for k in sorted(EDITED_FRONTEND)}}
 lock=a.evidence/"duoview-stage234-hashes.json"
 if a.final:
  if json.loads(lock.read_text())!=hashes: raise RuntimeError("Stage 2-4 source mutated during compile")
 else:
  lock.write_text(json.dumps(hashes,indent=2)+"\n")
 print("Stage 2-4 exact source, proprietary SDK isolation and source hashes verified.")

if __name__=="__main__":
 main()
