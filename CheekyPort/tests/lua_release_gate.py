#!/usr/bin/env python3
"""Independent preflight for compiled Lua source and actual distributed ZIP payload.

DO NOT import or reuse Cheeky's patch helpers: this checks their *output*.
Compile with the real Lua 5.1 and 5.4 parsers (no execution), and compare ZIP
bytes against the generated source. Fails closed for absent/mismatched Lua.
"""
from pathlib import Path
import hashlib
import sys
import zipfile

from lupa.lua51 import LuaRuntime as Lua51Runtime
from lupa.lua54 import LuaRuntime as Lua54Runtime

def check_lua(data: bytes, label: str) -> None:
    text = data.decode("utf-8-sig")
    for ver, constructor in (("Lua 5.1", Lua51Runtime), ("Lua 5.4", Lua54Runtime)):
        runtime = constructor(unpack_returned_tuples=True)
        # Compile only; do not execute the UEVR plugin or its entry points.
        compile_chunk = runtime.eval(
            "function(src, chunk) "
            "local fn, err = (loadstring or load)(src, chunk); "
            "return fn ~= nil, err end"
        )
        ok, error = compile_chunk(text, "@" + label)
        if not ok:
            raise RuntimeError(f"{label}: {ver} syntax error: {error}")
        print(f"LUA COMPILE OK {ver}: {label} sha256={hashlib.sha256(data).hexdigest()[:16]}")

def negative_fixture() -> None:
    invalid = b"local mem = status.gpu_memory.local\n"
    for version, creator in (("5.1", Lua51Runtime), ("5.4", Lua54Runtime)):
        rt = creator(unpack_returned_tuples=True)
        valid, _ = rt.eval("function(s) local f,e=(loadstring or load)(s); return f~=nil,e end")(
            invalid.decode("ascii")
        )
        if valid:
            raise RuntimeError(f"Lua {version} rejected-keyword negative fixture falsely accepted")
    print("LUA NEGATIVE FIXTURE OK: .local correctly rejected by both compilers")

def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"source", "package"}:
        raise SystemExit("usage: lua_release_gate.py source|package <upstream-cheeky-directory>")
    mode = sys.argv[1]
    root = Path(sys.argv[2]).resolve()
    key = Path("uevr/scripts/cheeky_foveated_dlss.lua")
    source_path = root / key
    if not source_path.is_file():
        raise RuntimeError(f"Missing generated Lua: {source_path}")
    source_bytes = source_path.read_bytes()
    negative_fixture()
    lua_files = sorted((root / "uevr/scripts").rglob("*.lua"))
    if not lua_files:
        raise RuntimeError("No Lua files to compile")
    for path in lua_files:
        check_lua(path.read_bytes(), str(path.relative_to(root)))
    if mode == "source":
        print(f"PASS source Lua release gate: {len(lua_files)} files compiled in two Lua runtimes")
        return

    archives = list((root / "bin/Release").glob("*-UEVR-v063-triview-nr-lite.zip"))
    if len(archives) != 1:
        raise RuntimeError(f"Expected exactly one UEVR ZIP, found {len(archives)}")
    archive = archives[0]
    with zipfile.ZipFile(archive) as z:
        bad_member = z.testzip()
        if bad_member is not None:
            raise RuntimeError(f"Corrupt ZIP member: {bad_member}")
        members = [i.filename for i in z.infolist()]
        expected = "scripts/cheeky_foveated_dlss.lua"
        if members.count(expected) != 1:
            raise RuntimeError(f"Expected exactly one {expected} in ZIP, found {members.count(expected)}")
        packed_source = z.read(expected)
        if packed_source != source_bytes:
            raise RuntimeError(
                f"ZIP Lua is not generated Lua: source={hashlib.sha256(source_bytes).hexdigest()}; "
                f"package={hashlib.sha256(packed_source).hexdigest()}"
            )
        checked = 0
        for member in members:
            if member.endswith(".lua"):
                check_lua(z.read(member), f"ZIP:{member}")
                checked += 1
        needed = {
            "plugins/CheekyFoveatedDLSS.dll",
            "plugins/CheekyFoveatedDLSS/CheekyFoveatedDLSSRuntime.dll",
            "OpenXR/CheekyOpenXRSetup.exe",
        }
        missing = needed - set(members)
        if missing:
            raise RuntimeError(f"Missing payload entries: {sorted(missing)}")
    if not checked:
        raise RuntimeError("No Lua scripts inside release")
    print(f"PASS packaged Lua release gate: {checked} scripts compiled, source ZIP bytes identical")

if __name__ == "__main__":
    main()
