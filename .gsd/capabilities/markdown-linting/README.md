# markdown-linting

Wraps [`rumdl`](https://github.com/rvben/rumdl) over `.planning/**/*.md`, root `README.md`, and
root `CLAUDE.md` (the D-02 target set — `docs/` and every other markdown path stay out of v1),
writes a gate-readable violation-count report, and advises (never blocks) `/gsd-ship` on it.

## What it does

One lifecycle step, one gate:

- **`verify:post`** runs `.gsd/capabilities/markdown-linting/scripts/lint.py verify-post
  <phase_dir>`, which fully overwrites `{phase_dir}/{padded_phase}-LINT-REPORT.md` on every
  invocation (regenerate-every-run, never merged with a prior hand edit — the same discipline
  `beads/scripts/sync.py`'s `regenerate_beads_md` uses for `BEADS.md`). The report is
  **phase-scoped**, not a project-root `.planning/LINT-REPORT.md`: the generic gate evaluator
  (`gate-predicate-evaluator`'s `artifact-frontmatter-equals` kind) resolves artifacts only inside
  `phaseDir`, so a root-level file would make the `ship:pre` gate silently never fire — there
  would be nothing at the path it looks for.
- **`ship:pre`** reads `LINT-REPORT.md`'s `violation_count` frontmatter field via
  `artifact-frontmatter-equals` and is **advisory by default** (`blocking: false`): a nonzero
  count prints a warning naming it, but the ship proceeds. Flipping this to blocking is tracked as
  **MDL-05** in the v2 backlog — it needs a clean full-milestone run first, not a setting to turn
  on casually.

Two config keys, both in `capability.json`'s `config` block and overridable in
`.planning/config.json`:

| Key | Default | Effect |
|-----|---------|--------|
| `markdown-linting.enabled` | `true` | Master toggle. `false` skips the `verify:post` step entirely (no report is regenerated). |
| `markdown-linting.ship_gate` | `true` | Whether the advisory `ship:pre` gate is even registered. `false` disables the gate but leaves `verify:post` running. |

## Install

Three tiers, checked in order by `resolve_rumdl_invocation()`:

1. **`rumdl` already on `PATH`** — preferred. The install is under the operator's own control
   (their package manager, their version pin), and this capability never installs anything on
   your behalf.
2. **`uvx rumdl`** (no persistent install). This capability's package-legitimacy audit flagged
   `rumdl`'s PyPI listing — the channel `uvx` actually pulls from — `SUS` (`too-new`,
   `unknown-downloads`), while the authoritative `crates.io` listing (the tool's native
   distribution) scored `OK`: ~1.5 years of history, matching `github.com/rvben/rumdl` repo,
   1,277 weekly downloads. The `SUS` verdict is a rolling-release republish artifact — the
   project's CI republishes every version tag to every registry on each release, so the
   "too-new" heuristic measures the latest version's publish timestamp, not the package's actual
   age — not a live risk signal. Confirmed live this phase (`uvx rumdl --version` resolves to the
   same `rvben/rumdl` project).
3. **Neither available** — one visible notice (`NOTICE` constant in `lint.py`), exit 0, and
   `LINT-REPORT.md` rewritten with a `violation_count: unavailable` sentinel. Never a stale count
   presented as current (MDL-04).

`cargo install rumdl`, `pip install rumdl`, `brew install rumdl`, and `npm install -g rumdl` all
exist as alternative install paths too — none of them is presented as the primary method; PATH
plus the `uvx` fallback cover every environment this capability needs to run in.

## Ruleset

The allowlist works **by omission** — `config/.rumdl.toml` sets `[global] enable = [...]` with no
`disable` key, so any rule not listed is off. `--config <path>` is always passed explicitly on
every invocation, because rumdl's auto-discovery was measured to silently ignore
`.markdownlint-cli2.jsonc`-style configs — an implicit config lookup would have been a second,
untested way for the ruleset to drift from what this file documents.

**Enabled:**

| Rule | Name | Checks |
|------|------|--------|
| MD001 | heading-increment | Heading levels increment by one (no skipping, e.g. `#` → `###`) |
| MD003 | heading-style | Consistent heading style (ATX `#`, not Setext underlines) throughout a file |
| MD009 | no-trailing-spaces | No trailing whitespace at end of line |
| MD012 | no-multiple-blanks | No more than one consecutive blank line |
| MD022 | blanks-around-headings | Exactly one blank line above and below every heading |
| MD024 | no-duplicate-heading | No two headings with identical text |
| MD040 | fenced-code-language | Every fenced code block declares a language tag |

**Disabled (by omission), with reasons:**

| Rule | Name | Why it's off |
|------|------|---------------|
| MD013 | line-length | Fights `.planning/`'s agent-generated long lines (verified-claim sentences, table rows, cited paths) — enforcing a wrap width would force either constant reflow noise or artificial line breaks mid-claim. |
| MD033 | no-inline-html | `.planning/` uses `<details>` blocks throughout (collapsible sections in RESEARCH.md/REVIEWS.md); banning inline HTML would make that pattern a permanent violation. |
| MD041 | first-line-heading | Every `.planning/` artifact is frontmatter-led (`---\nphase: ...\n---`), not heading-led; this rule assumes the opposite convention. |

## Known divergence from markdownlint-cli2

**rumdl's `0` is not proof of a clean tree.** rumdl and `markdownlint-cli2` implement the same
named rules with different internal heuristics, and they do not agree on every case. Measured
this session, after Task 1's auto-fix pass brought rumdl's own count on the D-02 target set to
`0`, by running `markdownlint-cli2` over the **identical** file set with an identical
allowlist-only config (`"default": false`, the same seven rules explicitly `true`):

| Rule | rumdl (`lint.py count`) | markdownlint-cli2 0.23.2 |
|------|------------------------:|--------------------------:|
| MD001 | 0 | 0 |
| MD003 | 0 | 0 |
| MD009 | 0 | 0 |
| MD012 | 0 | 0 |
| MD022 | 0 | 302 |
| MD024 | 0 | 7 |
| MD040 | 0 | 0 |
| **Total** | **0** | **309** |

rumdl detected 0 of the 309 violations markdownlint-cli2 found on this identical D-02 target set
and ruleset (0/309 = 0%) — every one of them is a heading-spacing (MD022) or duplicate-heading
(MD024) case rumdl's own detector never flags, not a case the auto-fixer left unfixed. This is a
**known, accepted tradeoff**, not a defect being glossed over: rumdl trades some detection depth
for being a single static binary with no Node dependency class, which is exactly why it was chosen
over `markdownlint-cli2` as the enforced tool (see `13-RESEARCH.md`'s tool selection).

**Measured:** 2026-08-18, commit `866d071`. This figure needs re-measurement as `.planning/`
grows — every new phase's artifacts are new corpus for both tools to (dis)agree on, and this
table will drift the same way REQUIREMENTS.md's earlier pre-recorded figure already has.
