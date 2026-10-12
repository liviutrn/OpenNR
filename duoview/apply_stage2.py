#!/usr/bin/env python3
"""Apply Stage 2 over the already applied Stage 1 patch.

Creates a two-view, unequal-viewport atlas diagnostic. It does NOT yet include
the GPU compositor and MUST NOT be advertised as a usable foveated headset
rendering mode. Both views share the same centered Mono camera.
"""
import argparse
from pathlib import Path
import shutil

def once(src: str, old: str, new: str, name: str) -> str:
    n = src.count(old)
    if n != 1:
        raise RuntimeError(f"Stage2 {name}: anchor count {n}, expected 1: {old[:110]!r}")
    return src.replace(old,new,1)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root",type=Path)
    a=ap.parse_args()
    root=a.root.resolve()
    cpp="src/mods/vr/FFakeStereoRenderingHook.cpp"
    policy="src/mods/vr/MonoRenderingPolicy.hpp"
    prior=(root/cpp).read_text(encoding="utf-8")
    new=prior

    new=once(new,
        '#include "FFakeStereoRenderingHook.hpp"',
        '#include "FFakeStereoRenderingHook.hpp"\n#include "DuoViewGeometry.hpp"',
        cpp)
    new=once(new,
        '    if (VR::get()->is_using_mono() && !VR::get()->is_using_duoview_mono()) {\n'
        '        *x = 0;\n'
        '        *y = 0;\n'
        '    } else if (!VR::get()->is_native_stereo_fix_enabled()) {',
        '    if (VR::get()->is_using_duoview_mono()) {\n'
        '        // STAGE 2 PROBE: actual UE view rectangles, NOT a final VR image.\n'
        '        // The current Mono submitter will not yet unpack/composite these!\n'
        '        const auto layout = uevr::duoview::make_layout(\n'
        '            VR::get()->get_hmd_width(), VR::get()->get_hmd_height());\n'
        '        if (layout) {\n'
        '            const auto& rect = true_index == 0 ? layout->fovea : layout->periphery;\n'
        '            *x = static_cast<int>(rect.x);\n'
        '            *y = static_cast<int>(rect.y);\n'
        '            *w = rect.width;\n'
        '            *h = rect.height;\n'
        '        } else {\n'
        '            SPDLOG_ERROR_EVERY_N_SEC(2, "[DuoView] Invalid atlas layout: defaulting to full equal views");\n'
        '            *x = *w * true_index;\n'
        '            *y = 0;\n'
        '        }\n'
        '        return;\n'
        '    }\n'
        '    if (VR::get()->is_using_mono() && !VR::get()->is_using_duoview_mono()) {\n'
        '        *x = 0;\n'
        '        *y = 0;\n'
        '    } else if (!VR::get()->is_native_stereo_fix_enabled()) {',
        cpp)
    new=once(new,
        '        if (vr->is_using_mono()) { true_index = 0; }\n\n'
        '        auto& double_matrix = *(Matrix4x4d*)out;',
        '        // Index of the UE view, before the physical camera is forced to\n'
        '        // the shared Mono origin and optical projection.\n'
        '        const auto duoview_pass = true_index;\n'
        '        if (vr->is_using_mono()) { true_index = 0; }\n\n'
        '        auto& double_matrix = *(Matrix4x4d*)out;',
        cpp)
    new=once(new,
        '        if (vr->mono_frame_gate_required() && vr->get_runtime()->is_openxr()) {\n'
        '            vr->get_openxr_runtime()->note_mono_projection();\n'
        '        }',
        '        if (vr->is_using_duoview_mono() && duoview_pass == 0) {\n'
        '            const auto layout = uevr::duoview::make_layout(\n'
        '                vr->get_hmd_width(), vr->get_hmd_height());\n'
        '            if (layout) {\n'
        '                // Project only the fovea into its crop view rectangle;\n'
        '                // UE view 1 retains the existing full Mono projection.\n'
        '                if (g_hook->m_has_double_precision) {\n'
        '                    uevr::duoview::apply_foveal_crop(double_matrix, *layout);\n'
        '                } else {\n'
        '                    uevr::duoview::apply_foveal_crop(*out, *layout);\n'
        '                }\n'
        '            }\n'
        '        }\n'
        '        if (vr->mono_frame_gate_required() && vr->get_runtime()->is_openxr()) {\n'
        '            vr->get_openxr_runtime()->note_mono_projection();\n'
        '        }',
        cpp)
    old_label='Choice{duoview_method_id, "DuoView Mono (Stage 1 Diagnostic)"},'
    new_label='Choice{duoview_method_id, "DuoView Mono (Atlas Diagnostic - Uncomposited)"},'
    p=(root/policy).read_text(encoding="utf-8")
    p=once(p,old_label,new_label,policy)

    # All anchors were matched. Atomically commit source only after validation.
    (root/cpp).write_text(new, encoding="utf-8",newline="\n")
    (root/policy).write_text(p, encoding="utf-8",newline="\n")
    target=root/"src/mods/vr/DuoViewGeometry.hpp"
    shutil.copyfile(Path(__file__).with_name("DuoViewGeometry.hpp"),target)
    print("Stage 2 atlas rectangle/projection patch applied. COMPOSITION NOT PRESENT.")

if __name__=="__main__": main()
