from __future__ import annotations

import unittest
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apply_backend_patch import PatchError, transform_source
import verify_backend_patch


class BackendPatchTests(unittest.TestCase):
    def test_adds_control_include_and_replaces_only_mono_callback(self):
        source = (
            '#include "MonoD3D12.hpp"\n'
            "other source\n"
            "                    if (vr->is_using_mono()) {\n"
            "                        baseline();\n"
            "                    } else if (use_native_array_submit) {\n"
            "                        keep_native();\n"
        )
        transformed = transform_source(source, "if (vr->is_using_mono()) {\nreplacement();\n} else if (use_native_array_submit) {\n")
        self.assertEqual(transformed.count('#include "StableSourceMaskD3D12.hpp"'), 1)
        self.assertIn("replacement();", transformed)
        self.assertNotIn("baseline();", transformed)
        self.assertIn("keep_native();", transformed)

    def test_preserves_exact_prefix_suffix_and_disabled_mono_path(self):
        source = (
            '#include "MonoD3D12.hpp"\n'
            "const int prefix_marker = 1;\n"
            "                    if (vr->is_using_mono()) {\n"
            "                        baseline();\n"
            "                    } else if (use_native_array_submit) {\n"
            "                        suffix_marker();\n"
        )
        start = source.index("                    if (vr->is_using_mono()) {\n")
        end = source.index("                    } else if (use_native_array_submit) {")
        include_end = source.index('#include "MonoD3D12.hpp"\n') + len('#include "MonoD3D12.hpp"\n')
        expected_prefix = (source[:include_end] + '#include "StableSourceMaskD3D12.hpp"\n' +
                           source[include_end:start])
        expected_suffix = source[end:]
        template = (Path(__file__).resolve().parents[1] / "backend/MonoControlBlock.inl").read_text()
        transformed = transform_source(source, template)
        self.assertTrue(transformed.startswith(expected_prefix))
        self.assertTrue(transformed.endswith(expected_suffix))
        self.assertIn("control_mode == uevr::duoview_restart::dx12::Mode::disabled", transformed)
        self.assertIn("scene_source_state, D3D12_RESOURCE_STATE_RENDER_TARGET);", transformed)
        self.assertIn("set_mono_status(\"Waiting: Mono scene/device/format/extent or GPU copy validation failed\")", transformed)

    def test_rejects_ambiguous_callback_anchor(self):
        source = (
            '#include "MonoD3D12.hpp"\n'
            "                    if (vr->is_using_mono()) {\n"
            "                    } else if (use_native_array_submit) {\n"
            "                    if (vr->is_using_mono()) {\n"
        )
        with self.assertRaises(PatchError):
            transform_source(source, "replacement\n")

    def test_rejects_already_patched_include(self):
        source = (
            '#include "MonoD3D12.hpp"\n'
            '#include "StableSourceMaskD3D12.hpp"\n'
            "                    if (vr->is_using_mono()) {\n"
            "                    } else if (use_native_array_submit) {\n"
        )
        with self.assertRaises(PatchError):
            transform_source(source, "replacement\n")

    def test_patch_verifier_handles_real_git_status_and_rejects_extra_change(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "backend"
            repo.mkdir()
            manifest = Path(directory) / "manifest.json"
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            tracked = repo / "src/mods/vr/D3D12Component.cpp"
            tracked.parent.mkdir(parents=True)
            tracked.write_text("original\n", encoding="utf-8")
            unrelated = repo / "keep.txt"
            unrelated.write_text("keep\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "base"], check=True, capture_output=True)
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True).stdout.strip()
            tracked.write_text("patched\n", encoding="utf-8")
            first = repo / "src/mods/vr/DuoViewRestartDiagnostics.hpp"
            second = repo / "src/mods/vr/StableSourceMaskD3D12.hpp"
            first.parent.mkdir(parents=True, exist_ok=True)
            first.write_text("header one\n", encoding="utf-8")
            second.write_text("header two\n", encoding="utf-8")
            files = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (tracked, first, second)}
            manifest.write_text(json.dumps({"backend_commit": head, "files": files}), encoding="utf-8")
            original_expected = verify_backend_patch.BACKEND_COMMIT
            verify_backend_patch.BACKEND_COMMIT = head
            try:
                verify_backend_patch.verify(repo, manifest)
                unrelated.write_text("unexpected\n", encoding="utf-8")
                with self.assertRaises(PatchError):
                    verify_backend_patch.verify(repo, manifest)
            finally:
                verify_backend_patch.BACKEND_COMMIT = original_expected


if __name__ == "__main__":
    unittest.main()
