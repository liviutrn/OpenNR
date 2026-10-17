#!/usr/bin/env python3
"""Verify exact Stage 2-4 added/edited source and unchanged original SDK."""
import argparse, hashlib, json, subprocess
from pathlib import Path
from verify_source_review import verify as verify_review_regressions, block as source_block

EDITED_BACKEND = {
 "src/mods/vr/MonoRenderingPolicy.hpp", "src/mods/vr/CompatibilityPolicy.hpp",
 "src/Framework.hpp", "src/Framework.cpp",
 "src/mods/VR.hpp", "src/mods/VR.cpp",
 "src/mods/vr/FFakeStereoRenderingHook.cpp", "src/mods/vr/D3D12Component.hpp",
 "src/mods/vr/D3D12Component.cpp", "src/mods/vr/runtimes/OpenVR.cpp",
 "src/mods/vr/runtimes/OpenXR.cpp",
 "src/mods/vr/d3d12/CommandContext.hpp", "src/mods/vr/d3d12/CommandContext.cpp",
 "tests/MonoRenderingTests.hpp",
}
ADDED_BACKEND = {
 "src/mods/vr/DuoViewGeometry.hpp", "src/mods/vr/DuoViewGaze.hpp",
 "src/mods/vr/DuoViewPSVR2Gaze.hpp", "src/mods/vr/DuoViewCropStability.hpp",
 "src/mods/vr/DuoViewFrame.hpp", "src/mods/vr/DuoViewConfig.hpp",
 "src/mods/vr/DuoViewState.hpp", "src/mods/vr/DuoViewBootstrap.hpp", "src/mods/vr/DuoViewD3D12.hpp",
 "src/mods/vr/DuoViewCommandRecovery.hpp", "src/mods/vr/DuoViewMonoCopyD3D12.hpp",
 "src/mods/vr/DuoViewShaderSource.hpp",
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
 p.add_argument("--source-only",action="store_true",
                 help="Verify exact transformed source before shader embedding; do not expect DXBC header")
 a=p.parse_args()
 verify_review_regressions(a.backend)
 assert git(a.backend,"rev-parse","HEAD")=="5ac7edc207866569334175e4ed8a7517971547f6"
 assert git(a.frontend,"rev-parse","HEAD")=="60be4b0f9a646109fd9fdf448bacd41477234091"
 sdk=a.backend/"dependencies/submodules/UESDK"
 sdk_tree=git(a.backend,"ls-tree","HEAD","dependencies/submodules/UESDK")
 if "160000 commit 3cffbc82429b6165ceec2714f0f0d9ae48f55596" not in sdk_tree:
  raise RuntimeError("Backend SDK submodule pin differs from the audited revision")
 if (sdk/".git").exists():
  if git(sdk,"rev-parse","HEAD")!="3cffbc82429b6165ceec2714f0f0d9ae48f55596":
   raise RuntimeError("Initialized SDK checkout differs from the audited revision")
  if git(sdk,"status","--porcelain"): raise RuntimeError("SDK source not clean")
 elif not a.source_only:
  raise RuntimeError("Full-source verification requires the pinned SDK checkout")
 bdiff=tracked(a.backend)
 if bdiff!=EDITED_BACKEND: raise RuntimeError(f"Wrong backend edited paths: {bdiff ^ EDITED_BACKEND}")
 buntracked=untracked(a.backend)
 expected_added=ADDED_BACKEND-({"src/mods/vr/DuoViewShaderSource.hpp"} if a.source_only else set())
 if buntracked!=expected_added: raise RuntimeError(f"Unexpected added backend paths: {buntracked ^ expected_added}")
 fdiff=tracked(a.frontend)
 if fdiff - (EDITED_FRONTEND|GENERATED_FRONTEND) or not EDITED_FRONTEND.issubset(fdiff):
  raise RuntimeError(f"Unexpected frontend tracked changes: {fdiff}")
 if untracked(a.frontend): raise RuntimeError("Unexpected untracked frontend source")
 geometry=(a.backend/"src/mods/vr/DuoViewGeometry.hpp").read_text(encoding="utf-8")
 if '.fovea = {0, 0, fw, fh}' not in geometry or '.periphery = {fw, 0, pw, ph}' not in geometry:
  raise RuntimeError("Legacy atlas order must be preserved in applied source")
 # A shipping DuoView must never compile shaders on the OpenXR copy path.
 compositor=(a.backend/"src/mods/vr/DuoViewD3D12.hpp").read_text(encoding="utf-8")
 if "D3DCompile(" in compositor or "shader_source" in compositor:
  raise RuntimeError("Runtime shader compiler still in production compositor")
 if "DuoViewState.hpp" not in (a.backend/"src/mods/VR.hpp").read_text(encoding="utf-8"):
  raise RuntimeError("Production VR headers missing DuoView frame state")
 vr_cpp=(a.backend/"src/mods/VR.cpp").read_text(encoding="utf-8")
 vr_header=(a.backend/"src/mods/VR.hpp").read_text(encoding="utf-8")
 # VRRuntime::error is std::optional<std::string>, NOT std::string.
 # This regression passed old CMake contracts but failed full MSVC backend.
 if vr_cpp.count("runtime && runtime->error.has_value()") != 2 or "runtime->error.empty()" in vr_cpp:
  raise RuntimeError("DuoView bootstrap guards must check optional runtime error engagement")
 if (".eye_tracked=false" not in vr_cpp or
     ".fixed_center_v=m_duo_center_v->value()" not in vr_cpp or
     "m_duo_gaze->draw(" in vr_cpp):
  raise RuntimeError("Fixed-center production control must not expose eye tracking")
 for token in ('m_duo_center_v->draw(', 'm_duo_width->draw(', 'm_duo_height->draw(', 'm_duo_periphery->draw(',
               'm_duo_density->draw(', 'm_duo_feather->draw(', 'm_duo_debug_source->draw('):
  if token not in vr_cpp: raise RuntimeError("DuoView quality UI missing "+token)
 for token in ('"DuoViewCropWidth"', '"DuoViewCropHeight"', '"DuoViewPeripheralScale"',
               '"DuoViewFovealDensity"', '"DuoViewFixedCenterVertical"',
               '"DuoViewFoveaSourceView"', '"DuoViewCropSmoothingMs"'):
  if token not in vr_header: raise RuntimeError("Persisted DuoView setting missing "+token)
 hook=(a.backend/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
 if "frame->config.settings.fovea_view" not in hook or "duo_frame->config.settings.fovea_view" not in hook:
  raise RuntimeError("Actual source index and UE projection must follow frozen source-view selection")
 if ("apply_frame_projection(double_matrix,*frame" not in hook or
     "can_native_fix_secondary_source(key,state)" not in hook or
     "duo_original_count=views->count" not in hook or
     "utility::ScopeGuard restore_duoview_family" not in hook or
     "if (result && duo_scene_observation)" not in hook):
  raise RuntimeError("DuoView source-parity constructor transaction or original-family restoration contract absent")
 # An incomplete DuoView atlas must never be presented as a full mono scene.
 # Persistent failure must request genuine mode5 on the game thread, never ID0.
 backend_copy=(a.backend/"src/mods/vr/D3D12Component.cpp").read_text(encoding="utf-8")
 if "duoview_quarantined" in vr_header or "duoview_quarantined" in vr_cpp:
  raise RuntimeError("Prohibited DuoView-to-Mono quarantine detected")
 if "m_openxr.duoview_compositors" not in backend_copy or "duoview_abort" not in backend_copy:
  raise RuntimeError("OpenXR DuoView fault handling missing")
 if ("DuoView OpenVR compositor" not in backend_copy or
     "OpenVR paired-source composition unavailable" not in backend_copy or
     "duo_left_submit_ok=(e==vr::VRCompositorError_None)" not in backend_copy or
     "if (duo_left_submit_ok) vr->duoview_frame_success()" not in backend_copy or
     "OpenVR right-eye Submit failed" not in backend_copy):
  raise RuntimeError("OpenVR must only call DuoView frame-success after BOTH eye submissions")
 state_source=(a.backend/"src/mods/vr/DuoViewState.hpp").read_text(encoding="utf-8")
 if ("can_native_fix_secondary_source" not in state_source or
     "slot->scene_states[0] == slot->scene_states[1]" not in state_source or
     "!slot->shading_applied" not in state_source):
  raise RuntimeError("DuoView must not present aliased or untreated secondary UE sources")
 if ("m_duoview_ever_presented" not in vr_header or
     "should_fallback_to_mono(failures,ever_presented)" not in vr_cpp or
     "OpenXR frame/projection gate not ready" not in backend_copy or
     "m_duoview_consecutive_failures" not in vr_cpp or
     "m_duoview_last_failure_tick.compare_exchange_weak(" not in vr_cpp or
     "m_duoview_game_tick_serial.fetch_add(" not in vr_cpp or
     "is_distinct_failed_tick(" not in vr_cpp or
     "m_duoview_fallback_requested.exchange(false" not in vr_cpp or
     "m_rendering_method->request(RenderingMethod::MONO)" not in vr_cpp or
     "m_rendering_method->request(RenderingMethod::NATIVE_STEREO)" in vr_cpp):
  raise RuntimeError("DuoView failure must request genuine Joey Mono ID5 only from game thread")
 if "m_openvr.copy_left_to_right(backbuffer.Get(),scene_source_state)" not in backend_copy:
  raise RuntimeError("OpenVR Joey Mono must duplicate complete first scene half to second eye")
 if 'duoview_abort("D3D12 setup/device/swapchain preparation failed")' not in backend_copy:
  raise RuntimeError("DX12 prewarm/RT setup errors must trigger DuoView-to-Mono policy")
 if "owner->is_using_mono()" not in (a.backend/"src/mods/vr/runtimes/OpenVR.cpp").read_text(encoding="utf-8"):
  raise RuntimeError("OpenVR Mono ID5 missing shared binocular optical calibration")
 if (".openxr = runtime != nullptr && (runtime->is_openxr() || (runtime->is_openvr() &&" not in vr_cpp or
     "g_framework->is_dx12() && duoview_stalker2_title" not in vr_cpp):
  raise RuntimeError("SteamVR Mono fallback must be allowed ONLY for STALKER2 DX12")
 if ("m_duo_center_v->value()" not in vr_cpp or
     "m_duoview_autostart_done" not in vr_header or
     "selection.requested()!=RenderingMethod::DUOVIEW_MONO" not in vr_cpp or
     "m_rendering_method->request(RenderingMethod::DUOVIEW_MONO)" not in vr_cpp):
  raise RuntimeError("DuoView must auto-start after a saved Mono fallback and preserve fixed-center control")
 framework_cpp=(a.backend/"src/Framework.cpp").read_text(encoding="utf-8")
 framework_header=(a.backend/"src/Framework.hpp").read_text(encoding="utf-8")
 bootstrap=(a.backend/"src/mods/vr/DuoViewBootstrap.hpp").read_text(encoding="utf-8")
 if ("is_mods_fully_initialized() const" not in framework_header or
     "if (m_vr) m_vr->on_duoview_startup_config_finalized();" not in framework_cpp or
     "m_duoview_autostart_config_token.store(" not in vr_cpp or
     "m_duoview_config_load_count" in vr_header or
     "bootstrap_draw_decision(" not in bootstrap):
  raise RuntimeError("Bootstrap readiness must use the explicit completed-config boundary, not a callback count")
 if ("bool VR::defer_duoview_bootstrap_draw()" not in vr_cpp or
     "m_d3d12.mono_consumers_retired()" not in vr_cpp or
     "selection.consumers_retired(token)" not in vr_cpp or
     "service_mono_transition_game_thread();" not in vr_cpp or
     "request_duoview_autostart_if_ready();" not in vr_cpp):
  raise RuntimeError("Startup must acknowledge actual retirement at the pre-scene Draw boundary and use the existing commit transaction")
 viewport_draw=source_block(hook,"void FFakeStereoRenderingHook::game_viewport_client_draw_hook(")
 main_draw_gate=viewport_draw.find("vr->defer_duoview_bootstrap_draw()) return;")
 main_draw_orig=viewport_draw.find("call_orig();", viewport_draw.find("if (!vr->is_hmd_active())"))
 early_draw_gate=viewport_draw.find("startup_vr->defer_duoview_bootstrap_draw()")
 early_draw_orig=viewport_draw.find("call_orig();", viewport_draw.find("if (!g_framework->is_game_data_intialized())"))
 if (main_draw_gate < 0 or main_draw_orig <= main_draw_gate or
     early_draw_gate < 0 or early_draw_orig <= early_draw_gate):
  raise RuntimeError("Startup Draw must be deferred before UE constructs the next scene")
 bootstrap_contracts=(Path(__file__).with_name("ProductionContractTests.cpp")).read_text(encoding="utf-8")
 if ("Unknown backend must defer the target startup Draw" not in bootstrap_contracts or
     "Saved fallback ID5 prevented the next eligible launch from requesting ID6" not in bootstrap_contracts or
     "Ready-but-unsupported automatic ID6 must keep Native ID0 scene Draw gated" not in bootstrap_contracts or
     "actual GPU-consumer retirement" not in bootstrap_contracts):
  raise RuntimeError("Bootstrap readiness, persisted-ID5 autostart, and retirement contracts are missing")
 openvr=(a.backend/"src/mods/vr/runtimes/OpenVR.cpp").read_text(encoding="utf-8")
 if ("uevr::mono::geometry(optical)" not in openvr or
     "owner->is_using_mono()" not in openvr or
     "this->view_bounds[eye][edge]=common->bounds[eye][edge]" not in openvr):
  raise RuntimeError("OpenVR shared Mono optical calibration or per-eye submission bounds missing")
 if ".fovea_view=static_cast<uint32_t>(m_duo_fovea_view->value())" not in vr_cpp:
  raise RuntimeError("UE source selector must be connected to immutable frame settings")
 shader_path=a.backend/"src/mods/vr/DuoViewShaderSource.hpp"
 if a.source_only:
  if shader_path.exists(): raise RuntimeError("Source-only transform unexpectedly generated a shader header")
 else:
  shaders=shader_path.read_text(encoding="utf-8")
  if "vertex_shader_bytecode[]" not in shaders or "pixel_shader_bytecode[]" not in shaders:
   raise RuntimeError("Precompiled DXBC shader arrays missing")
 inputs = sorted(EDITED_BACKEND | expected_added)
 hashes = {"backend":{k:sha(a.backend/k) for k in inputs},
           "frontend":{k:sha(a.frontend/k) for k in sorted(EDITED_FRONTEND)},
           "verification":{"source_only":bool(a.source_only),
                           "full_sdk_checkout_verified":bool((sdk/".git").exists()),
                           "shader_generated":not bool(a.source_only),
                           "compiled":False}}
 lock=a.evidence/"duoview-stage234-hashes.json"
 if a.final:
  if json.loads(lock.read_text())!=hashes: raise RuntimeError("Stage 2-4 source mutated during compile")
 else:
  lock.write_text(json.dumps(hashes,indent=2)+"\n")
 if a.source_only:
  print("Stage 2-4 source hashes verified; SDK gitlink verified; full SDK checkout/shader/build not verified.")
 else:
  print("Stage 2-4 exact source, proprietary SDK isolation and source hashes verified; this verifier does not certify compilation.")

if __name__=="__main__":
 main()
