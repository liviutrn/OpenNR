#!/usr/bin/env python3
"""Independent post-package verification. No shared-library execution.

Verifies the exact ZIP that is uploaded, PE architecture, payload hashes,
provenance and clear experimental identification. Fails closed.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys
import zipfile

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def check(cond,why):
    if not cond: raise RuntimeError(why)

def main():
    check(len(sys.argv)==4,"usage: audit_v44_package.py PACKAGE_DIR ZIP_FILE EVIDENCE_DIR")
    package,zip_path,evidence=map(Path,sys.argv[1:])
    needed={"UEVRBackend.dll","UEVRPluginNullifier.dll","LuaVR.dll",
            "READ_FIRST.txt","duoview-stage234-hashes.json",
            "exact-baseline-source.json","baseline.lock.json"}
    entries={}
    for path in sorted(package.rglob("*")):
        if path.is_file():
            rel=path.relative_to(package).as_posix()
            check(rel not in entries and ".." not in Path(rel).parts,"Unsafe package path")
            entries[rel]=sha256(path.read_bytes())
    check(needed.issubset(set(entries)),
          "Required package metadata/DLLs missing: "+str(needed-set(entries)))
    check(any(name.lower().endswith(".exe") for name in entries),
          "Matching original Joey frontend EXE missing")
    check(not any("ngngx" in name.lower() or "nvngx" in name.lower()
                  for name in entries),"NGX hook binary unexpectedly bundled")
    for name in ("UEVRBackend.dll","UEVRPluginNullifier.dll","LuaVR.dll"):
        data=(package/name).read_bytes()
        check(len(data)>=512 and data[:2]==b"MZ","Not a PE file: "+name)
        offset=struct.unpack_from("<I",data,0x3c)[0]
        check(offset+6<=len(data) and data[offset:offset+4]==bytes((80,69,0,0)),
              "Bad PE header: "+name)
        machine=struct.unpack_from("<H",data,offset+4)[0]
        check(machine==0x8664,"Non-x64 binary: "+name)
    readme=(package/"READ_FIRST.txt").read_text(encoding="utf-8-sig")
    check("v44" in readme and "QUARANTINED internally" in readme,
          "Read-first must identify v44 moving crop candidate and safe fallback")
    check("per-view previous projection" in readme and
          "does NOT prove TSR consumed correct vectors" in readme,
          "Must describe engine-owned projection history without claiming headset proof")
    with zipfile.ZipFile(zip_path) as archive:
        info=archive.infolist()
        zip_entries={}
        for z in info:
            check(not z.filename.startswith("/") and
                  ".." not in Path(z.filename).parts,"Unsafe ZIP path")
            if z.is_dir(): continue  # PowerShell archives can contain benign dir entries.
            check(z.filename not in zip_entries,"Duplicate ZIP payload path")
            zip_entries[z.filename]=sha256(archive.read(z))
        check(len(zip_entries)==len(entries),"ZIP payload file count mismatched package")
        check(entries==zip_entries,"ZIP extracted content hashes differ from package")
    declared_sha=zip_path.with_name(zip_path.name+".sha256")
    check(declared_sha.is_file(),"Missing final archive SHA256")
    check(declared_sha.read_text(encoding="utf-8").strip().lower()==
          sha256(zip_path.read_bytes()).lower(),"Final ZIP SHA256 mismatch")
    summary={"artifact":zip_path.name,"sha256":sha256(zip_path.read_bytes()),
             "zip_file_count":len(entries),"files":entries,
             "engine_previous_clip_verified":False,
             "experimental_compositor_ab_test":False,
             "moving_projection_crop":True,
             "view_state_history_gate":True,
             "headset_validated":False}
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/"v44-package-audit.json").write_text(
         json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print("v44 PE x64, ZIP round-trip SHA256, identity, documentation: PASS")
    print("ZIP SHA256:",summary["sha256"])
    print("ZIP FILE COUNT:",len(entries))
    print("NOT a proof of headset/Unreal TSR correction.")
if __name__=="__main__":
    main()
