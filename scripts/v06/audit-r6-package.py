"""Audit the exact r6 package against the tested r5 package."""
from pathlib import Path
import hashlib, json, shutil, struct, subprocess, os

root = Path.cwd()
seven = shutil.which("7z") or r"C:\Program Files\7-Zip\7z.exe"
assert Path(seven).exists(), "7-Zip unavailable"
archives = {}
manifests = {}
for revision in ("r5", "r6"):
    candidates = list((root / "artifacts" / revision).glob("*.7z"))
    assert len(candidates) == 1, (revision, candidates)
    archive = candidates[0]
    archives[revision] = {"name": archive.name, "size": archive.stat().st_size,
                          "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    subprocess.run([seven, "t", str(archive), "-bd"], check=True)
    output = root / "expanded" / revision
    subprocess.run([seven, "x", str(archive), "-o" + str(output), "-y", "-bd"], check=True)
    manifest = {}
    for path in sorted(output.rglob("*")):
        name = path.relative_to(output).as_posix()
        if path.is_dir():
            manifest[name + "/"] = {"size": 0, "sha256": hashlib.sha256(b"").hexdigest()}
        else:
            data = path.read_bytes()
            manifest[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifests[revision] = manifest

old, new = manifests["r5"], manifests["r6"]
added = sorted(set(new) - set(old))
removed = sorted(set(old) - set(new))
changed = sorted(p for p in set(old) & set(new) if old[p] != new[p])
expected_added = []
expected_changed = ["SKSE/Plugins/CommunityShaders.dll",
                    "Shaders/Upscaling/NeuralRendering/OutsideSeamApplyCS.hlsl",
                    "Shaders/Upscaling/NeuralRendering/OutsideToneApplyCS.hlsl",
                    "Shaders/Upscaling/NeuralRendering/ResultShapingCS.hlsl"]
assert added == expected_added, ("Unexpected additions", added)
assert not removed, ("Missing r5 payloads", removed)
assert changed == expected_changed, ("Unexpected changed payloads", changed)
assert not any(p.lower().endswith("nvngx_dlssnr.dll") for p in new), "NR carrier unexpectedly included"
expected_hashes = {}
source_root = root / "runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering"
for name in ("OutsideSeamApplyCS.hlsl", "OutsideSeamMapCS.hlsl", "OutsideSeamSmoothCS.hlsl",
             "OutsideToneApplyCS.hlsl", "OutsideToneMapCS.hlsl", "OutsideToneSmoothCS.hlsl", "ResultShapingCS.hlsl"):
    expected_hashes["Shaders/Upscaling/NeuralRendering/" + name] = hashlib.sha256((source_root / name).read_bytes()).hexdigest()
for name, expected in expected_hashes.items():
    assert new[name]["sha256"] == expected, ("Shader differs from reviewed source", name)

dll = (root / "expanded/r6/SKSE/Plugins/CommunityShaders.dll").read_bytes()
assert dll[:2] == b"MZ"
offset = struct.unpack_from("<I", dll, 60)[0]
assert dll[offset:offset+4] == b"PE\0\0"
assert struct.unpack_from("<H", dll, offset+4)[0] == 0x8664
markers = ["Outside NR tone transfer", "configureOutsideTone", "outsideToneMode", "Boundary gain + offset", "Targeted seam curve", "Outside contrast transfer", "Contrast reach",
           "Shadow / highlight curve", "NR near-black protection", "Protection strength", "Dark threshold", "Positive lift onset", "configureNeuralBlackProtection", "Hold before outside fade",
           "Brightness offset limit", "Correction map smoothing", "Outside edge protection",
           "NeuralRendering::OutsideToneMap", "NeuralRendering::OutsideToneApply", "NeuralRendering::OutsideToneSmooth"]
for marker in markers:
    assert marker.encode() in dll, ("New runtime feature missing from DLL", marker)
for marker in ("OutsideToneMapCS.hlsl", "OutsideToneApplyCS.hlsl", "OutsideToneSmoothCS.hlsl",
               "OutsideSeamMapCS.hlsl", "OutsideSeamApplyCS.hlsl", "OutsideSeamSmoothCS.hlsl"):
    assert marker.encode("utf-16-le") in dll, ("Shader path missing from DLL", marker)

result = {
    "build_commit": os.environ.get("GITHUB_SHA"),
    "build_run": os.environ.get("GITHUB_RUN_ID"),
    "r5_build_commit": "99e580549564b8b1d5e4531e86b3d218250cf2aa",
    "archives": archives,
    "r5_entries": len(old), "r6_entries": len(new),
    "added": added, "removed": removed, "changed": changed,
    "shader_hashes_match_reviewed_source": True,
    "every_other_r5_payload_identical": True,
    "x64_dll_and_new_runtime_controls_verified": True,
    "all_archive_crc_and_data_checks_passed": True,
    "nr_carrier_excluded": True,
    "dll": new["SKSE/Plugins/CommunityShaders.dll"],
    "gpu_ms_and_vr_quality_measured": False
}
(root / "audit-results").mkdir(exist_ok=True)
for name, data in (("package-audit.json", result), ("r6-manifest.json", new), ("r5-manifest.json", old)):
    (root / "audit-results" / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print("PACKAGE_AUDIT_RESULT=" + json.dumps(result, separators=(",",":")))

