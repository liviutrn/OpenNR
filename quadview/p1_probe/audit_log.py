#!/usr/bin/env python3
"""Offline STALKER2/Joey QuadView P1 trace auditor.
Reads ONLY opt-in [QuadP1] records from ordinary UEVR log text. Reported
"candidates" are observations, never proof of owned histories or shaded images.
"""
import argparse
import json
import re
from collections import Counter

DRAW = re.compile(r"\[QuadP1\] draw=(begin|end) serial=(\d+) engine_frame=(\d+) thread=(\d+)(?: nested=(true|false))?")
DESIRED = re.compile(
    r"\[QuadP1\] desired seq=(\d+) stereo=(true|false|0|1) post_init=(true|false|0|1) "
    r"engine_frame=(\d+) draw=(\d+) thread=(\d+)"
)
VIEW = re.compile(
    r"\[QuadP1\] constructor seq=(\d+) draw=(\d+) engine_frame=(\d+) "
    r"view=([0-9a-fA-F]+) family=([0-9a-fA-F]+) "
    r"viewstate=([0-9a-fA-F]+) original_pass=(\d+) thread=(\d+)"
)

def audit(text: str)->dict:
    draws:dict[int,dict]={}
    rejected=[]
    count_views=0
    desired_events=[]
    for line in text.splitlines():
        a=DRAW.search(line)
        if a:
            kind,serial,frame,thread,nested=a.groups()
            serial=int(serial);frame=int(frame);thread=int(thread)
            slot=draws.setdefault(serial,{"views":[]})
            tag=f"{kind}_frame"
            if tag in slot:
                rejected.append(f"repeat {kind} for draw {serial}")
            slot[tag]=frame
            slot[kind+"_thread"]=thread
            if nested=="true":
                rejected.append(f"nested viewport Draw {serial}")
            continue
        d=DESIRED.search(line)
        if d:
            seq,stereo,post_init,frame,draw,thread=d.groups()
            desired_events.append({
                "sequence":int(seq), "stereo_enabled":stereo in ("true","1"),
                "post_init":post_init in ("true","1"),
                "engine_frame":int(frame), "active_draw":int(draw), "thread":int(thread)
            })
            continue
        b=VIEW.search(line)
        if b:
            seq,draw,frame,view,family,state,role,thread=b.groups()
            draw=int(draw);frame=int(frame)
            slot=draws.setdefault(draw,{"views":[]})
            slot["views"].append({
                "sequence":int(seq),"frame":frame,"view":int(view,16),
                "family":int(family,16),"state":int(state,16),
                "pass":int(role),"thread":int(thread)
            })
            count_views+=1
    clean=[]
    same_engine_candidates=[]
    cross_engine_candidates=[]
    ordered=sorted(draws)
    for d in ordered:
        rec=draws[d]
        views=rec.get("views",[])
        missing = "begin_frame" not in rec or "end_frame" not in rec
        if missing: rejected.append(f"incomplete Draw lifetime {d}")
        if rec.get("begin_frame") != rec.get("end_frame"):
            rejected.append(f"engine frame changed within Draw {d}")
        states=[v["state"] for v in views]
        families={v["family"] for v in views}
        passes=[v["pass"] for v in views]
        if len(states)!=len(set(states)):
            rejected.append(f"view-state alias within Draw {d}")
        if (len(views)==2 and len(families)==1 and set(passes)=={1,2} and
            len(set(states))==2 and len({v["view"] for v in views})==2 and
            all(v["view"] and v["family"] and v["state"] for v in views) and
            all(v["frame"]==rec.get("begin_frame") for v in views) and
            rec.get("begin_frame")==rec.get("end_frame") and not missing):
            clean.append(d)
    for a,b in zip(clean,clean[1:]):
        if b!=a+1:continue
        x,y=draws[a],draws[b]
        views=x["views"]+y["views"]
        # Still only a candidate: phase, four independently allocated owners,
        # stereo eye pose, GPU fences and world tick have NOT been established.
        if len({v["state"] for v in views})==4 and \
           len({v["family"] for v in views})==2:
            if x["begin_frame"]==y["begin_frame"]:
                same_engine_candidates.append([a,b])
            else:
                # Joey's existing SyncedSequential redraw may occur near the
                # NEXT engine tick before simulation advances. Different XR
                # frame labels alone cannot prove different WORLD ticks.
                cross_engine_candidates.append([a,b])
    pairs={}
    for d in clean:
        vals=draws[d]["views"]
        pairs[d]={str(v["pass"]):format(v["state"],"x") for v in vals}
    return {
        "protocol":"QuadP1 read-only engine-source observation",
        "draw_count":len(draws),"constructor_count":count_views,
        "complete_native_two_view_draws":len(clean),
        "desired_view_count_call_observations":desired_events,
        "post_init_desired_call_count":sum(1 for d in desired_events if d["post_init"]),
        "same_engine_frame_four_distinct_state_candidates":same_engine_candidates,
        "cross_engine_frame_ambiguous_four_state_candidates":cross_engine_candidates,
        "observed_pair_histories":pairs,
        "warnings":rejected,
        "not_proven":["four persistent engine-owned references","two same-eye physical camera poses",
                      "unchanged world/gameplay tick","independent renderer singleton shading",
                      "separate GPU source targets","fence retirement","XR two-eye acceptance"]
    }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("log",help="UEVR log text containing [QuadP1] lines")
    parser.add_argument("--output",help="optional analysis JSON output path")
    args=parser.parse_args()
    from pathlib import Path
    report=json.dumps(audit(Path(args.log).read_text(encoding="utf-8",errors="replace")),indent=2)
    if args.output: Path(args.output).write_text(report+"\n",encoding="utf-8")
    print(report)
if __name__=="__main__":
    main()
