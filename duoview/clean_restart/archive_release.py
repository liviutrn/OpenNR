import argparse
import hashlib
import json
import re
import urllib.request
import zipfile
from pathlib import Path


def archive(lock, destination):
    destination.mkdir(parents=True, exist_ok=True)
    verified = []
    base = f"https://github.com/joeyhodge/UEVR/releases/download/{lock['release']}/"
    for asset in lock["official_assets"]:
        path = destination / asset["name"]
        request = urllib.request.Request(base + asset["name"], headers={"User-Agent": "DuoView-source-audit"})
        with urllib.request.urlopen(request, timeout=60) as response, path.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != asset["sha256"]:
            raise RuntimeError(f"Official asset hash mismatch: {asset['name']}")
        verified.append({"name": asset["name"], "sha256": digest, "bytes": path.stat().st_size})
    with zipfile.ZipFile(destination / "DIBRMONOUEVR.zip") as package:
        if package.testzip() is not None:
            raise RuntimeError("Official DIBR package has a corrupt entry")
        backend = package.read("UEVRBackend.dll")
        if hashlib.sha256(backend).hexdigest() != lock["official_assets"][1]["sha256"]:
            raise RuntimeError("Packaged DIBR DLL differs from the standalone official asset")
        hashes = sorted({value.decode("ascii") for value in re.findall(rb"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", backend)})
        for expected in (lock["backend"]["commit"], lock["backend"]["sdk_commit"]):
            if expected not in hashes:
                raise RuntimeError(f"Official DLL does not contain expected source identity: {expected}")
    with zipfile.ZipFile(destination / "UEVR.zip") as package:
        if package.testzip() is not None:
            raise RuntimeError("Official normal package has a corrupt entry")
        if hashlib.sha256(package.read("UEVRBackend.dll")).hexdigest() != lock["official_assets"][3]["sha256"]:
            raise RuntimeError("Packaged normal DLL differs from the standalone official asset")
    report = {"assets": verified, "dibr_embedded_commit_strings": hashes, "headset_test": "User reported smooth DIBR; no new runtime test performed"}
    (destination / "verified-release.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("lock", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    archive(json.loads(args.lock.read_text(encoding="utf-8")), args.destination)
