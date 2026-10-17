#!/usr/bin/env python3
"""Install and verify a reversible, read-only STALKER 2 view/Draw probe.

This patch is applied only after the exact pinned Joey + DuoView Stage1/Stage234
transformers. It records existing FSceneView constructor inputs and Draw
lifetimes. It creates no views, targets, histories, draws, or XR submissions.
"""
import hashlib
import json
import sys
from pathlib import Path

DRAW = "void FFakeStereoRenderingHook::game_viewport_client_draw_hook(sdk::UGameViewportClient* viewport_client, sdk::FViewport* viewport, sdk::FCanvas* canvas, void* a4) {"
CTOR = "    auto result = g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);"

SCOPE = r"""
namespace {
std::atomic<uint64_t> g_quad_p0_draw_serial{0};
std::atomic<uint64_t> g_quad_p0_view_serial{0};
thread_local uint64_t g_quad_p0_active_draw{0};

bool quad_p0_probe_enabled() {
    static const bool enabled = [] {
        wchar_t value[2]{};
        return ::GetEnvironmentVariableW(L"UEVR_QUAD_P0_PROBE", value, 2) == 1 &&
            value[0] == L'1';
    }();
    return enabled;
}

// Read-only, nested-Draw safe. The serial is scoped to the original Draw call.
struct QuadP0DrawScope {
    uint64_t old_draw{g_quad_p0_active_draw};
    uint64_t serial{};
    QuadP0DrawScope() {
        if (!quad_p0_probe_enabled() || !stalker2_is_current_game() ||
            g_framework == nullptr || !g_framework->is_dx12()) return;
        serial = g_quad_p0_draw_serial.fetch_add(1, std::memory_order_relaxed) + 1;
        g_quad_p0_active_draw = serial;
        if (serial <= 512 || (serial % 60) == 0)
            SPDLOG_INFO("[QuadP0] draw=begin serial={} engine_frame={} thread={} nested={}",
                serial, g_frame_count, ::GetCurrentThreadId(), old_draw != 0);
    }
    ~QuadP0DrawScope() {
        if (serial && (serial <= 512 || (serial % 60) == 0))
            SPDLOG_INFO("[QuadP0] draw=end serial={} engine_frame={} thread={}",
                serial, g_frame_count, ::GetCurrentThreadId());
        g_quad_p0_active_draw = old_draw;
    }
};
} // read-only QuadView clean-restart probe

"""

DRAW_SCOPE = DRAW + "\n    QuadP0DrawScope quad_p0_draw_scope{};"
POST_CTOR = r"""
    // Generic constructor observation: log only existing engine-owned objects.
    if (result != nullptr && g_quad_p0_active_draw != 0 &&
        quad_p0_probe_enabled() && stalker2_is_current_game() &&
        g_framework != nullptr && g_framework->is_dx12() &&
        g_hook != nullptr && g_hook->is_in_viewport_client_draw()) {
        const auto sequence = g_quad_p0_view_serial.fetch_add(1, std::memory_order_relaxed) + 1;
        if (sequence <= 2048 || (sequence % 128) == 0) {
            const auto family = init_options_view_family;
            const auto views = family ? family->get_views() : nullptr;
            const auto target = family ? family->get_render_target() : nullptr;
            const int32_t family_count = views ? views->count : -1;
            SPDLOG_INFO(
                "[QuadP0] view seq={} draw={} engine_frame={} object={:x} family={:x} target={:x} viewstate={:x} original_pass={} effective_pass={} family_views={} thread={}",
                sequence, g_quad_p0_active_draw, g_frame_count,
                reinterpret_cast<uintptr_t>(result),
                reinterpret_cast<uintptr_t>(family),
                reinterpret_cast<uintptr_t>(target),
                reinterpret_cast<uintptr_t>(init_options_scene_state),
                static_cast<uint32_t>(init_options_original_stereo_pass),
                static_cast<uint32_t>(get_effective_stereo_pass()),
                family_count, ::GetCurrentThreadId());
        }
    }
"""

def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one exact source anchor, found {count}: {old[:120]!r}")
    return text.replace(old, new, 1)

def source_bytes(path: Path) -> tuple[str, str, bytes]:
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    normalized = raw.decode("utf-8").replace("\r\n", "\n")
    if normalized.replace("\n", newline).encode("utf-8") != raw:
        raise RuntimeError("Mixed line endings would violate narrow source-diff contract")
    return normalized, newline, raw

def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()

def verify(backend: Path, frontend: Path, evidence: Path) -> None:
    path = backend / "src/mods/vr/FFakeStereoRenderingHook.cpp"
    modified, newline, actual = source_bytes(path)
    manifest = json.loads((evidence / "quad-p0-probe.json").read_text(encoding="utf-8"))
    locks = json.loads((evidence / "duoview-stage234-hashes.json").read_text(encoding="utf-8"))
    relative = "src/mods/vr/FFakeStereoRenderingHook.cpp"
    if digest(actual) != manifest["after_sha256"]:
        raise RuntimeError("Probe source changed after exact installation")
    restored = replace_once(modified, CTOR + POST_CTOR, CTOR)
    restored = replace_once(restored, SCOPE + DRAW_SCOPE, DRAW)
    original = restored.replace("\n", newline).encode("utf-8")
    if digest(original) != manifest["before_sha256"] or digest(original) != locks["backend"][relative]:
        raise RuntimeError("Probe did not restore the exact Stage234 source byte-for-byte")
    for name, expected in locks["backend"].items():
        if name == relative:
            continue
        if digest((backend / name).read_bytes()) != expected:
            raise RuntimeError(f"Unexpected backend source mutation: {name}")
    for name, expected in locks["frontend"].items():
        if digest((frontend / name).read_bytes()) != expected:
            raise RuntimeError(f"Unexpected frontend source mutation: {name}")
    print("Generic read-only QuadView probe is reversible; all other pinned source hashes match")

def main() -> int:
    if len(sys.argv) not in (3, 5) or (len(sys.argv) == 5 and sys.argv[4] != "--verify"):
        print("apply: <backend> <evidence>; verify: <backend> <evidence> <frontend> --verify")
        return 2
    backend = Path(sys.argv[1]).resolve()
    evidence = Path(sys.argv[2]).resolve()
    path = backend / "src/mods/vr/FFakeStereoRenderingHook.cpp"
    if len(sys.argv) == 5:
        verify(backend, Path(sys.argv[3]).resolve(), evidence)
        return 0
    source, newline, raw = source_bytes(path)
    if "duoview_state().scene(key,index,state,applied);" not in source:
        raise RuntimeError("Expected pinned v22 Stage234 source is absent; refusing an unknown base")
    if "g_quad_p0_active_draw" in source:
        raise RuntimeError("Probe already installed; refusing duplicate instrumentation")
    before = digest(raw)
    source = replace_once(source, DRAW, SCOPE + DRAW_SCOPE)
    source = replace_once(source, CTOR, CTOR + POST_CTOR)
    new_bytes = source.replace("\n", newline).encode("utf-8")
    after = digest(new_bytes)
    path.write_bytes(new_bytes)
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "quad-p0-probe.json").write_text(json.dumps({
        "target": "joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6",
        "base": "v22 Build 29 / bd8024c9e83debaaee6890d36c756f186e8421e1",
        "path": "src/mods/vr/FFakeStereoRenderingHook.cpp",
        "before_sha256": before,
        "after_sha256": after,
        "line_ending": "CRLF" if newline == "\r\n" else "LF",
        "mode": "opt-in read-only; UEVR_QUAD_P0_PROBE=1",
        "four_history_allocation": False,
        "quadview_renderer_active": False,
        "extra_draw": False
    }, indent=2) + "\n", encoding="utf-8")
    print("Installed generic read-only Draw/FSceneView probe; no rendering paths changed")
    return 0

if __name__ == "__main__":
    sys.exit(main())
