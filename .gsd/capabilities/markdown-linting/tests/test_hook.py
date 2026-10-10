"""Tests for hooks/capability-auto-install.sh, driven as a subprocess with a
stub gsd-tools so nothing is ever installed. Stdlib unittest only."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
HOOK = REPO / "hooks" / "capability-auto-install.sh"
CAP = "markdown-linting"
MARK_SCRIPT = '#!/bin/sh\necho %s >> "$GSD_TEST_LOG"\n'


class HookCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.plugin = self.tmp / "plugin"
        self.bundle = self.plugin / ".gsd" / "capabilities" / CAP
        self.bundle.mkdir(parents=True)
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        # PATH holds only system dirs plus a node shim, so a developer's
        # real gsd-tools can never leak into a test.
        (self.bin / "node").symlink_to(shutil.which("node"))
        self.log = self.tmp / "log"

    def stub_on_path(self, marker="path"):
        stub = self.bin / "gsd-tools"
        stub.write_text(MARK_SCRIPT % marker)
        stub.chmod(0o755)

    def write_cjs(self, root, marker):
        cjs = root / "gsd-core" / "bin" / "gsd-tools.cjs"
        cjs.parent.mkdir(parents=True)
        cjs.write_text(
            f"require('fs').appendFileSync(process.env.GSD_TEST_LOG, '{marker}\\n');\n"
        )

    def run_hook(self, cwd=None, **env_extra):
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.tmp / "nohome"),
            "GSD_HOME": str(self.home),
            "CLAUDE_PLUGIN_ROOT": str(self.plugin),
            "GSD_TEST_LOG": str(self.log),
            **env_extra,
        }
        return subprocess.run(
            ["bash", str(HOOK), CAP], cwd=cwd or self.tmp, env=env,
            capture_output=True, text=True,
        )

    def logged(self):
        return self.log.read_text().split() if self.log.exists() else []

    def state_hash(self):
        return (self.home / ".gsd" / f"capability-auto-install-{CAP}.hash").read_text()


class TestGsdToolsResolution(HookCase):
    def setUp(self):
        super().setUp()
        (self.bundle / "capability.json").write_text("{}")
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.write_cjs(self.repo, "repo")

    def test_path_wins_over_cwd_checkout(self):
        self.stub_on_path()
        self.run_hook(cwd=self.repo)
        self.assertEqual(self.logged(), ["path"])

    def test_cwd_checkout_is_never_used(self):
        # A stale checkout in whatever repo the session opened must not
        # perform a machine-wide install; the claude config dir is next.
        cfg = self.tmp / "cfg"
        self.write_cjs(cfg, "cfg")
        self.run_hook(cwd=self.repo, CLAUDE_CONFIG_DIR=str(cfg))
        self.assertEqual(self.logged(), ["cfg"])

    def test_no_resolver_reports_and_does_not_record_hash(self):
        result = self.run_hook(cwd=self.repo, CLAUDE_CONFIG_DIR=str(self.tmp / "none"))
        self.assertIn("gsd-tools not found", result.stderr)
        self.assertEqual(self.logged(), [])
        self.assertFalse((self.home / ".gsd").exists())


class TestBundleHash(HookCase):
    def setUp(self):
        super().setUp()
        self.stub_on_path()

    def hash_of(self, populate):
        shutil.rmtree(self.bundle)
        self.bundle.mkdir(parents=True)
        shutil.rmtree(self.home, ignore_errors=True)
        populate(self.bundle)
        self.run_hook()
        return self.state_hash()

    def test_moving_content_between_files_changes_hash(self):
        def one(b):
            (b / "a").write_text("AB")
            (b / "b").write_text("")

        def two(b):
            (b / "a").write_text("A")
            (b / "b").write_text("B")

        self.assertNotEqual(self.hash_of(one), self.hash_of(two))

    def test_symlink_target_change_changes_hash(self):
        def to(target):
            return lambda b: (b / "link").symlink_to(target)

        self.assertNotEqual(self.hash_of(to("x")), self.hash_of(to("y")))


class TestGitignore(unittest.TestCase):
    def test_tool_caches_are_ignored(self):
        # A scratch repo carrying only .gitignore, so the test also runs from
        # the installed plugin cache, which is not a git work tree.
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(REPO / ".gitignore", tmp)
            subprocess.run(["git", "init", "-q", tmp], check=True)
            for cache in (".pytest_cache/x", ".rumdl_cache/x"):
                with self.subTest(cache=cache):
                    result = subprocess.run(
                        ["git", "check-ignore", "-q", cache], cwd=tmp
                    )
                    self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
