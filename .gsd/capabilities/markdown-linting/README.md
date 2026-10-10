# markdown-linting

Wraps [`rumdl`](https://github.com/rvben/rumdl) over `.planning/**/*.md`, root `README.md`, and
root `CLAUDE.md`, writes a gate-readable violation-count report, and advises (never blocks)
`/gsd-ship` on it. `docs/` and every other markdown path are out of scope.

## What it does

One lifecycle step, one gate:

- **`verify:post`** runs `lint.py verify-post <phase_dir>`, which fully overwrites
  `{phase_dir}/{padded_phase}-LINT-REPORT.md` on every invocation (regenerate-every-run, never
  merged with a prior hand edit). The report is **phase-scoped**, not a project-root
  `.planning/LINT-REPORT.md`: the generic gate evaluator (`gate-predicate-evaluator`'s
  `artifact-frontmatter-equals` kind) resolves artifacts only inside `phaseDir`, so a root-level
  file would make the `ship:pre` gate silently never fire.
- **`ship:pre`** reads `LINT-REPORT.md`'s `violation_count` frontmatter field via
  `artifact-frontmatter-equals` and is **advisory** (`blocking: false`): a nonzero count prints a
  warning naming it, but the ship proceeds.

The skill locates `lint.py` at `${CLAUDE_PROJECT_DIR}/.gsd/capabilities/markdown-linting/scripts/lint.py`,
then `${GSD_HOME:-$HOME}/.gsd/capabilities/markdown-linting/scripts/lint.py`, and stops with a
message when neither exists.

Two config keys, both in `capability.json`'s `config` block and overridable in
`.planning/config.json`:

| Key | Default | Effect |
|-----|---------|--------|
| `markdown-linting.enabled` | `true` | Master toggle. `false` skips the `verify:post` step entirely (no report is regenerated). |
| `markdown-linting.ship_gate` | `true` | Whether the advisory `ship:pre` gate is registered. `false` disables the gate but leaves `verify:post` running. |

## Install

`rumdl` is resolved in this order:

1. `rumdl` on `PATH` -- preferred; the operator controls install and version, and this capability
   never installs anything.
2. `uvx rumdl` (no persistent install).
3. Neither available -- one visible notice, exit 0, and `LINT-REPORT.md` rewritten with a
   `violation_count: unavailable` sentinel. Never a stale count presented as current.

A rumdl that is reachable but fails writes the same `unavailable` sentinel plus an
`unavailable_reason`, so no failure leaves a stale numeric count for the `ship:pre` gate to read.
A rumdl config/runtime error also exits `1`; timeouts, `OSError`, and non-JSON output exit `0` with
a one-line cause.

## Target set

`.planning/`, root `README.md`, root `CLAUDE.md`. The two root files are **linted if present**:
rumdl exits `2` on a path that does not exist, so passing an absent `CLAUDE.md` would turn every run
in such a project into a permanent `unavailable` sentinel. Paths named explicitly on the CLI
(`lint.py count <paths>`, `lint.py fix <paths>`) are **not** filtered, so a typo fails loudly rather
than silently linting nothing and reporting `0`.

## Ruleset

`config/.rumdl.toml` is the single source for the enabled rules. It sets `[global] enable = [...]`
with no `disable` key, so any rule not listed is off. `--config <path>` is always passed
explicitly, because rumdl's auto-discovery was measured to silently ignore
`.markdownlint-cli2.jsonc`-style configs.

Off by omission:

- **MD013** (line-length): fights agent-generated long lines (verified-claim sentences, table rows,
  cited paths); a wrap width forces reflow noise or artificial mid-claim breaks.
- **MD033** (no-inline-html): `.planning/` uses `<details>` blocks throughout; banning inline HTML
  would make that a permanent violation.
- **MD041** (first-line-heading): `.planning/` artifacts are frontmatter-led, not heading-led.

## Known divergence from markdownlint-cli2

**rumdl's `0` is not proof of a clean tree.** On 2026-08-18 (commit `866d071`), over the identical
target set and allowlist-only ruleset, rumdl reported 0 violations where `markdownlint-cli2 0.23.2`
reported 309 (302 MD022, 7 MD024). Accepted tradeoff: rumdl trades some detection depth for a single
static binary with no Node dependency. Re-measure as `.planning/` grows.
