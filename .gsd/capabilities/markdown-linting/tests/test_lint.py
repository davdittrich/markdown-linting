"""Tests for .gsd/capabilities/markdown-linting/scripts/lint.py.

Stdlib unittest only (N5, review finding R-01): the suite must pass under
`python3 -m unittest discover` with no third-party test runner installed.
lint.py's parent directory is put on sys.path at module import so no
package __init__.py and no install step is needed -- mirrors
beads/tests/test_sync.py's own sys.path.insert technique.
"""
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import lint  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
REAL_CONFIG_PATH = Path(lint.__file__).resolve().parent.parent / "config" / ".rumdl.toml"
CURATED_RULES = {"MD001", "MD003", "MD009", "MD012", "MD022", "MD024", "MD040"}


def _rumdl_available():
    return lint.resolve_rumdl_invocation() is not None


def _write_phase_dir(tmp_path, phase_dir_name="13-markdown-linting-capability-dogfood"):
    """Lay out a minimal .planning/phases/<phase_dir_name>/ tree under
    tmp_path so find_project_root resolves -- mirrors test_sync.py's
    _write_plan_workspace, scoped to just what verify_post needs."""
    phase_dir = tmp_path / ".planning" / "phases" / phase_dir_name
    phase_dir.mkdir(parents=True)
    return phase_dir


def _make_fake_project_root(tmp_path):
    """Build a scratch project root: a .planning/ ancestor (for
    find_project_root) plus a copy of the shipped .rumdl.toml at the same
    CONFIG_REL_PARTS location verify_post/count_violations resolve --
    lets a test point a real rumdl subprocess at checked-in fixtures
    without ever touching the live .planning/ tree (the corpus there
    changes every session, per 13-RESEARCH.md Pitfall 2)."""
    phase_dir = _write_phase_dir(tmp_path)
    config_dir = tmp_path.joinpath(*lint.CONFIG_REL_PARTS[:-1])
    config_dir.mkdir(parents=True)
    (config_dir / lint.CONFIG_REL_PARTS[-1]).write_text(
        REAL_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return phase_dir


class TestFailOpen(unittest.TestCase):
    """MDL-04/Pitfall 5: rumdl+uvx both absent, or a live rumdl call raising
    TimeoutExpired/OSError, degrades to exit 0, exactly one NOTICE, and a
    sentinel report that overwrites any prior content -- deliberately
    unlike beads/scripts/sync.py's TestFailOpen, which asserts the
    analogous artifact (BEADS.md) does NOT exist on the fail-open path;
    here the report file must exist, since Pitfall 5's whole point is that
    the report is never left stale/untouched."""

    def test_tool_absent_fail_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            phase_dir = _write_phase_dir(Path(tmp))
            captured = io.StringIO()
            with mock.patch("shutil.which", return_value=None):
                with mock.patch(
                    "subprocess.run",
                    side_effect=AssertionError("rumdl/uvx must not be invoked when absent"),
                ):
                    with mock.patch("sys.stdout", captured):
                        exit_code = lint.verify_post(str(phase_dir))

            self.assertEqual(exit_code, 0)
            self.assertEqual(captured.getvalue().count(lint.NOTICE), 1)
            report_path = phase_dir / "13-LINT-REPORT.md"
            self.assertTrue(report_path.exists())
            text = report_path.read_text(encoding="utf-8")
            self.assertIn("violation_count: unavailable", text)
            self.assertNotIn("violation_count: 0\n", text)

    def test_tool_absent_overwrites_stale_zero_report_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            phase_dir = _write_phase_dir(Path(tmp))
            report_path = phase_dir / "13-LINT-REPORT.md"
            report_path.write_text(
                "---\nviolation_count: 0\n---\n\nstale\n", encoding="utf-8"
            )
            with mock.patch("shutil.which", return_value=None):
                with mock.patch(
                    "subprocess.run",
                    side_effect=AssertionError("rumdl/uvx must not be invoked when absent"),
                ):
                    lint.verify_post(str(phase_dir))

            text = report_path.read_text(encoding="utf-8")
            self.assertIn("unavailable", text)
            self.assertNotIn("violation_count: 0\n", text)

    def test_rumdl_timeout_fail_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            phase_dir = _write_phase_dir(Path(tmp))
            captured = io.StringIO()
            with mock.patch(
                "shutil.which",
                side_effect=lambda name: "/usr/bin/rumdl" if name == "rumdl" else None,
            ):
                with mock.patch(
                    "subprocess.run",
                    side_effect=subprocess.TimeoutExpired(cmd=["rumdl"], timeout=60),
                ):
                    with mock.patch("sys.stdout", captured):
                        exit_code = lint.verify_post(str(phase_dir))

            self.assertEqual(exit_code, 0)
            self.assertEqual(captured.getvalue().count(lint.NOTICE), 1)
            text = (phase_dir / "13-LINT-REPORT.md").read_text(encoding="utf-8")
            self.assertIn("violation_count: unavailable", text)

    def test_rumdl_oserror_fail_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            phase_dir = _write_phase_dir(Path(tmp))
            captured = io.StringIO()
            with mock.patch(
                "shutil.which",
                side_effect=lambda name: "/usr/bin/rumdl" if name == "rumdl" else None,
            ):
                with mock.patch("subprocess.run", side_effect=OSError("boom")):
                    with mock.patch("sys.stdout", captured):
                        exit_code = lint.verify_post(str(phase_dir))

            self.assertEqual(exit_code, 0)
            self.assertEqual(captured.getvalue().count(lint.NOTICE), 1)
            text = (phase_dir / "13-LINT-REPORT.md").read_text(encoding="utf-8")
            self.assertIn("violation_count: unavailable", text)

    def test_config_error_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            phase_dir = _write_phase_dir(Path(tmp))
            completed = subprocess.CompletedProcess(
                args=["rumdl"], returncode=2, stdout="", stderr="bad config"
            )
            with mock.patch(
                "shutil.which",
                side_effect=lambda name: "/usr/bin/rumdl" if name == "rumdl" else None,
            ):
                with mock.patch("subprocess.run", return_value=completed):
                    with self.assertRaises(RuntimeError):
                        lint.verify_post(str(phase_dir))

            report_path = phase_dir / "13-LINT-REPORT.md"
            self.assertFalse(report_path.exists())

    def test_unexpected_exit_code_fail_open_overwrites_stale_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            phase_dir = _write_phase_dir(Path(tmp))
            report_path = phase_dir / "13-LINT-REPORT.md"
            report_path.write_text(
                "---\nviolation_count: 0\n---\n\nstale\n", encoding="utf-8"
            )
            before_text = report_path.read_text(encoding="utf-8")
            captured = io.StringIO()
            completed = subprocess.CompletedProcess(
                args=["rumdl"], returncode=101, stdout="",
                stderr="thread 'main' panicked at rumdl/src/main.rs:1:1",
            )
            with mock.patch(
                "shutil.which",
                side_effect=lambda name: "/usr/bin/rumdl" if name == "rumdl" else None,
            ):
                with mock.patch("subprocess.run", return_value=completed):
                    with mock.patch("sys.stdout", captured):
                        exit_code = lint.verify_post(str(phase_dir))

            self.assertEqual(exit_code, 0)
            self.assertEqual(captured.getvalue().count(lint.NOTICE), 1)
            text = report_path.read_text(encoding="utf-8")
            self.assertNotEqual(text, before_text)
            self.assertIn("violation_count: unavailable", text)
            self.assertNotIn("violation_count: 0\n", text)
            self.assertIn("CalledProcessError", text)


class TestCuratedRuleset(unittest.TestCase):
    """MDL-01: the checked-in fixtures pin the curated 7-rule allowlist's
    actual behavior against real rumdl -- never against the live
    .planning/ tree, which changes every session (13-RESEARCH.md
    Pitfall 2). Skipped when neither rumdl nor uvx is on PATH, so the
    suite stays green on a machine with no rumdl installed."""

    @unittest.skipUnless(_rumdl_available(), "neither rumdl nor uvx is available")
    def test_curated_config_zero_violations(self):
        rumdl_argv = lint.resolve_rumdl_invocation()
        count = lint.count_violations(
            REAL_CONFIG_PATH, [FIXTURES_DIR / "clean.md"], rumdl_argv
        )
        self.assertEqual(count, 0)

    @unittest.skipUnless(_rumdl_available(), "neither rumdl nor uvx is available")
    def test_dirty_fixture_known_count(self):
        rumdl_argv = lint.resolve_rumdl_invocation()
        config_path = REAL_CONFIG_PATH
        argv = rumdl_argv + [
            "check", "--config", str(config_path), "--output-format", "json",
            str(FIXTURES_DIR / "dirty.md"),
        ]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        violations = json.loads(result.stdout)
        self.assertEqual(len(violations), 5)
        for v in violations:
            self.assertIn(v["rule"], CURATED_RULES)


class TestReportMatchesHandRun(unittest.TestCase):
    """MDL-02: verify_post()'s written violation_count equals a hand-run
    count_violations() call over the identical target set and config."""

    @unittest.skipUnless(_rumdl_available(), "neither rumdl nor uvx is available")
    def test_report_matches_handrun_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            phase_dir = _make_fake_project_root(tmp_path)
            target = tmp_path / "scratch-target.md"
            target.write_text(
                (FIXTURES_DIR / "dirty.md").read_text(encoding="utf-8"), encoding="utf-8"
            )

            with mock.patch.object(lint, "LINT_TARGETS", ("scratch-target.md",)):
                exit_code = lint.verify_post(str(phase_dir))
                self.assertEqual(exit_code, 0)

                config_path = tmp_path.joinpath(*lint.CONFIG_REL_PARTS)
                rumdl_argv = lint.resolve_rumdl_invocation()
                handrun_count = lint.count_violations(config_path, [target], rumdl_argv)

            report_text = (phase_dir / "13-LINT-REPORT.md").read_text(encoding="utf-8")
            match = re.search(r"violation_count: (\d+)", report_text)
            self.assertIsNotNone(match, report_text)
            self.assertEqual(int(match.group(1)), handrun_count)


class TestToolResolution(unittest.TestCase):
    """D-04 tier ordering: uvx is used only when rumdl is absent from
    PATH, and the actual argv invoked reflects that. Also covers that
    every CLI subcommand guards the both-absent case rather than
    crashing -- this class is the D-04 tier ordering plus its absent
    tier, and the test below is the absent tier for `count`."""

    def test_uvx_fallback_used_when_rumdl_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            phase_dir = _write_phase_dir(tmp_path)
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
            with mock.patch(
                "shutil.which",
                side_effect=lambda name: None if name == "rumdl" else "/usr/bin/uvx",
            ):
                with mock.patch("subprocess.run", return_value=completed) as mock_run:
                    exit_code = lint.verify_post(str(phase_dir))

            self.assertEqual(exit_code, 0)
            self.assertGreaterEqual(mock_run.call_count, 1)
            argv = mock_run.call_args_list[0].args[0]
            self.assertEqual(argv[:2], ["uvx", "rumdl"])

    def test_count_cli_tool_absent_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_fake_project_root(tmp_path)
            with mock.patch.object(lint.Path, "cwd", return_value=tmp_path):
                with mock.patch("shutil.which", return_value=None):
                    with mock.patch(
                        "subprocess.run",
                        side_effect=AssertionError("rumdl/uvx must not be invoked when absent"),
                    ):
                        with self.assertRaises(RuntimeError) as ctx:
                            lint.main(["count"])

            self.assertIn(
                "neither rumdl nor uvx is available on PATH", str(ctx.exception)
            )


class TestEmptyTargetSet(unittest.TestCase):
    """Edge case: a target set matching zero markdown files still yields
    violation_count: 0 and exit 0 -- not an error path."""

    @unittest.skipUnless(_rumdl_available(), "neither rumdl nor uvx is available")
    def test_empty_target_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            phase_dir = _make_fake_project_root(tmp_path)
            empty_dir = tmp_path / "no-markdown-here"
            empty_dir.mkdir()

            with mock.patch.object(lint, "LINT_TARGETS", ("no-markdown-here",)):
                exit_code = lint.verify_post(str(phase_dir))

            self.assertEqual(exit_code, 0)
            report_text = (phase_dir / "13-LINT-REPORT.md").read_text(encoding="utf-8")
            self.assertIn("violation_count: 0\n", report_text)


if __name__ == "__main__":
    unittest.main()
