---
name: gsd-markdown-linting-report
description: "Regenerate the phase's LINT-REPORT.md via rumdl. Use only when verify:post hands you a phase directory."
allowed-tools:
  - Bash
---

## Step 1 -- Locate lint.py

Use the first path that exists:

1. `${CLAUDE_PROJECT_DIR}/.gsd/capabilities/markdown-linting/scripts/lint.py`
2. `${GSD_HOME:-$HOME}/.gsd/capabilities/markdown-linting/scripts/lint.py`

Neither exists: print `markdown-linting: lint.py not found under CLAUDE_PROJECT_DIR or GSD_HOME` and stop.

## Step 2 -- Regenerate

Run one Bash call with the phase directory:

```bash
python3 <lint.py path> verify-post <phase directory>
```

Done when one outcome holds:

- Exit 0 and the output is `LINT-REPORT.md regenerated: <n> violation(s)`: print that line verbatim.
- Exit 0 with any other output (NOTICE or `rumdl failed, lint skipped`): print it verbatim; report marked unavailable.
- Nonzero exit: print the full output and stop. Do not retry.
