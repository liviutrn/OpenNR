#!/usr/bin/env python3
"""Isolated exact-source patcher contract: no UEVR checkout, SDK or graphics needed."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
SCRIPT=HERE/"apply_read_only_probe.py"
sys.path.insert(0,str(HERE))
import apply_read_only_probe as probe

def sha(content:bytes)->str:
    return hashlib.sha256(content).hexdigest()

def check(newline:str):
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);backend=root/"backend";frontend=root/"frontend";evidence=root/"evidence"
        source=backend/"src/mods/vr/FFakeStereoRenderingHook.cpp"
        source.parent.mkdir(parents=True)
        normal=(
            "#include <atomic>\n"
            "void mock_header() {}\n"
            "// duo_scene_observation exists in exact Stage234 source\n"
            +probe.DRAW +"\n  fake_body();\n}\n"
            +"void mock_constructor() {\n"+probe.CONSTRUCTOR+"\n}\n"
        )
        original=normal.replace("\n",newline).encode("utf-8")
        source.write_bytes(original)
        other=backend/"src/keep.cpp";other.write_text("original\n",encoding="utf-8")
        frontend.mkdir(parents=True);front=(frontend/"file.txt");front.write_text("frontend\n",encoding="utf-8")
        evidence.mkdir(parents=True)
        lock={
            "backend":{
                "src/mods/vr/FFakeStereoRenderingHook.cpp":sha(original),
                "src/keep.cpp":sha(other.read_bytes())
            },
            "frontend":{"file.txt":sha(front.read_bytes())}
        }
        (evidence/"duoview-stage234-hashes.json").write_text(json.dumps(lock),encoding="utf-8")
        def run(*args,success=True):
            p=subprocess.run([sys.executable,str(SCRIPT),str(backend),str(evidence),*args],
                             capture_output=True,text=True)
            if (p.returncode==0)!=success:
                raise AssertionError(f"probe returned {p.returncode}; stdout={p.stdout}; stderr={p.stderr}")
        run()
        modified=source.read_bytes()
        assert modified!=original
        assert (b"\r\n" in modified)==(newline=="\r\n")
        run(str(frontend),"--verify")
        run(success=False) # no duplicate instrumentation
        other.write_text("wrong\n",encoding="utf-8")
        run(str(frontend),"--verify",success=False)
        other.write_text("original\n",encoding="utf-8")
        source.write_bytes(modified+b"\n// unverified extra source mutation\n")
        run(str(frontend),"--verify",success=False)
        source.write_bytes(modified)
        run(str(frontend),"--verify")
        assert source.read_bytes()==modified
        print("strict reversible source probe and protected hashes OK:",repr(newline))

if __name__=="__main__":
    check("\n")
    check("\r\n")
