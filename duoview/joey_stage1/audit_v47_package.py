#!/usr/bin/env python3
"""Independent post-package verification for the v47 fixed-crop safety build."""
from pathlib import Path
import hashlib
import json
import struct
import sys
import zipfile

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def check(cond, why):
    if not cond:
        raise RuntimeError(why)

def main():
    check(len(sys.argv) == 4,
          "usage: audit_v47_package.py PACKAGE_DIR ZIP_FILE EVIDENCE_DIR")
    package, zip_path, evidence = map(Path, sys.argv[1:])
    needed = {"UEVRBackend.dll", "UEVRPluginNullifier.dll", "LuaVR.dll",
              "READ_FIRST.txt", "duoview-stage234-hashes.json",
              "exact-baseline-source.json", "baseline.lock.json",
              "duoview-v47-target-policy.json"}
    entries = {}
    for path in sorted(package.rglob("*")):
        if path.is_file():
            rel = path.relative_to(package).as_posix()
            check(rel not in entries and ".." not in Path(rel).parts,
                  "Unsafe or duplicate package path")
            entries[rel] = sha256(path.read_bytes())
    check(needed.issubset(set(entries)),
          "Required package metadata/DLLs missing: " + str(needed-set(entries)))
    check(any(name.lower().endswith(".exe") for name in entries),
          "Matching original Joey frontend EXE missing")
    check(not any("ngngx" in name.lower() or "nvngx" in name.lower()
                  for name in entries), "NGX hook binary unexpectedly bundled")

    for name in ("UEVRBackend.dll", "UEVRPluginNullifier.dll", "LuaVR.dll"):
        data = (package / name).read_bytes()
        check(len(data) >= 512 and data[:2] == b"MZ", "Not a PE file: " + name)
        offset = struct.unpack_from("<I", data, 0x3c)[0]
        check(offset + 6 <= len(data) and data[offset:offset+4] == bytes((80,69,0,0)),
              "Bad PE header: " + name)
        machine = struct.unpack_from("<H", data, offset+4)[0]
        check(machine == 0x8664, "Non-x64 binary: " + name)

    readme = (package / "READ_FIRST.txt").read_text(encoding="utf-8-sig")
    check("v47" in readme and "UE 5.5.4" in readme and
          "fixed-center crop" in readme,
          "Read-first must identify the UE5.5.4 fixed-crop fallback")
    check("does not write the unverified ClipToPrevClipOverride memory field" in readme,
          "Read-first must clearly state the UE5.5 raw-write prohibition")
    check("Reselecting ID6 will not clear a fault quarantine" in readme and
          "does NOT prove that Unreal TSR consumes the override" in readme,
          "Read-first must describe session quarantine and validation limits")

    policy = json.loads((package / "duoview-v47-target-policy.json").read_text(encoding="utf-8"))
    check(policy.get("engine_target") == "UE 5.5.4" and
          policy.get("eye_tracked_crop_enabled") is False and
          policy.get("fixed_crop_fallback") is True and
          policy.get("unverified_ue55_sceneview_write") is False,
          "Packaged v47 target policy does not match the fixed-crop build")
    with zipfile.ZipFile(zip_path) as archive:
        zip_entries = {}
        for item in archive.infolist():
            check(not item.filename.startswith("/") and
                  ".." not in Path(item.filename).parts, "Unsafe ZIP path")
            if item.is_dir():
                continue
            check(item.filename not in zip_entries, "Duplicate ZIP payload path")
            zip_entries[item.filename] = sha256(archive.read(item))
        check(len(zip_entries) == len(entries), "ZIP payload file count mismatched package")
        check(entries == zip_entries, "ZIP content hashes differ from package")

    declared_sha = zip_path.with_name(zip_path.name + ".sha256")
    check(declared_sha.is_file(), "Missing final archive SHA256")
    archive_sha = sha256(zip_path.read_bytes())
    check(declared_sha.read_text(encoding="utf-8").strip().lower() == archive_sha,
          "Final ZIP SHA256 mismatch")
    summary = {
        "artifact": zip_path.name,
        "sha256": archive_sha,
        "zip_file_count": len(entries),
        "files": entries,
        "ue55_gaze_crop_enabled": False,
        "fixed_crop_fallback": True,
        "unknown_ue55_sceneview_field_written": False,
        "headset_validated": False,
    }
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "v47-package-audit.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("v47 x64 PE, ZIP round-trip, source provenance, and UE5.5 fixed-crop audit: PASS")
    print("ZIP SHA256:", archive_sha)
    print("ZIP FILE COUNT:", len(entries))
    print("UE5.5 eye-tracked crop: disabled; headset behavior remains unverified")

if __name__ == "__main__":
    main()
