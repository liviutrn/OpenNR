#!/usr/bin/env python3
"""Strict, opt-in, read-only STALKER2 view-state discovery for pinned Joey UEVR.
Run AFTER the isolated Stage1+Stage234 source transformer. Does not create an
additional Draw, allocate a ViewState, change projections, or submit to XR.
"""
import hashlib
import json
import sys
from pathlib import Path

DRAW = """void FFakeStereoRenderingHook::game_viewport_client_draw_hook(sdk::UGameViewportClient* viewport_client, sdk::FViewport* viewport, sdk::FCanvas* canvas, void* a4) {"""
CONSTRUCTOR = """    if (result && duo_scene_observation) {
        const auto& observation=*duo_scene_observation;
        vr->duoview_state().scene(observation.key,observation.index,observation.state,observation.shading);
    }"""
SCOPE = r"""
namespace {
std::atomic<uint64_t> g_quad_p1_draw_serial{0};
std::atomic<uint64_t> g_quad_p1_view_serial{0};
thread_local uint64_t g_quad_p1_active_draw{0};
bool quad_p1_probe_enabled() {
    static const bool enabled = [] {
        wchar_t value[2]{};
        return ::GetEnvironmentVariableW(L"UEVR_QUAD_P1_PROBE", value, 2) == 1 &&
            value[0] == L'1';
    }();
    return enabled;
}
// Read-only; nest/reentrancy safe. Lifetime is the exact game-thread Draw.
struct QuadP1DrawScope {
    uint64_t old_draw{g_quad_p1_active_draw};
    uint64_t serial{};
    QuadP1DrawScope() {
        if (!quad_p1_probe_enabled() || !stalker2_is_current_game() ||
            g_framework == nullptr || !g_framework->is_dx12()) return;
        serial = g_quad_p1_draw_serial.fetch_add(1, std::memory_order_relaxed) + 1;
        g_quad_p1_active_draw = serial;
        if (serial <= 512 || (serial % 60) == 0)
            SPDLOG_INFO("[QuadP1] draw=begin serial={} engine_frame={} thread={} nested={}",
                serial, g_frame_count, ::GetCurrentThreadId(), old_draw != 0);
    }
    ~QuadP1DrawScope() {
        if (serial && (serial <= 512 || (serial % 60) == 0))
            SPDLOG_INFO("[QuadP1] draw=end serial={} engine_frame={} thread={}",
                serial, g_frame_count, ::GetCurrentThreadId());
        g_quad_p1_active_draw = old_draw;
    }
};
} // read-only QuadView probe

"""
POST_VIEW = r"""
    // Independent evidence of the original engine-created FSceneView and its
    // current, *borrowed* state. Never mutate or retain UE ownership pointers.
    if (result && init_options && g_quad_p1_active_draw != 0 &&
        quad_p1_probe_enabled() && stalker2_is_current_game() &&
        g_framework != nullptr && g_framework->is_dx12()) {
        const auto sequence = g_quad_p1_view_serial.fetch_add(1, std::memory_order_relaxed) + 1;
        if (sequence <= 1024 || (sequence % 128) == 0)
            SPDLOG_INFO(
                "[QuadP1] constructor seq={} draw={} engine_frame={} view={:x} family={:x} viewstate={:x} original_pass={} thread={}",
                sequence, g_quad_p1_active_draw, g_frame_count,
                reinterpret_cast<uintptr_t>(result),
                reinterpret_cast<uintptr_t>(init_options_view_family),
                reinterpret_cast<uintptr_t>(init_options_scene_state),
                static_cast<uint32_t>(init_options_original_stereo_pass),
                ::GetCurrentThreadId());
    }
"""
def replace_once(haystack: str, old: str, new: str) -> str:
    count=haystack.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one exact source anchor, found {count}: {old[:100]!r}")
    return haystack.replace(old, new, 1)

def main() -> int:
    if len(sys.argv) != 3:
        print("usage: apply_read_only_probe.py <transformed_joey_backend> <evidence_directory>")
        return 2
    base=Path(sys.argv[1]).resolve()
    evidence=Path(sys.argv[2]).resolve()
    path=base/"src/mods/vr/FFakeStereoRenderingHook.cpp"
    source=path.read_text(encoding="utf-8")
    if "duo_scene_observation" not in source:
        raise RuntimeError("DuoView stage234 source identity absent; refusing unexpected source")
    if "g_quad_p1_active_draw" in source:
        raise RuntimeError("Probe is already installed; refusing duplicate instrumentation")
    before=hashlib.sha256(source.encode()).hexdigest()
    source=replace_once(source,DRAW,SCOPE+DRAW+"\n    QuadP1DrawScope quad_p1_draw_scope{};")
    source=replace_once(source,CONSTRUCTOR,CONSTRUCTOR+POST_VIEW)
    after=hashlib.sha256(source.encode()).hexdigest()
    path.write_text(source,encoding="utf-8",newline="\n")
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/"quad-p1-probe.json").write_text(
        json.dumps({
            "target":"joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6",
            "path":"src/mods/vr/FFakeStereoRenderingHook.cpp",
            "before_sha256":before,
            "after_sha256":after,
            "mode":"opt-in read-only; UEVR_QUAD_P1_PROBE=1",
            "four_history_allocation":False,
            "quadview_renderer_active":False,
            "extra_draw":False
        },indent=2)+"\n",encoding="utf-8")
    print("Installed opt-in source-only QuadView view-state probe; no rendering paths changed")
    return 0
if __name__ == "__main__":
    sys.exit(main())
