#!/usr/bin/env python3
"""Verify exact Stage 2-4 added/edited source and unchanged original SDK."""
import argparse, hashlib, json, subprocess
from pathlib import Path

EDITED_BACKEND = {
 "src/mods/vr/MonoRenderingPolicy.hpp", "src/mods/vr/CompatibilityPolicy.hpp",
 "src/mods/vr/RenderingMethodSetting.hpp",
 "src/mods/VR.hpp", "src/mods/VR.cpp",
 "src/mods/vr/FFakeStereoRenderingHook.cpp", "src/mods/vr/D3D12Component.hpp",
 "src/mods/vr/D3D12Component.cpp", "tests/MonoRenderingTests.hpp",
}
ADDED_BACKEND = {
 "src/mods/vr/DuoViewOpenNRCropPolicy.hpp", "src/mods/vr/DuoViewSceneLayout.hpp",
 "src/mods/vr/DuoViewGeometry.hpp", "src/mods/vr/DuoViewGaze.hpp",
 "src/mods/vr/DuoViewFovealCamera.hpp",
 "src/mods/vr/DuoViewPSVR2Gaze.hpp", "src/mods/vr/DuoViewCropStability.hpp",
 "src/mods/vr/DuoViewFrame.hpp", "src/mods/vr/DuoViewConfig.hpp",
 "src/mods/vr/DuoViewState.hpp", "src/mods/vr/DuoViewD3D12.hpp",
 "src/mods/vr/DuoViewMonoCopyD3D12.hpp", "src/mods/vr/DuoViewShaderSource.hpp",
}
EDITED_FRONTEND = {"UEVR/RenderingModeOptions.cs", "UEVR/MainWindow.xaml.cs", "tests/RenderingModes/Program.cs"}
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
 if "DuoViewPSVR2Gaze.hpp" not in (a.backend/"src/mods/VR.hpp").read_text(encoding="utf-8"):
  raise RuntimeError("Production VR headers missing native PSVR2 gaze integration")
 vr_cpp=(a.backend/"src/mods/VR.cpp").read_text(encoding="utf-8")
 vr_header=(a.backend/"src/mods/VR.hpp").read_text(encoding="utf-8")
 if any(token in vr_cpp+vr_header for token in ("ngx::service", "DuoViewDlssHistory", "DuoViewDlssHistoryProtection")):
  raise RuntimeError("Removed NGX interception remains in production VR code")
 if (".eye_tracked=m_duo_gaze->value()" not in vr_cpp or
     "m_duoview_gaze.read_uv(frozen,optical)" not in vr_cpp or
     ".temporal_audit=m_duo_history_audit->value()" not in vr_cpp or
     ".smoothing_ms=m_duo_smoothing->value()" not in vr_cpp or
     'm_duo_quantization->draw(' not in vr_cpp):
  raise RuntimeError("Stage5 gaze control is not connected to frame source")
 for token in ('m_duo_history_audit->draw(', 'm_duo_shading->draw(', 'm_duo_width->draw(', 'm_duo_height->draw(', 'm_duo_periphery->draw(',
               'm_duo_density->draw(', 'm_duo_feather->draw(', 'm_duo_debug_source->draw('):
  if token not in vr_cpp: raise RuntimeError("DuoView quality UI missing "+token)
 for token in ('"DuoViewCropWidth"', '"DuoViewPeripheralScale"', '"DuoViewFovealDensity"',
               '"DuoViewFoveaSourceView"', '"DuoViewCropSmoothingMs"', '"DuoViewTemporalAudit"'):
  if token not in vr_header: raise RuntimeError("Persisted DuoView setting missing "+token)
 hook=(a.backend/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
 if '*w=8; *h=8' in hook or 'duoview_scene_rectangle(index,g_hook->m_has_double_precision)' not in hook:
  raise RuntimeError("Startup views must use valid compact atlas rectangles, never tiny dummy views")
 setting=(a.backend/"src/mods/vr/RenderingMethodSetting.hpp").read_text(encoding="utf-8")
 policy=(a.backend/"src/mods/vr/MonoRenderingPolicy.hpp").read_text(encoding="utf-8")
 for token in ('m_selection.initialize_duoview();','void request(int32_t)'):
  if token not in setting: raise RuntimeError("Dedicated mode enforcement missing "+token)
 if 'm_active=pack(duoview_method_id,1)' not in policy:
  raise RuntimeError("DuoView must activate directly, never through ID0")
 for token in ('!vr->is_using_duoview_mono() && !vr->is_ghosting_fix_enabled()',
               'rotate_foveal_view(rotation,frame->config.foveal_camera)',
               'x = duo_extent[0]', 'duoview_scene_extent()[0]'):
  if token not in hook: raise RuntimeError("DuoView startup/render contract missing "+token)
 if "frame->config.settings.fovea_view" not in hook or "duo_frame->config.settings.fovea_view" not in hook:
  raise RuntimeError("Actual source index and UE projection must follow frozen source-view selection")
 if ("apply_frame_projection(double_matrix,*frame" not in hook or
    "reconcile(init_options_ue5->projection_matrix)" not in hook or
    "can_independent_shading(key,state)" not in hook):
  raise RuntimeError("Actual SceneView constructor must receive the frozen projection")
  raise RuntimeError("Frozen producer projection and guarded shading constructor are required")
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
