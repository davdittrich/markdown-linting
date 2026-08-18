# Clean Fixture Title

This fixture is authored to yield zero violations against the curated
MD0XX ruleset (MD001, MD003, MD009, MD012, MD022, MD024, MD040).

## Section One

Every heading below is surrounded by exactly one blank line above and
below it, headings increment by one level at a time, no line carries
trailing whitespace, and no two headings share identical text.

```python
print("a fenced code block with an explicit language tag")
```

## Section Two

A second, distinctly named section, so MD024 (no-duplicate-heading) has
nothing to flag.

### Subsection Two A

One more heading level down, still incrementing by exactly one level
(MD001), still ATX style throughout (MD003).

Final paragraph, no trailing whitespace, no consecutive blank lines above
it (MD012).
