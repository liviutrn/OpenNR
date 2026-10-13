#!/usr/bin/env python3
"""Apply guarded Stage-1 DuoView Mono fallback edits to exact Joey pins.

Run ONLY after verify_exact_baseline.py on pristine backend/SDK/frontend.
This makes ID 6 a distinct selectable method, but intentionally routes it
through Joey's original single-view Mono renderer. No two-view or gaze code.
"""
from pathlib import Path
import argparse
import json

BACKEND = {
 "src/mods/vr/MonoRenderingPolicy.hpp": [
  ('inline constexpr int32_t method_id = 5;\n', 
   'inline constexpr int32_t method_id = 5;\ninline constexpr int32_t duoview_method_id = 6;\nconstexpr bool is_mono_family(int32_t id) { return id == method_id || id == duoview_method_id; }\n'),
  ('    Choice{method_id, "Mono (Experimental)"},\n', 
   '    Choice{method_id, "Mono (Experimental)"},\n    Choice{duoview_method_id, "DuoView Mono (Stage 1 - safe Mono fallback)"},\n'),
  ('inline constexpr std::array non_dibr_choices {choices[0], choices[1], choices[2], choices[5]};',
   'inline constexpr std::array non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6]};'),
  ('// Requests from config, Lua/API and ImGui all use this transaction. Only Mono\n// transitions are deferred; existing mode-to-mode selection remains unchanged.',
   '// Requests from config, Lua/API and ImGui all use this transaction. Mono-family\n// transitions are deferred; existing mode-to-mode selection remains unchanged.'),
  ('m_active = pack(value == method_id ? 0 : value, 0);',
   'm_active = pack(is_mono_family(value) ? 0 : value, 0);'),
  ('if (active() != method_id && value != method_id) {',
   'if (!is_mono_family(active()) && !is_mono_family(value)) {'),
  ('return method == method_id || generation != ready_generation;',
   'return is_mono_family(method) || generation != ready_generation;'),
 ],
 "src/mods/VR.hpp": [
  ('        MONO = uevr::mono::method_id,\n',
   '        MONO = uevr::mono::method_id,\n        DUOVIEW_MONO = uevr::mono::duoview_method_id,\n'),
  ('bool is_using_mono() const { return m_rendering_method->value() == RenderingMethod::MONO; }',
   'bool is_using_mono() const { return uevr::mono::is_mono_family(m_rendering_method->value()); }\n    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }'),
  ('(requested_rendering_method() != RenderingMethod::MONO || mono_unavailable_reason() == nullptr);',
   '(!uevr::mono::is_mono_family(requested_rendering_method()) || mono_unavailable_reason() == nullptr);'),
 ],
 "src/mods/VR.cpp": [
  ('const bool entering = selection.requested() == RenderingMethod::MONO;',
   'const bool entering = uevr::mono::is_mono_family(selection.requested());'),
  ('if (selection.requested() == RenderingMethod::MONO && mono_unavailable_reason() != nullptr) { return; }',
   'if (uevr::mono::is_mono_family(selection.requested()) && mono_unavailable_reason() != nullptr) { return; }'),
  ('if (is_using_mono() || requested_rendering_method() == RenderingMethod::MONO || is_mono_transition_pending()) {',
   'if (is_using_mono() || uevr::mono::is_mono_family(requested_rendering_method()) || is_mono_transition_pending()) {'),
  ('            ImGui::TextWrapped("Mono: %s", mono_status());',
   '            if (is_using_duoview_mono() || requested_rendering_method() == RenderingMethod::DUOVIEW_MONO) {\n                ImGui::TextWrapped("DuoView Stage 1: rendering uses original Joey Mono unchanged. Two-view foveation and gaze are NOT active.");\n            }\n            ImGui::TextWrapped("Mono: %s", mono_status());'),
 ],
 "src/mods/vr/CompatibilityPolicy.hpp": [
  ('    Mono = 5,\n', '    Mono = 5,\n    DuoViewMono = 6,\n'),
  ('if (method == RenderingMethod::Mono) { return false; }',
   'if (method == RenderingMethod::Mono || method == RenderingMethod::DuoViewMono) { return false; }'),
 ],
 "tests/MonoRenderingTests.hpp": [
  ('    for (int id = 0; id != 6; ++id) {',
   '    for (int id = 0; id != 7; ++id) {'),
  ('expect(m::available(id, m::non_dibr_choices) == (id < 3 || id == 5),',
   'expect(m::available(id, m::non_dibr_choices) == (id < 3 || id == 5 || id == 6),'),
  ('    expect(!m::available(-1) && !m::available(6), "unsupported IDs are identified, never clamped into Mono");',
   '    expect(!m::available(-1) && !m::available(7), "unsupported IDs are identified, never clamped into Mono");\n'
   '    expect(m::is_mono_family(5) && m::is_mono_family(6) && !m::is_mono_family(0),\n'
   '        "original Mono and DuoView fallback share the safe Mono lifecycle, other modes do not");\n'
   '    expect(!p::is_using_afr(p::RenderingMethod::DuoViewMono, true),\n'
   '        "DuoView fallback cannot accidentally activate AFR even if an old profile requests it");\n'
   '    {\n'
   '        m::Selection duo;\n'
   '        duo.initialize(6);\n'
   '        expect(duo.active() == 0 && duo.pending(), "DuoView startup defers rendering until GPU consumers retire");\n'
   '        expect(!duo.commit_at_game_frame_boundary(), "DuoView cannot activate before retirement");\n'
   '        duo.consumers_retired(duo.request_token());\n'
   '        expect(duo.commit_at_game_frame_boundary() && duo.active() == 6 && duo.generation() == 1,\n'
   '            "DuoView startup commits at main game-frame boundary");\n'
   '        duo.request(5);\n'
   '        expect(duo.active() == 6 && duo.pending(), "DuoView to Mono requires retirement");\n'
   '        duo.consumers_retired(duo.request_token());\n'
   '        expect(duo.commit_at_game_frame_boundary() && duo.active() == 5,\n'
   '            "DuoView to original Mono switches without stale frame generation");\n'
   '        duo.request(0);\n'
   '        expect(duo.active() == 5 && duo.pending(), "Mono to Native requires retirement");\n'
   '        duo.consumers_retired(duo.request_token());\n'
   '        expect(duo.commit_at_game_frame_boundary() && duo.active() == 0,\n'
   '            "after DuoView fallback the original native route remains selectable");\n'
   '    }\n'),
 ],
}
FRONTEND = {
 "UEVR/RenderingModeOptions.cs": [
  ('        public const int Mono = 5;',
   '        public const int Mono = 5;\n        public const int DuoViewMono = 6;'),
  ('            result.Add(Mono.ToString(), "Mono (Experimental)");',
   '            result.Add(Mono.ToString(), "Mono (Experimental)");\n            result.Add(DuoViewMono.ToString(), "DuoView Mono (Stage 1 - safe Mono fallback)");'),
 ],
 "tests/RenderingModes/Program.cs": [
  ('for (int id = 0; id <= 5; ++id) {', 'for (int id = 0; id <= 6; ++id) {'),
  ('bool supported = id < 3 || id == 5 || dibr;',
   'bool supported = id < 3 || id == 5 || id == 6 || dibr;'),
  ('"4", "5", "99", "-1"', '"4", "5", "6", "99", "-1"'),
  ('    if (choices.ContainsKey("99")) {',
   '    if (choices["6"] != "DuoView Mono (Stage 1 - safe Mono fallback)") {\n'
   '        throw new Exception("DuoView stage 1 must be explicitly identified as original Mono fallback");\n'
   '    }\n'
   '    if (choices.ContainsKey("99")) {'),
 ],
}

def apply(root, file_map):
    audit = []
    for rel, edits in file_map.items():
        p = root / rel
        text = p.read_text(encoding="utf-8-sig")
        original = text
        for before, after in edits:
            count = text.count(before)
            if count != 1:
                raise RuntimeError(f"{rel}: expected one occurrence, found {count}: {before[:100]!r}")
            text = text.replace(before, after)
        if text == original:
            raise RuntimeError(f"No changes applied to {rel}")
        p.write_text(text, encoding="utf-8", newline="")
        audit.append({"path": rel, "replacements": len(edits)})
    return audit

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", type=Path)
    parser.add_argument("frontend", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    report = {"stage": 1, "duoview_id": 6, "two_view_enabled": False,
        "mono_renderer_fallback": True, "backend": apply(args.backend, BACKEND),
        "frontend": apply(args.frontend, FRONTEND)}
    (args.evidence / "duoview-stage1-edits.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("DuoView Stage 1 exact-source guarded edits applied (Mono fallback, no dual-view rendering).")
