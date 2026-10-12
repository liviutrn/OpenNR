#!/usr/bin/env python3
"""Temporary, STALKER 2 UE5.5-only public-SDK compiler probe.

Only excludes code that unambiguously depends on SDK ABIs for UE5.0-5.3
or a UE5.8 transitional variant. Does not invent memory layouts, offsets
or virtual tables. NO full game-ready runtime guarantee.
"""
from pathlib import Path
import argparse

def one(t,old,new,name):
    if t.count(old) != 1:
        raise RuntimeError(f"{name}: expected exactly one anchor, got {t.count(old)}: {old[:140]!r}")
    return t.replace(old,new,1)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("root",type=Path)
    root=ap.parse_args().root
    h=root/"src/mods/vr/FFakeStereoRenderingHook.hpp"
    c=root/"src/mods/vr/FFakeStereoRenderingHook.cpp"
    hs=h.read_text(encoding="utf-8")
    cs=c.read_text(encoding="utf-8")
    begin="struct VRRenderTargetManager_58_Transitional : IStereoRenderTargetManager_58_Transitional, VRRenderTargetManager_Base {"
    end="enum class UE58RenderTargetManagerABI : uint8_t {"
    assert hs.count(begin)==1 and hs.count(end)==1
    first,last=hs.index(begin),hs.index(end)
    hs=hs[:first]+"#if !defined(UEVR_DUOVIEW_PUBLICSDK_STALKER2_ONLY)\n"+hs[first:last]+"#endif // UE5.8 ABI unavailable in public SDK; not used by UE5.5.4 STALKER 2\n\n"+hs[last:]
    old="        std::unordered_map<sdk::FSceneViewStateInterface*, sdk::FSceneViewInitOptionsUE50To53> view_init_options_ue50_to_53{};"
    hs=one(hs,old,"#if !defined(UEVR_DUOVIEW_PUBLICSDK_STALKER2_ONLY)\n"+old+"\n#endif",str(h))
    first="bool VRRenderTargetManager_58_Transitional::AllocateRenderTargetTextures("
    last="bool VRRenderTargetManager_418::AllocateRenderTargetTexture("
    assert cs.count(first)==1 and cs.count(last)==1
    a,b=cs.index(first),cs.index(last)
    cs=cs[:a]+"#if !defined(UEVR_DUOVIEW_PUBLICSDK_STALKER2_ONLY)\n"+cs[a:b]+"#endif\n\n"+cs[b:]
    old="    auto init_options_ue50_to_53 = (sdk::FSceneViewInitOptionsUE50To53*)init_options;"
    cs=one(cs,old,"#if !defined(UEVR_DUOVIEW_PUBLICSDK_STALKER2_ONLY)\n"+old+"\n#endif",str(c))
    old=("        if (is_ue50_to_53) {\n"
         "            auto& vio_entry = g_hook->m_sceneview_data.view_init_options_ue50_to_53[init_options_scene_state];\n"
         "            memcpy(&vio_entry, init_options, sizeof(sdk::FSceneViewInitOptionsUE50To53));\n"
         "        } else if (is_ue5) {")
    replacement=("        if (is_ue50_to_53) {\n"
                 "#if !defined(UEVR_DUOVIEW_PUBLICSDK_STALKER2_ONLY)\n"
                 "            auto& vio_entry = g_hook->m_sceneview_data.view_init_options_ue50_to_53[init_options_scene_state];\n"
                 "            memcpy(&vio_entry, init_options, sizeof(sdk::FSceneViewInitOptionsUE50To53));\n"
                 "#else\n"
                 "            // Probe supports UE5.5 only; cannot copy an unknown UE5.0-5.3 memory layout.\n"
                 "            SPDLOG_ERROR_ONCE(\"[DuoView] Unsupported UE5.0-5.3 InitOptions ABI in public SDK probe\");\n"
                 "#endif\n"
                 "        } else if (is_ue5) {")
    cs=one(cs,old,replacement,str(c))
    hs="#define UEVR_DUOVIEW_PUBLICSDK_STALKER2_ONLY 1\n"+hs
    cs="#define UEVR_DUOVIEW_PUBLICSDK_STALKER2_ONLY 1\n"+cs
    h.write_text(hs,encoding="utf-8",newline="\n")
    c.write_text(cs,encoding="utf-8",newline="\n")
    print("STALKER2-only public SDK ABI compile probe applied: UE5.8 Transitional and UE5.0-5.3 InitOptions disabled")

if __name__=="__main__":main()
