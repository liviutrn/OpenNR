#!/usr/bin/env python3
"""Compile-time C++ regression additions for the configurable NR VRAM cap."""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
p=root/"tests/nr_processing_tests.cpp"
s=p.read_text(encoding="utf-8")
anchor='''        // Old INIs exposed intensity up to 2, although the model saturates at 1.'''
if s.count(anchor)!=1:raise RuntimeError("Expected one NR test insertion marker")
suite='''        // Log-informed November 13 VRAM policy: never bypass the NVIDIA
        // allocation admission for unknown DXGI memory, but allow users to
        // cap the guessed 2-4 GiB policy at 1536 MiB by default.
        {
            Settings base{};
            base.nr_enabled=true;
            base.nr_target_mode=0U;
            base.nr_passes=1U;
            base.nr_foveated=false;
            base.nr_processing_order=NrProcessingOrder::before_upscaling;
            require(base.nr_vram_guard_mib==1536U,
                "Fresh UEVR NR VRAM guard defaults to 1536 MiB");
            auto expands=base;
            expands.nr_processing_order=NrProcessingOrder::after_upscaling;
            const auto policy=nr_lite_required_headroom(base,expands);
            require(policy>1536ULL*nr_lite_mib,
                "Existing After-SR expansion is intentionally more conservative than 1536");
            const auto required=nr_lite_effective_headroom(base,expands);
            require(required==1536ULL*nr_lite_mib,
                "Guard caps the policy requirement at default 1536 MiB");
            for (const auto free_mib : {1705ULL,1961ULL,1823ULL,1863ULL}) {
                require(nr_lite_has_headroom(required,true,
                    (10020ULL-free_mib)*nr_lite_mib,10020ULL*nr_lite_mib),
                    "Logged 1705-1961 MiB free must admit a capped expansion");
            }
            require(!nr_lite_has_headroom(required,true,
                (10020ULL-1349ULL)*nr_lite_mib,10020ULL*nr_lite_mib),
                "Guard still rejects a riskier expansion at 1349 MiB free");
            require(!nr_lite_has_headroom(required,false,0U,0U),
                "Unknown DXGI headroom must still fail closed");
            expands.nr_vram_guard_mib=2048U;
            require(nr_lite_effective_headroom(base,expands)==2048ULL*nr_lite_mib,
                "User can restore a more conservative 2048 MiB cap");
            expands.nr_vram_guard_mib=512U;
            require(nr_lite_effective_headroom(base,expands)==512ULL*nr_lite_mib,
                "User can explicitly lower the headroom cap at own risk");
            expands.nr_vram_guard_mib=4096U;
            require(nr_lite_effective_headroom(base,expands)==policy,
                "Higher cap cannot invent an allocation demand beyond policy");
            auto rekey=base;rekey.nr_preset=base.nr_preset+1U;
            require(nr_lite_required_headroom(base,rekey)==768ULL*nr_lite_mib &&
                    nr_lite_effective_headroom(base,rekey)==768ULL*nr_lite_mib,
                "Small model rekey preserves old 768 MiB requirement");
            auto cap_only=base;cap_only.nr_vram_guard_mib=4096U;
            require(nr_lite_effective_headroom(base,cap_only)==0ULL,
                "Changing guard setting alone must not request GPU reallocation");
            auto less=base;less.nr_enabled=false;
            require(nr_lite_effective_headroom(base,less)==0ULL,
                "Disabling NR must always remain free");
            auto duo_both=base;duo_both.nr_target_mode=1U;
            require(nr_lite_effective_headroom(duo_both,base)==0ULL,
                "Removing periphery NR remains a no-headroom recovery edit");
        }
'''
s=s.replace(anchor,suite+anchor,1)
p.write_text(s,encoding="utf-8",newline="\n")
print("PASS compiled adjustable guard regressions: default, cap, logs, rekey, reduced work, DXGI unknown")
