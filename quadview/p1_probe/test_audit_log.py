#!/usr/bin/env python3
from audit_log import audit

def d(kind,n,frame):
    return f"[2026-10-17] [QuadP1] draw={kind} serial={n} engine_frame={frame} thread=7 nested=false"
def v(seq,draw,frame,view,family,state,stereo):
    return (f"[QuadP1] constructor seq={seq} draw={draw} engine_frame={frame} "
            f"view={view:x} family={family:x} viewstate={state:x} original_pass={stereo} thread=7")

good="\n".join([
    d("begin",1,10),v(1,1,10,101,11,21,1),v(2,1,10,102,11,22,2),d("end",1,10),
    d("begin",2,10),v(3,2,10,103,12,23,1),v(4,2,10,104,12,24,2),d("end",2,10)
])
r=audit(good)
assert r["draw_count"]==2 and r["constructor_count"]==4
assert r["complete_native_two_view_draws"]==2
assert r["same_engine_frame_four_distinct_state_candidates"]==[[1,2]]
assert r["not_proven"] and not r["warnings"]

alias=good.replace("viewstate=18", "viewstate=16")
# 0x18=24 and 0x16=22: cross-pair state alias must not qualify.
a=audit(alias)
assert a["same_engine_frame_four_distinct_state_candidates"]==[]

null_history=good.replace("viewstate=18", "viewstate=0")
assert audit(null_history)["same_engine_frame_four_distinct_state_candidates"]==[]
duplicate_view=good.replace("view=66", "view=65")
assert audit(duplicate_view)["complete_native_two_view_draws"]==1

bad_tick=good.replace("draw=end serial=2 engine_frame=10","draw=end serial=2 engine_frame=11")
t=audit(bad_tick)
assert t["same_engine_frame_four_distinct_state_candidates"]==[]
assert any("changed within Draw" in e for e in t["warnings"])

# A paired redraw on the next XR frame cannot establish a shared world tick.
# Preserve it as ambiguous evidence, not a verified same-XR-frame QuadView.
cross_frame=good.replace("engine_frame=10", "engine_frame=11", 0)
cross_frame=good.splitlines()
cross_frame=[row.replace("engine_frame=10","engine_frame=11") if
             ("serial=2" in row or "draw=2" in row) else row for row in cross_frame]
cf=audit("\n".join(cross_frame))
assert cf["same_engine_frame_four_distinct_state_candidates"]==[]
assert cf["cross_engine_frame_ambiguous_four_state_candidates"]==[[1,2]]


desired="\n".join([
    "[QuadP1] desired seq=1 stereo=true post_init=true engine_frame=10 draw=0 thread=7",
    "[QuadP1] desired seq=2 stereo=false post_init=false engine_frame=10 draw=1 thread=7"
])
q=audit(good+"\n"+desired)
assert len(q["desired_view_count_call_observations"])==2
assert q["post_init_desired_call_count"]==1
assert q["desired_view_count_call_observations"][0]["active_draw"]==0

nested=good.replace("thread=7 nested=false","thread=7 nested=true",1)
n=audit(nested)
assert any("nested" in e for e in n["warnings"])
print("QuadP1 trace parser positive, alias, frame mutation and recursion tests passed")
