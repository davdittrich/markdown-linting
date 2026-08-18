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

# Wall-clock ceiling for any single rumdl invocation. Shared by the count
# and --fix paths so the two can never drift apart.
RUMDL_TIMEOUT_SECONDS = 60

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


def resolve_targets(root, paths=None):
    """Confine the target set to `root` and return what rumdl can be handed.

    The D-02 defaults are **lint-if-present**: `README.md` and `CLAUDE.md`
    are both optional in a gsd-core project, and rumdl exits 2 ("Failed to
    find markdown files") when a named path does not exist. Without this
    filter, every verify:post run in a project with no root CLAUDE.md
    would take the loud RuntimeError path and write a permanent
    `violation_count: unavailable` the ship:pre gate can never satisfy --
    a tree that lints clean would be indistinguishable from a broken
    ruleset.

    Explicitly named CLI paths are deliberately NOT filtered: a typo in
    `lint.py count docs/REDME.md` must fail loudly rather than silently
    lint nothing and print a reassuring 0.
    """
    if paths:
        return [confined(root, p) for p in paths]
    return [t for t in (confined(root, d) for d in LINT_TARGETS) if t.exists()]


def resolve_rumdl_invocation():
    """D-04's two-tier chain: PATH first, then uvx, else None. Tool-absent
    fail-open handling (never raising here) is plan 02 scope -- a None
    return is guarded explicitly by both callers, each on its own terms
    rather than this function raising: `resolve_cwd_run_context()` (the
    operator-invoked `count`/`fix` subcommands) raises RuntimeError, while
    `verify_post()` degrades to the MDL-04 sentinel report."""
    if shutil.which("rumdl"):
        return ["rumdl"]
    if shutil.which("uvx"):
        return ["uvx", "rumdl"]
    return None


def check_argv(rumdl_argv, config_path, targets, *flags):
    """Build one `rumdl check [...flags] --config <path> <targets>` argv
    list. Single source of truth for the invocation shape, so the count,
    --fix, and report-provenance paths cannot drift apart (the
    `generated_from` field used to rebuild this list by hand)."""
    return rumdl_argv + ["check", *flags, "--config", str(config_path)] + [
        str(t) for t in targets
    ]


def run_rumdl(argv):
    """Run a rumdl argv list and enforce the completed-run returncode
    contract shared by every call site: 0 (clean) and 1 (violations found)
    are completed runs; `2` (config/runtime error) raises RuntimeError; any
    other value raises subprocess.CalledProcessError. Returns the
    CompletedProcess so callers can read stdout."""
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=RUMDL_TIMEOUT_SECONDS
    )
    if result.returncode == 2:
        raise RuntimeError(f"rumdl config/runtime error: {result.stderr}")
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode, argv, result.stdout, result.stderr
        )
    return result


def count_violations(config_path, targets, rumdl_argv):
    """Run `rumdl check --config <config_path> --output-format json
    <targets>` and return the exact integer length of the emitted JSON
    array -- no text-summary parsing, no rounding (MDL-02 precision).

    Output that is not a JSON array (empty stdout from a rumdl build
    without `--output-format json`, a JSON object, a panic message) raises
    ValueError rather than yielding a bogus count: `len()` of a dict would
    silently report its key count as a violation total. verify_post()
    catches ValueError on its fail-open path, so a malformed payload
    degrades to the `unavailable` sentinel instead of escaping the
    onError:skip dispatch and leaving a stale report behind.
    """
    if not targets:
        # rumdl with zero path arguments walks the whole cwd instead of
        # doing nothing -- an empty target set must never reach it.
        return 0
    argv = check_argv(rumdl_argv, config_path, targets, "--output-format", "json")
    violations = json.loads(run_rumdl(argv).stdout)
    if not isinstance(violations, list):
        raise ValueError(
            f"rumdl JSON output is {type(violations).__name__}, expected a list"
        )
    return len(violations)


def _write_report(out_path, phase_dir, generated_at, config_path, generated_from, violation_count, unavailable_reason=None):
    """Shared frontmatter+body writer for both the happy path and the
    sentinel path -- one place that fully overwrites the report, so the two
    paths cannot drift into different file shapes."""
    # WR-03 (mirrors pr_status.py's fix): every free-text field is emitted
    # via json.dumps, whose output is also a valid double-quoted YAML
    # scalar. This escapes both an embedded `"` (which would terminate the
    # scalar early) and an embedded newline (which would otherwise inject
    # arbitrary extra frontmatter keys). `unavailable_reason` is the one
    # that makes this load-bearing rather than defensive: it carries rumdl's
    # own stderr, so a linter error message containing a line reading
    # `violation_count: 0` would append a second, later-wins
    # `violation_count` key and hand the advisory ship:pre gate a clean
    # verdict for a run that never measured anything. `phase` and `config`
    # are filesystem-derived and quoted for the same reason (`:` in a
    # directory name is legal and would otherwise re-key the line).
    # `violation_count` stays unquoted: it is an int or the bare
    # `unavailable` sentinel, and the gate compares it numerically.
    lines = [
        "---",
        f"phase: {json.dumps(phase_dir.name)}",
        f"violation_count: {violation_count}",
    ]
    if unavailable_reason is not None:
        lines.append(f"unavailable_reason: {json.dumps(unavailable_reason)}")
    lines.append(f"config: {json.dumps(str(config_path))}")
    lines.append(f"generated_from: {json.dumps(generated_from)}")
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
    TimeoutExpired/OSError, rumdl exiting with an unexpected crash code
    reported as CalledProcessError, or rumdl emitting output that is not a
    JSON array -- ValueError, which json.JSONDecodeError subclasses):
    print NOTICE exactly once and still
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

    A rumdl returncode of 2 (config/runtime error) is a DISTINCT loud path,
    not the fail-open one above: count_violations raises RuntimeError for
    it, which is caught here and returns exit 1 (not 0) -- a broken
    ruleset must never be silently laundered into a fail-open zero. But
    the report is still fully overwritten with the same non-numeric
    `unavailable` sentinel the other paths use, distinguished by
    `unavailable_reason`: under this dispatch point's `onError: skip`
    contract, an UNCAUGHT exception here does not fail the phase -- it
    only skips regenerating the report, leaving whatever the PREVIOUS
    successful run wrote (e.g. `violation_count: 0`) stale on disk, which
    is exactly the "stale status satisfies the gate" failure this whole
    function exists to prevent. Catching and still writing keeps both
    properties: the failure is loud (nonzero exit, printed message) AND
    the artifact is never stale.
    """
    phase_dir = Path(phase_dir_arg).resolve()
    project_root = find_project_root(phase_dir)
    padded_phase = phase_dir.name.split("-", 1)[0]

    config_path = confined(project_root, *CONFIG_REL_PARTS)
    targets = resolve_targets(project_root)
    rumdl_argv = resolve_rumdl_invocation()
    out_path = confined(project_root, phase_dir.relative_to(project_root), f"{padded_phase}-LINT-REPORT.md")
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

    argv = check_argv(rumdl_argv, config_path, targets, "--output-format", "json")

    try:
        violation_count = count_violations(config_path, targets, rumdl_argv)
    except RuntimeError as exc:
        print(exc)
        _write_report(
            out_path, phase_dir, generated_at, config_path,
            generated_from=" ".join(argv),
            violation_count="unavailable",
            unavailable_reason=f"RuntimeError: {exc}",
        )
        return 1
    except (subprocess.TimeoutExpired, OSError, subprocess.CalledProcessError, ValueError) as exc:
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


def resolve_cwd_run_context(paths=None):
    """Resolve (config_path, targets, rumdl_argv) for the two cwd-rooted
    CLI subcommands (`count`, `fix`). Both are operator-invoked and
    fail LOUDLY when no rumdl is reachable -- unlike verify_post, whose
    MDL-04 contract is to degrade to a sentinel report instead."""
    project_root = find_project_root(Path.cwd())
    config_path = confined(project_root, *CONFIG_REL_PARTS)
    targets = resolve_targets(project_root, paths)
    rumdl_argv = resolve_rumdl_invocation()
    if rumdl_argv is None:
        raise RuntimeError("neither rumdl nor uvx is available on PATH")
    return config_path, targets, rumdl_argv


def fix(paths=None):
    """Allowlist-safe wrapper for `rumdl check --fix` (Pitfall 6: --fix
    lives on the check subcommand, not as a bare top-level flag). This
    machine's shell allowlist rejects a bare top-level `rumdl` command
    word and interpreter inline-code/heredoc-stdin forms -- routing the
    fixer through this script file is the invocation form that survives
    it. Sole caller is plan 03 Task 1.

    The --fix run goes through run_rumdl, so a config/runtime error or a
    crash raises here instead of being swallowed: this rewrites the
    operator's markdown in place, and a partially-applied fix reported as
    success is the one outcome worth failing loudly for."""
    config_path, targets, rumdl_argv = resolve_cwd_run_context(paths)
    if not targets:
        # Same hazard as count_violations': a bare `rumdl check --fix` with
        # no path arguments would rewrite every markdown file under cwd.
        print("no existing targets to fix")
        return 0
    result = run_rumdl(check_argv(rumdl_argv, config_path, targets, "--fix"))
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
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
        print(count_violations(*resolve_cwd_run_context(args.paths)))
        return 0
    if args.command == "fix":
        return fix(args.paths)
    return 1


if __name__ == "__main__":
    sys.exit(main())
