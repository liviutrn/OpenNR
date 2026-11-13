#!/usr/bin/env python3
"""C1/C3/C4/C6 behavioral test extensions for pinned generated Cheeky source."""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
p=root/"tests/gaze_tests.cpp";s=p.read_text(encoding="utf-8")
a=s.index('        s.nr_target_mode=0U; s.nr_pass1_views=7U; s.nr_pass2_views=7U;\n        s.nr_duo_fovea_source=1U;')
b=s.index('        s.nr_duo_fovea_source=0U;\n        note_stereo_view_evaluation(99110,12U,400U,260U,800U,520U);',a)
new='''        s.nr_target_mode=0U; s.nr_pass1_views=7U; s.nr_pass2_views=7U;
        s.nr_duo_fovea_source=1U;
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Forced larger image never guesses on equal-size DLSS inputs");
        s.nr_duo_fovea_source=2U;
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Forced smaller image never guesses on equal-size DLSS inputs");
        note_stereo_view_evaluation(99111,12U,400U,260U,800U,520U);
        s.nr_duo_fovea_source=1U;
        const auto larger = cheeky_nr_selection(s,99110);
        expect(larger.role==1U && larger.passes==3U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Forced larger-input fovea identifies actual larger region");
        s.nr_duo_fovea_source=2U;
        const auto smaller = cheeky_nr_selection(s,99111);
        expect(smaller.role==1U && smaller.passes==3U &&
               cheeky_nr_selected_passes(s,99110)==0U,
               "Forced smaller-input fovea identifies actual smaller region");
'''
s=s[:a]+new+s[b:]
p.write_text(s,encoding="utf-8",newline="\n")
print("FABLE-TEST: Duo size hint, equal input fail closed, one-call role selection")

p=root/"tests/nr_processing_tests.cpp";s=p.read_text(encoding="utf-8")
anchor='''        // Old INIs exposed intensity up to 2, although the model saturates at 1.'''
if s.count(anchor)!=1:raise RuntimeError("Unable to locate NR budget test insertion")
extra='''        // Fable C1/C4: requested-source admission and same-family recovery.
        {
            Settings tri{}, duo{}, tri_all{};
            tri.nr_enabled=true;
            tri.nr_target_mode=2U; tri.nr_pass1_views=7U;
            tri.nr_passes=1U; tri.nr_foveated=true;
            duo=tri; duo.nr_target_mode=0U;
            Settings fresh=duo; fresh.nr_enabled=false;
            const auto from_scratch=nr_lite_required_headroom(fresh,duo);
            require(from_scratch>0U &&
                    nr_lite_required_headroom(tri,duo)==from_scratch,
                    "Tri->Duo reserves the REQUESTED one-fovea allocation");
            tri_all=tri;tri_all.nr_target_mode=3U;
            require(nr_lite_required_headroom(tri_all,tri)==0U,
                    "Tri all->foveas must remain zero-reserve recovery");
            require(nr_lite_required_headroom(duo,tri)>0U,
                    "Duo->Tri needs headroom for requested 2-fovea features");
            Settings duo_all=duo;duo_all.nr_target_mode=1U;
            require(nr_lite_required_headroom(duo_all,duo)==0U,
                    "Duo both->fovea-only must remain zero-reserve recovery");
            Settings change=duo;
            change.nr_duo_fovea_source=2U;
            change.nr_target_mode=1U;
            require(nr_lite_required_headroom(duo,change)>=2048ULL*nr_lite_mib,
                    "Simultaneous size-hint and new periphery target needs MAX reserve");
        }
'''
s=s.replace(anchor,extra+anchor,1)
p.write_text(s,encoding="utf-8",newline="\n")
print("FABLE-TEST: live NR budget policy family changes, reduction & simultaneous growth")
