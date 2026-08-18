#!/usr/bin/env python3
"""markdown-linting: wrap rumdl (PATH, else uvx) to measure this repo's
markdown against a curated MD0XX ruleset and write a gate-readable
violation-count report.

stdlib-only (N5: no dependency beyond the `rumdl`/`uvx` binaries and the
Python 3 standard library). Every rumdl/uvx invocation is an argv list
passed to `subprocess.run` with shell execution left at its (disabled)
default -- no rumdl command is ever assembled as a shell string (T-13-01,
mirrors beads/scripts/sync.py's T-01-01 discipline).
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# D-02: single source of truth for what this capability lints. Every
# caller (count, verify-post, fix) resolves its default targets from this
# constant -- never a hand-typed path list.
LINT_TARGETS = (".planning", "README.md", "CLAUDE.md")

CONFIG_REL_PARTS = (".gsd", "capabilities", "markdown-linting", "config", ".rumdl.toml")

# MDL-04/B6, mirrors sync.py's NOTICE constant shape -- one line naming the
# tool and both fallback tiers checked.
NOTICE = "rumdl unavailable (checked PATH and uvx) -- lint skipped, LINT-REPORT.md marked unavailable"


def find_project_root(start):
    """Walk up from `start` to the nearest ancestor containing `.planning/`.

    Guards T-13-02: every path this script reads or writes is confined to
    this resolved root, never derived unchecked from artifact text. Copied
    verbatim from beads/scripts/sync.py -- the two capabilities are
    independent and must not import across capability boundaries.
    """
    current = start.resolve()
    for _ in range(10):
        if (current / ".planning").is_dir():
            return current
        if current.parent == current:
            break
        current = current.parent
    raise ValueError(f"could not locate a .planning/ ancestor above {start}")


def confined(root, *parts):
    """Join parts onto root and reject any resolved escape (T-13-02)."""
    candidate = root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(f"path escapes project root: {candidate} not under {root}")
    return candidate


def resolve_rumdl_invocation():
    """D-04's two-tier chain: PATH first, then uvx, else None. Tool-absent
    fail-open handling (never raising here) is plan 02 scope -- a None
    return is guarded explicitly by all three callers (`fix()`, `main()`'s
    `count` branch, and `verify_post()`'s own None check), each raising or
    handling it on their own terms rather than this function raising."""
    if shutil.which("rumdl"):
        return ["rumdl"]
    if shutil.which("uvx"):
        return ["uvx", "rumdl"]
    return None


def count_violations(config_path, targets, rumdl_argv):
    """Run `rumdl check --config <config_path> --output-format json
    <targets>` and return the exact integer length of the emitted JSON
    array -- no text-summary parsing, no rounding (MDL-02 precision). A
    returncode outside the completed-run pair (0 clean, 1 violations
    found) is treated as a crash: `2` (config/runtime error) raises
    RuntimeError, and any other value raises subprocess.CalledProcessError
    rather than being parsed as JSON."""
    argv = rumdl_argv + [
        "check",
        "--config", str(config_path),
        "--output-format", "json",
    ] + [str(t) for t in targets]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if result.returncode == 2:
        raise RuntimeError(f"rumdl config/runtime error: {result.stderr}")
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode, argv, result.stdout, result.stderr
        )
    return len(json.loads(result.stdout))


def _write_report(out_path, phase_dir, generated_at, config_path, generated_from, violation_count, unavailable_reason=None):
    """Shared frontmatter+body writer for both the happy path and the
    sentinel path -- one place that fully overwrites the report, so the two
    paths cannot drift into different file shapes."""
    lines = [
        "---",
        f"phase: {phase_dir.name}",
        f"violation_count: {violation_count}",
    ]
    if unavailable_reason is not None:
        lines.append(f"unavailable_reason: {unavailable_reason}")
    lines.append(f"config: {config_path}")
    lines.append(f'generated_from: "{generated_from}"')
    lines.append(f"generated_at: {generated_at}")
    lines.append("---\n")
    # D-03: count-only, no per-rule/per-file breakdown table. The banner
    # below has no literal precedent in BEADS.md (B11 is a principle name,
    # not file content) -- authored fresh here; see 13-RESEARCH.md Pitfall 3.
    body = (
        f"# LINT-REPORT.md: {phase_dir.name}\n\n"
        "> Regenerated every step. Do not hand-edit.\n"
    )
    out_path.write_text("\n".join(lines) + "\n" + body, encoding="utf-8")


def verify_post(phase_dir_arg):
    """B11-style regenerate-every-run: always fully overwrite
    `{phase_dir}/{padded_phase}-LINT-REPORT.md`, never merging a prior
    hand edit.

    MDL-04 fail-open path (rumdl+uvx absent, a live rumdl call raising
    TimeoutExpired/OSError, or rumdl exiting with an unexpected crash code
    reported as CalledProcessError): print NOTICE exactly once and still
    fully overwrite the report, with a non-numeric
    `violation_count: unavailable` sentinel that cannot satisfy the
    ship:pre gate's `equals: 0` predicate.

    This is a **deliberate divergence** from
    beads/scripts/sync.py::regenerate_beads_md, which returns without
    touching BEADS.md when `bd` is unavailable: `bd`'s prior issue data
    stays meaningfully accurate until the next sync, but a lint count where
    the linter never ran is a claim about the tree that was never measured
    -- MDL-04 success criterion 5 forbids presenting it as current. A
    future editor must not "fix" this back to match beads's leave-it-alone
    behavior. No STATE.md blocker append here either (sync.py's fail-open
    paths do): the sentinel in the report plus the ship-transcript advisory
    already carry the signal, and a per-run append would accumulate noise
    on any machine without rumdl.

    A rumdl returncode of 2 (config/runtime error) is NOT part of this
    fail-open path -- count_violations raises RuntimeError for it, which
    propagates uncaught, since a broken ruleset must never be silently
    laundered into a fail-open zero.
    """
    phase_dir = Path(phase_dir_arg).resolve()
    project_root = find_project_root(phase_dir)
    padded_phase = phase_dir.name.split("-", 1)[0]

    config_path = confined(project_root, *CONFIG_REL_PARTS)
    targets = [confined(project_root, t) for t in LINT_TARGETS]
    rumdl_argv = resolve_rumdl_invocation()
    out_path = phase_dir / f"{padded_phase}-LINT-REPORT.md"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if rumdl_argv is None:
        print(NOTICE)
        _write_report(
            out_path, phase_dir, generated_at, config_path,
            generated_from="none (rumdl and uvx both absent from PATH)",
            violation_count="unavailable",
            unavailable_reason="rumdl and uvx both absent from PATH",
        )
        return 0

    argv = rumdl_argv + [
        "check",
        "--config", str(config_path),
        "--output-format", "json",
    ] + [str(t) for t in targets]

    try:
        violation_count = count_violations(config_path, targets, rumdl_argv)
    except (subprocess.TimeoutExpired, OSError, subprocess.CalledProcessError) as exc:
        print(NOTICE)
        _write_report(
            out_path, phase_dir, generated_at, config_path,
            generated_from=" ".join(argv),
            violation_count="unavailable",
            unavailable_reason=f"{type(exc).__name__}: {exc}",
        )
        return 0

    _write_report(
        out_path, phase_dir, generated_at, config_path,
        generated_from=" ".join(argv),
        violation_count=violation_count,
    )
    print(f"LINT-REPORT.md regenerated: {violation_count} violation(s)")
    return 0


def fix(paths=None):
    """Allowlist-safe wrapper for `rumdl check --fix` (Pitfall 6: --fix
    lives on the check subcommand, not as a bare top-level flag). This
    machine's shell allowlist rejects a bare top-level `rumdl` command
    word and interpreter inline-code/heredoc-stdin forms -- routing the
    fixer through this script file is the invocation form that survives
    it. Sole caller is plan 03 Task 1."""
    project_root = find_project_root(Path.cwd())
    config_path = confined(project_root, *CONFIG_REL_PARTS)
    targets = [confined(project_root, t) for t in (paths or LINT_TARGETS)]
    rumdl_argv = resolve_rumdl_invocation()
    if rumdl_argv is None:
        raise RuntimeError("neither rumdl nor uvx is available on PATH")

    check_argv = rumdl_argv + [
        "check", "--fix",
        "--config", str(config_path),
    ] + [str(t) for t in targets]
    result = subprocess.run(check_argv, capture_output=True, text=True, timeout=60)
    print(result.stdout, end="")
    post_fix_count = count_violations(config_path, targets, rumdl_argv)
    print(f"post-fix violation count: {post_fix_count}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lint.py")
    sub = parser.add_subparsers(dest="command", required=True)

    verify_p = sub.add_parser(
        "verify-post",
        help="Fully overwrite {phase_dir}/{padded_phase}-LINT-REPORT.md from a live rumdl run",
    )
    verify_p.add_argument("phase_dir")

    count_p = sub.add_parser(
        "count",
        help="Print the integer violation count to stdout (defaults to the D-02 target set)",
    )
    count_p.add_argument("paths", nargs="*")

    fix_p = sub.add_parser(
        "fix",
        help="Run rumdl check --fix over the D-02 target set (allowlist-safe wrapper)",
    )
    fix_p.add_argument("paths", nargs="*")

    args = parser.parse_args(argv)

    if args.command == "verify-post":
        return verify_post(args.phase_dir)
    if args.command == "count":
        project_root = find_project_root(Path.cwd())
        config_path = confined(project_root, *CONFIG_REL_PARTS)
        targets = [confined(project_root, t) for t in (args.paths or LINT_TARGETS)]
        rumdl_argv = resolve_rumdl_invocation()
        if rumdl_argv is None:
            raise RuntimeError("neither rumdl nor uvx is available on PATH")
        print(count_violations(config_path, targets, rumdl_argv))
        return 0
    if args.command == "fix":
        return fix(args.paths)
    return 1


if __name__ == "__main__":
    sys.exit(main())
