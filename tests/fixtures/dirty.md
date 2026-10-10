<!-- dirty.md: deliberately violates the curated MD0XX ruleset. Its expected
violation count is asserted as an exact integer in
test_lint.py::test_dirty_fixture_known_count -- editing this file requires
updating that number there too. -->
# Dirty Fixture
## Section One
This line follows two headings with no blank line above or between them (MD022).

This line has trailing whitespace right here.   

```
code fence with no language tag (MD040)
```

This is a very long line that exceeds eighty characters by a wide margin so that if MD013 (line-length) were enabled it would definitely flag this line as too long, but that rule is disabled in the curated ruleset so it must produce zero MD013 violations even though this line is clearly over the usual limit.

Here is some <strong>inline HTML</strong> which would normally trigger MD033 (inline-HTML) but that rule is disabled in the curated ruleset so it must produce zero MD033 violations too.
