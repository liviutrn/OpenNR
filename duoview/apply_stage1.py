#!/usr/bin/env python3
"""Apply the isolated DuoView Stage-1 two-view diagnostic to pinned Joey UEVR.

No source patch is applied unless every expected upstream anchor matches once.
Stage 1 intentionally uses two full-resolution identical-perspective UE views.
Stage 2 (unequal shader-resolution views) and composition are NOT implemented.
"""
import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, file: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{file}: expected one anchor, got {n}: {old[:110]!r}")
    return text.replace(old, new, 1)


def patch_file(root: Path, name: str, changes: list[tuple[str, str]]) -> None:
    path = root / name
    before = path.read_text(encoding="utf-8")
    after = before
    for old, new in changes:
        after = replace_once(after, old, new, name)
    path.write_text(after, encoding="utf-8", newline="\n")
    print(f"[DuoView] patched {name} ({len(changes)} anchors)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="UEVR source checkout")
    args = ap.parse_args()
    root = args.root.resolve()
    if not (root / "src/mods/VR.hpp").is_file():
        ap.error("root must point to the Joey UEVR source directory")

    # Fail closed before touching any file: this patch must only run against
    # the pinned upstream revision (also checked in the CI workflow).
    patch = {
        "src/mods/vr/MonoRenderingPolicy.hpp": [
            (
                "inline constexpr int32_t method_id = 5;",
                "inline constexpr int32_t method_id = 5;\n"
                "inline constexpr int32_t duoview_method_id = 6;\n"
                "constexpr bool is_mono_method(int32_t id) {\n"
                "    return id == method_id || id == duoview_method_id;\n"
                "}",
            ),
            (
                '    Choice{method_id, "Mono (Experimental)"},',
                '    Choice{method_id, "Mono (Experimental)"},\n'
                '    Choice{duoview_method_id, "DuoView Mono (Stage 1 Diagnostic)"},',
            ),
            (
                "inline constexpr std::array non_dibr_choices {choices[0], choices[1], choices[2], choices[5]};",
                "inline constexpr std::array non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6]};",
            ),
            (
                "m_active = pack(value == method_id ? 0 : value, 0);",
                "m_active = pack(is_mono_method(value) ? 0 : value, 0);",
            ),
            (
                "if (active() != method_id && value != method_id) {",
                "if (!is_mono_method(active()) && !is_mono_method(value)) {",
            ),
            (
                "return method == method_id || generation != ready_generation;",
                "return is_mono_method(method) || generation != ready_generation;",
            ),
        ],
        "src/mods/VR.hpp": [
            (
                "        MONO = uevr::mono::method_id,",
                "        MONO = uevr::mono::method_id,\n"
                "        DUOVIEW_MONO = uevr::mono::duoview_method_id,",
            ),
            (
                "    bool is_using_mono() const { return m_rendering_method->value() == RenderingMethod::MONO; }",
                "    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }\n"
                "    bool is_using_mono() const { return uevr::mono::is_mono_method(m_rendering_method->value()); }",
            ),
            (
                "(requested_rendering_method() != RenderingMethod::MONO || mono_unavailable_reason() == nullptr);",
                "(!uevr::mono::is_mono_method(requested_rendering_method()) || mono_unavailable_reason() == nullptr);",
            ),
        ],
        "src/mods/VR.cpp": [
            (
                "const bool entering = selection.requested() == RenderingMethod::MONO;",
                "const bool entering = uevr::mono::is_mono_method(selection.requested());",
            ),
            (
                "if (selection.requested() == RenderingMethod::MONO && mono_unavailable_reason() != nullptr) { return; }",
                "if (uevr::mono::is_mono_method(selection.requested()) && mono_unavailable_reason() != nullptr) { return; }",
            ),
        ],
        "src/mods/vr/FFakeStereoRenderingHook.cpp": [
            (
                "    if (VR::get()->is_using_mono()) {\n"
                "        *x = 0;\n"
                "        *y = 0;\n"
                "    } else if (!VR::get()->is_native_stereo_fix_enabled()) {",
                "    if (VR::get()->is_using_mono() && !VR::get()->is_using_duoview_mono()) {\n"
                "        *x = 0;\n"
                "        *y = 0;\n"
                "    } else if (!VR::get()->is_native_stereo_fix_enabled()) {",
            ),
            (
                "    if (vr->is_using_mono()) { return 1; }",
                "    if (vr->is_using_duoview_mono()) { return 2; }\n"
                "    if (vr->is_using_mono()) { return 1; }",
            ),
            (
                "            (!vr->is_using_mono() || views_ptr->count == 1));",
                "            (!vr->is_using_mono() ||\n"
                "             views_ptr->count == (vr->is_using_duoview_mono() ? 2 : 1)));",
            ),
        ],
        "tests/MonoRenderingTests.hpp": [
            (
                "for (int id = 0; id != 6; ++id) {",
                "for (int id = 0; id != 7; ++id) {",
            ),
            (
                "== (id < 3 || id == 5),",
                "== (id < 3 || id == 5 || id == 6),",
            ),
            (
                'expect(!m::available(-1) && !m::available(6), "unsupported IDs are identified, never clamped into Mono");',
                'expect(!m::available(-1) && !m::available(7), "unsupported IDs are identified, never clamped into Mono");',
            ),
            (
                'expect(!m::needs_frame_gate(0,0,0) && m::needs_frame_gate(5,1,1),',
                'expect(!m::needs_frame_gate(0,0,0) && m::needs_frame_gate(5,1,1) && m::needs_frame_gate(6,1,1),',
            ),
            (
                "    m::Selection s;\n    s.initialize(5);",
                "    m::Selection duo;\n"
                "    duo.initialize(6);\n"
                "    expect(duo.active() == 0 && duo.requested() == 6 && duo.pending(),\n"
                '        "DuoView startup uses the guarded Mono transition");\n'
                "    duo.consumers_retired(duo.request_token());\n"
                "    expect(duo.commit_at_game_frame_boundary() && duo.active() == 6,\n"
                '        "DuoView becomes active only after retirement and game-frame boundary");\n'
                "    duo.request(5);\n"
                "    expect(duo.active() == 6 && duo.pending(),\n"
                '        "DuoView-to-Mono transition must be retired, not applied immediately");\n'
                "    duo.consumers_retired(duo.request_token());\n"
                "    expect(duo.commit_at_game_frame_boundary() && duo.active() == 5,\n"
                '        "DuoView-to-Mono transition commits safely");\n'
                "    m::Selection s;\n    s.initialize(5);",
            ),
        ],
    }

    # Validate every anchor in memory first to avoid a half-patched checkout.
    new_files = {}
    for name, changes in patch.items():
        source = (root / name).read_text(encoding="utf-8")
        new = source
        for old, target in changes:
            new = replace_once(new, old, target, name)
        new_files[name] = new
    for name, output in new_files.items():
        (root / name).write_text(output, encoding="utf-8", newline="\n")
        print(f"[DuoView] applied {name}")
    print("[DuoView] Stage 1 patch complete (NOT yet a foveated renderer)")


if __name__ == "__main__":
    main()
