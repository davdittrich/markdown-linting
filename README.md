# markdown-linting

Wraps rumdl over .planning/, README.md, and CLAUDE.md; verify:post writes a gate-readable violation-count report, ship:pre gates advisorily on it.

## What it does

One lifecycle step, one gate:

- **`verify:post`** runs the bundled `lint.py verify-post <phase_dir>`, which fully overwrites
  `{phase_dir}/{padded_phase}-LINT-REPORT.md` on every invocation (regenerate-every-run, never
  merged with a prior hand edit). The report is **phase-scoped**, not a project-root
  `.planning/LINT-REPORT.md`: the generic gate evaluator's `artifact-frontmatter-equals` predicate
  resolves artifacts only inside `phaseDir`, so a root-level file would make the `ship:pre` gate
  silently never fire.
- **`ship:pre`** reads `LINT-REPORT.md`'s `violation_count` frontmatter field via
  `artifact-frontmatter-equals` and is **advisory by default** (`blocking: false`): a nonzero
  count prints a warning naming it, but the ship proceeds.

Two config keys, both overridable in a project's `.planning/config.json`:

| Key | Default | Effect |
|-----|---------|--------|
| `markdown-linting.enabled` | `true` | Master toggle. `false` skips the `verify:post` step entirely (no report is regenerated). |
| `markdown-linting.ship_gate` | `true` | Whether the advisory `ship:pre` gate is even registered. `false` disables the gate but leaves `verify:post` running. |

Targets are `.planning/`, root `README.md`, and root `CLAUDE.md`. The two root files are
**linted if present** — a project without a root `CLAUDE.md` gets a normal count over what it does
have, not an error.

Ruleset (allowlist by omission — `config/.rumdl.toml` sets `[global] enable = [...]` with no
`disable` key, so any rule not listed is off):

**Enabled:**

| Rule | Name | Checks |
|------|------|--------|
| MD001 | heading-increment | Heading levels increment by one (no skipping, e.g. `#` -> `###`) |
| MD003 | heading-style | Consistent heading style (ATX `#`, not Setext underlines) throughout a file |
| MD009 | no-trailing-spaces | No trailing whitespace at end of line |
| MD012 | no-multiple-blanks | No more than one consecutive blank line |
| MD022 | blanks-around-headings | Exactly one blank line above and below every heading |
| MD024 | no-duplicate-heading | No two headings with identical text |
| MD040 | fenced-code-language | Every fenced code block declares a language tag |

**Disabled (by omission), with reasons:**

| Rule | Name | Why it's off |
|------|------|---------------|
| MD013 | line-length | Fights agent-generated long lines (verified-claim sentences, table rows, cited paths) — enforcing a wrap width would force either constant reflow noise or artificial line breaks mid-claim. |
| MD033 | no-inline-html | Many gsd-core projects use `<details>` blocks (collapsible sections); banning inline HTML would make that pattern a permanent violation. |
| MD041 | first-line-heading | gsd-core artifacts are frontmatter-led (`---\nphase: ...\n---`), not heading-led; this rule assumes the opposite convention. |

## Requirements

- **`rumdl`** — first-class prerequisite. Checked in this order by the resolver:
  1. `rumdl` already on `PATH` — preferred. Install is under the operator's own control (their
     package manager, their version pin); this capability never installs anything on your behalf.
  2. `uvx rumdl` (no persistent install).
  3. Neither available — one visible notice, exit 0, and `LINT-REPORT.md` rewritten with a
     `violation_count: unavailable` sentinel. Never a stale count presented as current.

  A rumdl that *is* present but fails (bad ruleset, crash, non-JSON output) is a distinct, louder
  path: the same `unavailable` sentinel is written, with an `unavailable_reason` naming the
  failure, but a config/runtime error also exits `1`. A broken ruleset is never laundered into a
  clean `0`.

  `rumdl` project: <https://github.com/rvben/rumdl>
- Python 3 (standard library only)
- gsd-core `>=1.6.0`

## Install

```bash
claude plugin marketplace add davdittrich/gsd-beads
claude plugin install markdown-linting@gsd-beads -y
```

The marketplace entry stays hosted at `davdittrich/gsd-beads` even though this plugin lives in
its own repo — the two repository names are intentionally different.

## Uninstall

```bash
claude plugin uninstall markdown-linting -y
```

## Caveats

- The `ship:pre` gate is **advisory and never blocks** — `capability.json` declares `blocking:
  false` and `onError: "skip"`, so a nonzero violation count prints a warning and the ship
  proceeds regardless.
- **rumdl's `0` is not proof of a clean tree.** rumdl and `markdownlint-cli2` implement the same
  named rules with different internal heuristics and do not agree on every case. Measured
  2026-08-18 (commit `866d071`) over an identical target set and allowlist-only ruleset: rumdl
  reported 0 violations where `markdownlint-cli2 0.23.2` reported 309 (all MD022/MD024,
  heading-spacing and duplicate-heading cases rumdl's own detector never flags). This is a known,
  accepted tradeoff, not a defect being glossed over — rumdl trades some detection depth for being
  a single static binary with no Node dependency class.
- The `SessionStart` hook re-grants the capability bundle at user scope on every session start and
  exits silently when the bundle is unchanged.
- Marketplace installation copies the cloned repo into the installer's local plugin cache —
  documented Claude Code behavior this repo does not control.

## License

MIT, see [LICENSE](./LICENSE).

## gsd-core

This is a capability plugin for [gsd-core](https://github.com/open-gsd/gsd-core).
