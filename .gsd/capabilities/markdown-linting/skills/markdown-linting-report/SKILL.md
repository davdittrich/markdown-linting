---
name: gsd-markdown-linting-report
description: "Regenerates LINT-REPORT.md from a live rumdl run over the curated MD0XX ruleset (verify:post lifecycle dispatch)"
allowed-tools:
  - Read
  - Bash
---

**STOP -- DO NOT READ THIS FILE. You are already reading it. This prompt was injected into your context by the command system. Using the Read tool on this file wastes tokens. Begin executing Step 1 immediately.**

## Step 1 -- Config Gate

Check whether the markdown-linting capability is enabled by reading `.planning/config.json`
directly with the Read tool.

1. Read `.planning/config.json` with the Read tool.
2. If the file exists, `config["markdown-linting"]` is present, and
   `config["markdown-linting"]["enabled"]` is explicitly the boolean `false`: display the
   disabled message below and **STOP**.
3. Otherwise -- the file is missing, `config["markdown-linting"]` is absent, or it is present
   with no `enabled` key -- fall through to the shipped default (`markdown-linting.enabled: true`
   in `capability.json`) and proceed to Step 2.

**Disabled message:**

```
GSD > MARKDOWN LINTING REPORT

Markdown linting is disabled (markdown-linting.enabled).
Nothing was regenerated; the loop proceeds normally.
```

This step is `onError: skip` at its single dispatch point (`verify:post`) -- no dispatch ever
fails a phase.

## Step 2 -- verify:post: Regenerate LINT-REPORT.md

This skill has exactly one `capability.json` `steps[]` entry (`verify:post`), so there is no
lifecycle-point branch to resolve -- unlike `beads-status`, which dispatches at four points.

Run one Bash call passing only the phase directory:

```bash
python3 .gsd/capabilities/markdown-linting/scripts/lint.py verify-post <phase directory>
```

Print `lint.py`'s stdout summary verbatim (`LINT-REPORT.md regenerated: <n> violation(s)`).

Do NOT port `beads-status` Step 2d's ship.md patch re-verification -- that is beads-specific
(beads owns the patch) and this capability has no `ship:pre` **step**, only a generically
dispatched `ship:pre` **gate**.

## Anti-Patterns

1. DO NOT write `LINT-REPORT.md` at a project-root path (`.planning/LINT-REPORT.md`) -- the
   generic gate evaluator only resolves artifacts inside `phaseDir` (13-RESEARCH.md Pitfall 1).
   `lint.py verify-post` already writes the correct phase-scoped path; this skill must never
   override that with a different destination.
2. DO NOT re-run the config gate's check more than once per invocation, and DO NOT call
   `lint.py count` or `lint.py fix` from this skill -- this dispatch point only regenerates the
   report.
