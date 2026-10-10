"""Tests for hooks/capability-auto-install.sh, driven as a subprocess with a
stub gsd-tools so nothing is ever installed. Stdlib unittest only."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks" / "capability-auto-install.sh"
CAP = "markdown-linting"
MARK_SCRIPT = '#!/bin/sh\necho %s >> "$GSD_TEST_LOG"\n'
ARGS_SCRIPT = '#!/bin/sh\necho "$@" >> "$GSD_TEST_LOG"\n'
BUNDLE_FILES = ["capability.json", "config", "scripts", "skills"]


class HookCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.plugin = self.tmp / "plugin"
        self.plugin.mkdir()
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        # PATH holds only system dirs plus a node shim, so a developer's
        # real gsd-tools can never leak into a test.
        (self.bin / "node").symlink_to(shutil.which("node"))
        self.log = self.tmp / "log"

    def stub_on_path(self, marker="path", script=None):
        stub = self.bin / "gsd-tools"
        stub.write_text(script or MARK_SCRIPT % marker)
        stub.chmod(0o755)

    def populate_bundle(self):
        (self.plugin / "capability.json").write_text("{}")
        for d in ("config", "scripts", "skills"):
            (self.plugin / d).mkdir(exist_ok=True)
            (self.plugin / d / "f").write_text(d)

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
        self.populate_bundle()
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
        shutil.rmtree(self.plugin)
        self.plugin.mkdir()
        self.populate_bundle()
        shutil.rmtree(self.home, ignore_errors=True)
        populate(self.plugin / "scripts")
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
            def populate(b):
                (b / "a").write_text("A")
                (b / "b").write_text("B")
                (b / "link").symlink_to(target)
            return populate

        self.assertNotEqual(self.hash_of(to("a")), self.hash_of(to("b")))

    def test_symlinked_file_content_change_changes_hash(self):
        # Staging uses cp -RL, so the installed copy tracks the target's content.
        def with_target_text(text):
            def populate(b):
                outside = b.parent / "outside.txt"
                outside.write_text(text)
                (b / "link").symlink_to(outside)
            return populate

        self.assertNotEqual(self.hash_of(with_target_text("A")), self.hash_of(with_target_text("B")))

    def test_edit_outside_bundle_files_keeps_hash_and_skips_install(self):
        self.populate_bundle()
        self.run_hook()
        before = self.state_hash()
        for extra in ("README.md", "tests/x", "hooks/x", "scripts/__pycache__/lint.pyc"):
            path = self.plugin / extra
            path.parent.mkdir(exist_ok=True)
            path.write_text("edit")
        self.log.unlink()
        self.run_hook()
        self.assertEqual(self.state_hash(), before)
        self.assertEqual(self.logged(), [])

    def test_edit_to_bundle_file_reinstalls(self):
        self.populate_bundle()
        self.run_hook()
        (self.plugin / "skills" / "f").write_text("changed")
        self.log.unlink()
        self.run_hook()
        self.assertEqual(self.logged(), ["path"])


class TestStaging(HookCase):
    def setUp(self):
        super().setUp()
        self.stub_on_path(script=ARGS_SCRIPT)
        self.stage = self.home / ".gsd" / f"capability-bundle-{CAP}"

    def test_installs_staged_bundle_files_only(self):
        self.populate_bundle()
        for extra in ("README.md", "LICENSE", "tests/t.py", "hooks/h.sh", ".git/HEAD",
                      "scripts/__pycache__/lint.pyc"):
            path = self.plugin / extra
            path.parent.mkdir(exist_ok=True)
            path.write_text("x")
        self.run_hook()
        self.assertEqual(sorted(p.name for p in self.stage.iterdir()), sorted(BUNDLE_FILES))
        self.assertFalse((self.stage / "scripts" / "__pycache__").exists())
        self.assertEqual((self.stage / "skills" / "f").read_text(), "skills")
        self.assertEqual(
            self.logged(),
            f"capability install {self.stage} --scope global --yes".split(),
        )

    def test_restage_drops_removed_files(self):
        self.populate_bundle()
        (self.plugin / "scripts" / "old").write_text("x")
        self.run_hook()
        (self.plugin / "scripts" / "old").unlink()
        self.run_hook()
        self.assertFalse((self.stage / "scripts" / "old").exists())

    def test_no_root_manifest_exits_silently(self):
        result = self.run_hook()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(self.logged(), [])

    def test_staging_failure_reports_and_does_not_install(self):
        self.populate_bundle()
        shutil.rmtree(self.plugin / "skills")
        result = self.run_hook()
        self.assertIn("staging failed", result.stderr)
        self.assertEqual(self.logged(), [])
        self.assertFalse((self.home / ".gsd" / f"capability-auto-install-{CAP}.hash").exists())


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
