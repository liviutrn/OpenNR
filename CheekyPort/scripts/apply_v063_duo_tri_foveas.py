#!/usr/bin/env python3
"""Strict post-patch support for DuoView Mono + TriView, foveas only.

After the proven v0.6.3 NR Lite / independent / safety / Faithful HDR patches.
DuoView is admitted only with TWO live DX12 sources and positive NGX
subrectangle evidence consistent with DuoView's fovea-left atlas layout.
If NGX does not expose those coordinates, fail closed: never guess a source.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()

def patch(name, before, after, count=1):
    p = root / name
    s = p.read_text(encoding="utf-8")
    n = s.count(before)
    if n != count:
        raise RuntimeError(f"{name}: expected {count} exact anchor(s), found {n}: {before[:100]!r}")
    p.write_text(s.replace(before, after), encoding="utf-8", newline="\n")
    print("DUO-TRI:", name)

# Keep original source-view geometry and identity tracking. The extra NGX
# subrectangle metadata is collected at the existing NGX evaluation boundary;
# no UEVR or native DLSS SR integration is changed.
patch("src/settings.cpp",
      "    std::uint32_t evaluation_output_width{}, evaluation_output_height{};\n};",
      """    std::uint32_t evaluation_output_width{}, evaluation_output_height{};
    std::uint32_t ngx_output_base_x{}, ngx_output_base_y{};
    bool ngx_output_base_valid{};
};""")
patch("src/settings.hpp",
      "    std::uint32_t output_width, std::uint32_t output_height) noexcept;\n[[nodiscard]] bool has_multiple_stereo_views() noexcept;",
      """    std::uint32_t output_width, std::uint32_t output_height) noexcept;
void note_stereo_view_output_subrect(std::uint64_t view_id,
    bool valid, std::uint32_t base_x, std::uint32_t base_y) noexcept;
[[nodiscard]] bool has_multiple_stereo_views() noexcept;""")
patch("src/settings.cpp",
      "void note_stereo_view_geometry(\n",
      """void note_stereo_view_output_subrect(const std::uint64_t id,
    const bool valid, const std::uint32_t x, const std::uint32_t y) noexcept {
    std::lock_guard lock(stereo_views_mutex);
    for (auto& view : stereo_views) {
        if (view.view_id != id) continue;
        view.ngx_output_base_valid = valid;
        view.ngx_output_base_x = valid ? x : 0U;
        view.ngx_output_base_y = valid ? y : 0U;
        return;
    }
}

void note_stereo_view_geometry(
""")
patch("src/hooks.cpp",
      """    note_stereo_view_evaluation(reinterpret_cast<std::uintptr_t>(handle),
        api == DiagnosticApi::d3d11 ? 11U : 12U, input_width, input_height,
        get_ui(parameters, "OutWidth") ? get_ui(parameters, "OutWidth") : output.width,
        get_ui(parameters, "OutHeight") ? get_ui(parameters, "OutHeight") : output.height);""",
      """    const auto physical_id = static_cast<std::uint64_t>(
        reinterpret_cast<std::uintptr_t>(handle));
    note_stereo_view_evaluation(physical_id,
        api == DiagnosticApi::d3d11 ? 11U : 12U, input_width, input_height,
        get_ui(parameters, "OutWidth") ? get_ui(parameters, "OutWidth") : output.width,
        get_ui(parameters, "OutHeight") ? get_ui(parameters, "OutHeight") : output.height);
    std::uint32_t ngx_base_x{};
    const bool ngx_has_base = api == DiagnosticApi::d3d12 && parameters != nullptr &&
        ngx_succeeded(parameters->Get("DLSS.Output.Subrect.Base.X", &ngx_base_x));
    note_stereo_view_output_subrect(physical_id, ngx_has_base, ngx_base_x,
        ngx_has_base ? get_ui(parameters, "DLSS.Output.Subrect.Base.Y") : 0U);
    if (api == DiagnosticApi::d3d12) {
        static std::atomic<std::uint64_t> source_trace{};
        const auto count = source_trace.fetch_add(1U, std::memory_order_relaxed) + 1U;
        if (count <= 24U || count % 300U == 0U)
            trace_event("[CheekyNR][SourceRouting] source=%llu in=%ux%u out=%ux%u ngxBase=%s:%u,%u role=%u (1/2=fovea,4=bypass,0=unknown)",
                static_cast<unsigned long long>(physical_id), input_width, input_height,
                get_ui(parameters, "OutWidth"), get_ui(parameters, "OutHeight"),
                ngx_has_base ? "yes" : "no", ngx_base_x,
                ngx_has_base ? get_ui(parameters, "DLSS.Output.Subrect.Base.Y") : 0U,
                cheeky_nr_source_role(physical_id));
    }""")

# The full original TriView 3/4-source implementation is retained verbatim.
# Add only a TWO-source case. Require a verified positive output-base offset
# for the right-hand peripheral rectangle, 0,0 for the fovea, and distinct
# source dimensions. Two ordinary stereo eye sources have matched dimensions,
# so cannot be mistaken for DuoView. One atlas-sized NGX source is ambiguous.
p = root / "src/settings.cpp"
source = p.read_text(encoding="utf-8")
start = source.index("std::uint32_t cheeky_nr_source_role(const std::uint64_t id) noexcept {")
end = source.index("std::uint32_t cheeky_nr_selected_passes(", start)
old = source[start:end]
anchor = """    if (n != 3U && n != 4U) return 0U;
    const auto same = [](const StereoView* a, const StereoView* b) noexcept {"""
if old.count(anchor) != 1:
    raise RuntimeError("Expected unchanged 3/4-source TriView classifier")
new = old.replace(anchor, """    if (n == 2U) {
        const StereoView* fovea{};
        const StereoView* periphery{};
        // The authoritative *layout* comes from the NGX output subrects:
        // DuoView packs fovea at atlas x=0 and periphery immediately right.
        // Unlike guessing by resolution, reversing foveal density cannot
        // silently turn the periphery into the NR target.
        if (v[0]->ngx_output_base_valid && v[1]->ngx_output_base_valid &&
            v[0]->ngx_output_base_y == 0U && v[1]->ngx_output_base_y == 0U) {
            if (v[0]->ngx_output_base_x == 0U &&
                v[1]->ngx_output_base_x > 0U) {
                fovea = v[0]; periphery = v[1];
            } else if (v[1]->ngx_output_base_x == 0U &&
                       v[0]->ngx_output_base_x > 0U) {
                fovea = v[1]; periphery = v[0];
            }
        }
        if (!fovea || !periphery ||
            !fovea->evaluation_input_width || !fovea->evaluation_input_height ||
            !periphery->evaluation_input_width || !periphery->evaluation_input_height ||
            !fovea->evaluation_output_width || !fovea->evaluation_output_height ||
            !periphery->evaluation_output_width || !periphery->evaluation_output_height)
            return 0U;
        // Positive difference rules out the common two-equal-eye stereo case.
        // We DO NOT assume the foveal image is always the larger one.
        const bool different_input =
            fovea->evaluation_input_width != periphery->evaluation_input_width ||
            fovea->evaluation_input_height != periphery->evaluation_input_height;
        const bool different_output =
            fovea->evaluation_output_width != periphery->evaluation_output_width ||
            fovea->evaluation_output_height != periphery->evaluation_output_height;
        if (!different_input && !different_output) return 0U;
        return id == fovea->view_id ? 1U :
            id == periphery->view_id ? 4U : 0U;
    }
    if (n != 3U && n != 4U) return 0U;
    const auto same = [](const StereoView* a, const StereoView* b) noexcept {""")
# Need to permit TWO views in enumeration but keep >4 rejection unchanged.
new = new.replace("if (n != 3U && n != 4U) return 0U;", "if (n != 3U && n != 4U) return 0U;", 1)
assert new != old
p.write_text(source[:start] + new + source[end:], encoding="utf-8", newline="\n")
print("DUO-TRI: two-source positive subrect classifier, original TriView preserved")

# Enforce the new foveas-only user policy at the *actual NR selection* boundary
# even when an old template or saved UEVR config requests mask 4/5/6/7.
patch("src/settings.cpp",
      "const auto first = settings.nr_pass1_views & 7U;",
      "const auto first = settings.nr_pass1_views & 3U; // periphery is NEVER an NR target")
patch("src/settings.cpp",
      "        ? (settings.nr_pass2_views & 7U) : 0U;",
      "        ? (settings.nr_pass2_views & 3U) : 0U;")
patch("src/settings.cpp",
      "nr_pass1_views = settings.nr_pass1_views & 7U;",
      "nr_pass1_views = settings.nr_pass1_views & 3U;")
patch("src/settings.cpp",
      "nr_pass2_views = settings.nr_pass2_views & 7U;",
      "nr_pass2_views = settings.nr_pass2_views & 3U;")
patch("src/dlss_nr.cpp",
      "if ((mask & view.source_role) == 0U) view.retired = true;",
      "if (view.source_role == 4U || (mask & view.source_role) == 0U) view.retired = true;")
# Existing masks up to 7 in old saved profiles are accepted for migration, but
# applied values are immediately limited to foveal bits when settings commit.
patch("uevr/settings_io.cpp",
      "(key==\"NrPass1Views\" ? s.nr_pass1_views : s.nr_pass2_views)=mask;return true;",
      "(key==\"NrPass1Views\" ? s.nr_pass1_views : s.nr_pass2_views)=(mask & 3U);return true;")

# Remove periphery choices from the menu; retain independent pass1/pass2
# source selection, the 2 NR templates and every Faithful HDR control.
p = root / "uevr/scripts/cheeky_foveated_dlss.lua"
ui = p.read_text(encoding="utf-8")
a = ui.index('    text("Each model pass has independent source coverage.')
b = ui.index('    if draft.NrProcessingOrder ~= nil then', a)
part = ui[a:b]
old_labels = """    text("Each model pass has independent source coverage. A/B are stable source IDs, not verified left/right eyes.")
    local mask_labels = {[0]="None", [1]="Fovea A", [2]="Fovea B", [3]="Both foveas",
        [4]="Periphery only", [5]="Fovea A + periphery",
        [6]="Fovea B + periphery", [7]="All three views"}
    combo("Pass 1 source views", "NrPass1Views", mask_labels, {3,7,4,1,2,5,6,0})"""
new_labels = """    text("Auto source routing: TriView = both foveas; DuoView Mono = one fovea.")
    text("NR is NEVER sent to the peripheral DLSS source. Ambiguous DuoView subrects bypass NR.")
    local mask_labels = {[0]="None", [1]="Fovea A / Duo fovea", [2]="TriView fovea B", [3]="All foveas"}
    combo("Pass 1 source views", "NrPass1Views", mask_labels, {3,1,2,0})"""
if part.count(old_labels)!=1:
    raise RuntimeError("Cheeky Lua foveal mask menu changed upstream")
part = part.replace(old_labels,new_labels)
if part.count('combo("Pass 2 source views", "NrPass2Views", mask_labels, {3,7,4,1,2,5,6,0})') != 1:
    raise RuntimeError("Cheeky Lua pass-2 mask menu changed upstream")
part = part.replace('combo("Pass 2 source views", "NrPass2Views", mask_labels, {3,7,4,1,2,5,6,0})',
                    'combo("Pass 2 source views", "NrPass2Views", mask_labels, {3,1,2,0})')
ui = ui[:a] + part + ui[b:]
p.write_text(ui, encoding="utf-8", newline="\n")
print("DUO-TRI: foveas-only independent NR menus")

# Update the earlier pass-routing tests: masks containing the periphery bit
# are accepted for migration but cannot cause periphery inference.
p = root / "tests/gaze_tests.cpp"
tests = p.read_text(encoding="utf-8")
old_tests = """        expect(cheeky_nr_selected_passes(s,99001)==3U &&
               cheeky_nr_selected_passes(s,99002)==3U &&
               cheeky_nr_selected_passes(s,99004)==1U,
               "Pass1 all, pass2 foveas excludes peripheral pass2");"""
new_tests = """        expect(cheeky_nr_selected_passes(s,99001)==3U &&
               cheeky_nr_selected_passes(s,99002)==3U &&
               cheeky_nr_selected_passes(s,99004)==0U,
               "Pass1 all saved mask still bypasses periphery");"""
if tests.count(old_tests) != 1: raise RuntimeError("Missing source mask test 1")
tests = tests.replace(old_tests,new_tests)
old_tests = """        expect(cheeky_nr_selected_passes(s,99001)==2U &&
               cheeky_nr_selected_passes(s,99002)==2U &&
               cheeky_nr_selected_passes(s,99004)==1U,
               "Independent pass mask routing");"""
new_tests = """        expect(cheeky_nr_selected_passes(s,99001)==2U &&
               cheeky_nr_selected_passes(s,99002)==2U &&
               cheeky_nr_selected_passes(s,99004)==0U,
               "Independent NR passes skip periphery");"""
if tests.count(old_tests) != 1: raise RuntimeError("Missing source mask test 2")
tests = tests.replace(old_tests,new_tests)
old_tests = """        expect(cheeky_nr_selected_passes(s,99001)==0U &&
               cheeky_nr_selected_passes(s,99004)==2U,
               "Pass2-only peripheral routing");"""
new_tests = """        expect(cheeky_nr_selected_passes(s,99001)==0U &&
               cheeky_nr_selected_passes(s,99004)==0U,
               "Periphery-only saved masks perform no NR");"""
if tests.count(old_tests) != 1: raise RuntimeError("Missing source mask test 3")
tests = tests.replace(old_tests,new_tests)
marker = """        unregister_stereo_view(99003);
        update_settings(old);"""
if tests.count(marker)!=1: raise RuntimeError("Missing end-of-stereo-fixture marker")
duo_tests = """        unregister_stereo_view(99003);

        // A single CHEEKY binary must handle DuoView Mono's fovea and the
        // verified TriView fovea pair. Neither can enable peripheral NR.
        register_stereo_view(99110);
        register_stereo_view(99111);
        note_stereo_view_evaluation(99110,12U,1200U,800U,2400U,1600U);
        note_stereo_view_evaluation(99111,12U,400U,260U,800U,520U);
        note_stereo_view_output_subrect(99110,true,0U,0U);
        note_stereo_view_output_subrect(99111,true,1200U,0U);
        s.nr_enabled=true; s.nr_passes=2U;
        s.nr_pass1_views=7U; s.nr_pass2_views=7U; // old persisted "all"
        expect(cheeky_nr_selected_passes(s,99110)==3U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "DuoView positive subrect routes both passes only to mono fovea");
        // Source IDs/order can reverse, without changing anatomical roles.
        note_stereo_view_output_subrect(99110,true,1000U,0U);
        note_stereo_view_output_subrect(99111,true,0U,0U);
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==3U,
               "DuoView output subrect, not NGX handle order, chooses fovea");
        note_stereo_view_output_subrect(99110,true,0U,0U);
        note_stereo_view_output_subrect(99111,true,1200U,0U);
        // Ordinary stereo: equal dimensions plus two side-by-side outputs.
        note_stereo_view_evaluation(99111,12U,1200U,800U,2400U,1600U);
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Ordinary two-eye stereo is not guessed as DuoView");
        note_stereo_view_evaluation(99111,12U,400U,260U,800U,520U);
        note_stereo_view_output_subrect(99111,false,0U,0U);
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Missing NGX subrect evidence fails closed");
        note_stereo_view_output_subrect(99111,true,1200U,0U);
        s.nr_pass1_views=4U; s.nr_pass2_views=4U;
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Periphery-only legacy settings cannot enable any NR");
        unregister_stereo_view(99110);
        unregister_stereo_view(99111);
        update_settings(old);"""
tests=tests.replace(marker,duo_tests)
p.write_text(tests,encoding="utf-8",newline="\n")
print("DUO-TRI: source identity, no-periphery, missing tags, stereo disambiguation tests")

print("PASS DuoView/TriView foveas-only changes, with fail-closed unverified Duo layout")
