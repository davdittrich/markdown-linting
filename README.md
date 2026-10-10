# markdown-linting

Wraps rumdl over .planning/, README.md, and CLAUDE.md; verify:post writes a gate-readable violation-count report, ship:pre re-measures and advises (never blocks).

## What it does

One lifecycle step and one gate:

- **`verify:post`** runs the bundled `lint.py verify-post <phase_dir>`, which fully overwrites
  `{phase_dir}/{padded_phase}-LINT-REPORT.md` on every invocation (regenerate-every-run, never
  merged with a prior hand edit). The report is **phase-scoped**, not a project-root
  `.planning/LINT-REPORT.md`.
- **`ship:pre`** runs `lint.py count` and is **advisory** (`blocking: false`): a nonzero count
  prints a warning, but the ship proceeds. It re-measures the tree rather than reading the
  report, so edits made after `verify:post` cannot pass on a stale count. It locates `lint.py`
  under `${CLAUDE_PROJECT_DIR}` first, then `${GSD_HOME:-$HOME}`, and `markdown-linting.ship_gate`
  toggles it.

The skill locates `lint.py` at `${CLAUDE_PROJECT_DIR}/.gsd/capabilities/markdown-linting/scripts/lint.py`,
then `${GSD_HOME:-$HOME}/.gsd/capabilities/markdown-linting/scripts/lint.py`, and stops with a
message when neither exists.

Two config keys, both overridable in a project's `.planning/config.json`:

| Key | Default | Effect |
|-----|---------|--------|
| `markdown-linting.enabled` | `true` | Master toggle. `false` skips the `verify:post` step entirely (no report is regenerated). |
| `markdown-linting.ship_gate` | `true` | Whether the advisory `ship:pre` gate is registered. `false` disables the gate but leaves `verify:post` running. |

Targets are `.planning/`, root `README.md`, and root `CLAUDE.md`. The two root files are
**linted if present** -- a project without a root `CLAUDE.md` gets a normal count over what it does
have, not an error.

The enabled rules live in `.gsd/capabilities/markdown-linting/config/.rumdl.toml` (allowlist by
omission: any rule not listed is off). MD013, MD033, and MD041 are off because agent-generated
long lines, `<details>` blocks, and frontmatter-led files would make them permanent violations.

## Requirements

- **`rumdl`**, resolved in this order:
  1. `rumdl` on `PATH` -- preferred; the operator controls install and version, and this
     capability never installs anything.
  2. `uvx rumdl` (no persistent install).
  3. Neither available -- one visible notice, exit 0, and `LINT-REPORT.md` rewritten with a
     `violation_count: unavailable` sentinel. Never a stale count presented as current.

  A rumdl that is present but fails (bad ruleset, crash, non-JSON output) writes the same
  `unavailable` sentinel with an `unavailable_reason`; a config/runtime error also exits `1`;
  timeouts, `OSError`, and non-JSON output exit `0` with a one-line cause. A
  broken ruleset is never laundered into a clean `0`.

  `rumdl` project: <https://github.com/rvben/rumdl>
- Python 3 (standard library only)
- gsd-core `>=1.6.0`

## Install

```bash
claude plugin marketplace add davdittrich/gsd-beads
claude plugin install markdown-linting@gsd-beads -y
```

The marketplace entry stays hosted at `davdittrich/gsd-beads` even though this plugin lives in
its own repo -- the two repository names are intentionally different.

## Uninstall

```bash
claude plugin uninstall markdown-linting -y
```

## Caveats

- **rumdl's `0` is not proof of a clean tree.** On 2026-08-18 (commit `866d071`), over the
  identical target set and allowlist-only ruleset, rumdl reported 0 violations where
  `markdownlint-cli2 0.23.2` reported 309 (302 MD022, 7 MD024). Accepted tradeoff: rumdl trades
  some detection depth for a single static binary with no Node dependency.
- The `SessionStart` hook installs the capability bundle at user scope when the bundle changed
  since the last successful install, and exits silently otherwise.
- Marketplace installation copies the cloned repo into the installer's local plugin cache --
  documented Claude Code behavior this repo does not control.

## License

MIT, see [LICENSE](./LICENSE).

## gsd-core

This is a capability plugin for [gsd-core](https://github.com/open-gsd/gsd-core).
