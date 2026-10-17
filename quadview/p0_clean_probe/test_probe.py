#!/usr/bin/env python3
"""Portable exact-anchor and reversibility tests for the read-only source patch."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "apply_read_only_probe.py"
sys.path.insert(0, str(HERE))
import apply_read_only_probe as probe

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def run(newline: str) -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        backend, frontend, evidence = root / "backend", root / "frontend", root / "evidence"
        source = backend / "src/mods/vr/FFakeStereoRenderingHook.cpp"
        source.parent.mkdir(parents=True)
        normal = (
            "#include <atomic>\n"
            "namespace { bool stalker2_is_current_game(); }\n"
            + probe.DRAW + "\n  fake_draw_body();\n}\n"
            "void constructor_hook() {\n"
            "    auto result = g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);\n"
            "    (void)result;\n"
            "}\n"
            "void duo_observation() { vr->duoview_state().scene(key,index,state,applied); }\n"
        )
        original = normal.replace("\n", newline).encode("utf-8")
        source.write_bytes(original)
        other = backend / "src/keep.cpp"
        other.write_text("backend\n", encoding="utf-8")
        frontend.mkdir(parents=True)
        front = frontend / "file.txt"
        front.write_text("frontend\n", encoding="utf-8")
        evidence.mkdir(parents=True)
        locks = {
            "backend": {
                "src/mods/vr/FFakeStereoRenderingHook.cpp": sha(original),
                "src/keep.cpp": sha(other.read_bytes())
            },
            "frontend": {"file.txt": sha(front.read_bytes())}
        }
        (evidence / "duoview-stage234-hashes.json").write_text(json.dumps(locks), encoding="utf-8")

        def invoke(*args, success=True):
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(backend), str(evidence), *args],
                capture_output=True, text=True
            )
            if (result.returncode == 0) != success:
                raise AssertionError(f"unexpected code={result.returncode}; out={result.stdout}; err={result.stderr}")

        invoke()
        modified = source.read_bytes()
        assert modified != original
        assert (b"\r\n" in modified) == (newline == "\r\n")
        invoke(str(frontend), "--verify")
        invoke(success=False)
        other.write_text("changed\n", encoding="utf-8")
        invoke(str(frontend), "--verify", success=False)
        other.write_text("backend\n", encoding="utf-8")
        source.write_bytes(modified + newline.encode() + b"// extra mutation" + newline.encode())
        invoke(str(frontend), "--verify", success=False)
        source.write_bytes(modified)
        invoke(str(frontend), "--verify")
        assert source.read_bytes() == modified
        print("read-only source probe is exact and reversible:", repr(newline))

if __name__ == "__main__":
    run("\n")
    run("\r\n")
