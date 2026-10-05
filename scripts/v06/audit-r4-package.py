"""Audit the exact r4 package against the tested r3 package."""
from pathlib import Path
import hashlib, json, shutil, struct, subprocess

root = Path.cwd()
seven = shutil.which("7z") or r"C:\Program Files\7-Zip\7z.exe"
assert Path(seven).exists(), "7-Zip unavailable"
archives = {}
manifests = {}
for revision in ("r3", "r4"):
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

old, new = manifests["r3"], manifests["r4"]
added = sorted(set(new) - set(old))
removed = sorted(set(old) - set(new))
changed = sorted(p for p in set(old) & set(new) if old[p] != new[p])
expected_added = ["Shaders/Upscaling/NeuralRendering/OutsideToneSmoothCS.hlsl"]
expected_changed = ["SKSE/Plugins/CommunityShaders.dll",
                    "Shaders/Upscaling/NeuralRendering/OutsideToneApplyCS.hlsl",
                    "Shaders/Upscaling/NeuralRendering/OutsideToneMapCS.hlsl"]
assert added == expected_added, ("Unexpected additions", added)
assert not removed, ("Missing r3 payloads", removed)
assert changed == expected_changed, ("Unexpected changed payloads", changed)
assert not any(p.lower().endswith("nvngx_dlssnr.dll") for p in new), "NR carrier unexpectedly included"
expected_hashes = {
    "Shaders/Upscaling/NeuralRendering/OutsideToneApplyCS.hlsl": "643825fe14dbccf0a580b0462ba5c3a68d71ea0e6ea5e6aa268234cb3054a064",
    "Shaders/Upscaling/NeuralRendering/OutsideToneMapCS.hlsl": "d53430f9691b3c691859c04bd7d26af04857195ad658d0b3d07ffe917f1ef712",
    "Shaders/Upscaling/NeuralRendering/OutsideToneSmoothCS.hlsl": "7b621186130d56879f9c2a2243bb574619cf251e057c100f35c51f19a9b0c8df"
}
for name, expected in expected_hashes.items():
    assert new[name]["sha256"] == expected, ("Shader differs from reviewed source", name)

dll = (root / "expanded/r4/SKSE/Plugins/CommunityShaders.dll").read_bytes()
assert dll[:2] == b"MZ"
offset = struct.unpack_from("<I", dll, 60)[0]
assert dll[offset:offset+4] == b"PE\0\0"
assert struct.unpack_from("<H", dll, offset+4)[0] == 0x8664
markers = ["Outside NR tone transfer", "configureOutsideTone", "outsideToneMode", "Boundary gain + offset",
           "Brightness offset limit", "Correction map smoothing", "Outside edge protection",
           "NeuralRendering::OutsideToneMap", "NeuralRendering::OutsideToneApply", "NeuralRendering::OutsideToneSmooth"]
for marker in markers:
    assert marker.encode() in dll, ("New runtime feature missing from DLL", marker)
for marker in ("OutsideToneMapCS.hlsl", "OutsideToneApplyCS.hlsl", "OutsideToneSmoothCS.hlsl"):
    assert marker.encode("utf-16-le") in dll, ("Shader path missing from DLL", marker)

result = {
    "build_commit": "196780498dc3e19cacdc6ed9ac02d18fde677481",
    "build_run": 37346929262,
    "r3_build_commit": "4dfcd4d2fdc547d3d8bdc9dff713016506e9299b",
    "archives": archives,
    "r3_entries": len(old), "r4_entries": len(new),
    "added": added, "removed": removed, "changed": changed,
    "shader_hashes_match_reviewed_source": True,
    "every_other_r3_payload_identical": True,
    "x64_dll_and_new_runtime_controls_verified": True,
    "all_archive_crc_and_data_checks_passed": True,
    "nr_carrier_excluded": True,
    "dll": new["SKSE/Plugins/CommunityShaders.dll"],
    "gpu_ms_and_vr_quality_measured": False
}
(root / "audit-results").mkdir(exist_ok=True)
for name, data in (("package-audit.json", result), ("r4-manifest.json", new), ("r3-manifest.json", old)):
    (root / "audit-results" / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print("PACKAGE_AUDIT_RESULT=" + json.dumps(result, separators=(",",":")))
