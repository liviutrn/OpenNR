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
DESIRED = """uint32_t FFakeStereoRenderingHook::get_desired_number_of_views_hook(FFakeStereoRendering* stereo, bool is_stereo_enabled) {"""
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
DESIRED_OBSERVATION = r"""
    if (quad_p1_probe_enabled() && stalker2_is_current_game() &&
        g_framework != nullptr && g_framework->is_dx12()) {
        static std::atomic<uint64_t> desired_serial{0};
        const auto count = desired_serial.fetch_add(1, std::memory_order_relaxed) + 1;
        if (count <= 256 || (count % 128) == 0)
            SPDLOG_INFO("[QuadP1] desired seq={} stereo={} post_init={} engine_frame={} draw={} thread={}",
                count, is_stereo_enabled,
                g_hook->m_sceneview_data.inside_post_init_properties, g_frame_count,
                g_quad_p1_active_draw, ::GetCurrentThreadId());
    }
"""
def replace_once(haystack: str, old: str, new: str) -> str:
    count=haystack.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one exact source anchor, found {count}: {old[:100]!r}")
    return haystack.replace(old, new, 1)

def source_bytes(path: Path) -> tuple[str,str,bytes]:
    raw=path.read_bytes()
    newline="\r\n" if b"\r\n" in raw else "\n"
    normalized=raw.decode("utf-8").replace("\r\n","\n")
    if normalized.replace("\n",newline).encode("utf-8")!=raw:
        raise RuntimeError("Mixed line endings would violate narrow source-diff contract")
    return normalized,newline,raw

def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()

def verify(base: Path, frontend: Path, evidence: Path) -> None:
    path=base/"src/mods/vr/FFakeStereoRenderingHook.cpp"
    modified,newline,actual=source_bytes(path)
    manifest=json.loads((evidence/"quad-p1-probe.json").read_text(encoding="utf-8"))
    locks=json.loads((evidence/"duoview-stage234-hashes.json").read_text(encoding="utf-8"))
    relative="src/mods/vr/FFakeStereoRenderingHook.cpp"
    if digest(actual)!=manifest["after_sha256"]:
        raise RuntimeError("QuadView probe source mutated after exact installation")
    restored=replace_once(modified,SCOPE+DRAW+"\n    QuadP1DrawScope quad_p1_draw_scope{};",DRAW)
    restored=replace_once(restored,CONSTRUCTOR+POST_VIEW,CONSTRUCTOR)
    restored=replace_once(restored,DESIRED+DESIRED_OBSERVATION,DESIRED)
    original=restored.replace("\n",newline).encode("utf-8")
    if digest(original)!=manifest["before_sha256"] or \
       digest(original)!=locks["backend"][relative]:
        raise RuntimeError("Unmodified Joey/DuoView source was not recovered byte-for-byte")
    # Preserve all OTHER transformed files and the matching frontend bitwise.
    for name,expected in locks["backend"].items():
        if name==relative: continue
        if digest((base/name).read_bytes())!=expected:
            raise RuntimeError(f"Unexpected backend source mutation: {name}")
    for name,expected in locks["frontend"].items():
        if digest((frontend/name).read_bytes())!=expected:
            raise RuntimeError(f"Unexpected frontend source mutation: {name}")
    print("Exact read-only QuadView probe reversible; backend/frontend source hashes unchanged")

def main() -> int:
    if len(sys.argv) not in (3,5) or (len(sys.argv)==5 and sys.argv[4]!="--verify"):
        print("apply: <backend> <evidence>; verify: <backend> <evidence> <frontend> --verify")
        return 2
    base=Path(sys.argv[1]).resolve()
    evidence=Path(sys.argv[2]).resolve()
    if len(sys.argv)==5:
        verify(base,Path(sys.argv[3]).resolve(),evidence)
        return 0
    path=base/"src/mods/vr/FFakeStereoRenderingHook.cpp"
    source,newline,raw=source_bytes(path)
    if "duo_scene_observation" not in source:
        raise RuntimeError("DuoView stage234 source identity absent; refusing unexpected source")
    if "g_quad_p1_active_draw" in source:
        raise RuntimeError("Probe already installed; refusing duplicate instrumentation")
    before=digest(raw)
    source=replace_once(source,DRAW,SCOPE+DRAW+"\n    QuadP1DrawScope quad_p1_draw_scope{};")
    source=replace_once(source,CONSTRUCTOR,CONSTRUCTOR+POST_VIEW)
    source=replace_once(source,DESIRED,DESIRED+DESIRED_OBSERVATION)
    new_bytes=source.replace("\n",newline).encode("utf-8")
    after=digest(new_bytes)
    path.write_bytes(new_bytes)
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/"quad-p1-probe.json").write_text(
        json.dumps({
            "target":"joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6",
            "path":"src/mods/vr/FFakeStereoRenderingHook.cpp",
            "before_sha256":before,
            "after_sha256":after,
            "line_ending":"CRLF" if newline=="\r\n" else "LF",
            "mode":"opt-in read-only; UEVR_QUAD_P1_PROBE=1",
            "four_history_allocation":False,
            "quadview_renderer_active":False,
            "extra_draw":False
        },indent=2)+"\n",encoding="utf-8")
    print("Installed opt-in read-only QuadView view-state probe; no rendering paths changed")
    return 0

if __name__ == "__main__":
    sys.exit(main())
