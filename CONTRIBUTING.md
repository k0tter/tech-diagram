# Contributing

[English](CONTRIBUTING.md) | [日本語](CONTRIBUTING.ja.md) | [Bahasa Indonesia](CONTRIBUTING.id.md)

How development on tech-diagram works. The only dependency is the Python
standard library (3.10+), so setup is just a clone.

## Development loop

### 1. Regression tests

```bash
python3 scripts/tests.py
```

The suite covers the skill package, builder, validator, layout engine and
tf_to_spec. **Run it before and after every change** and keep everything
green. When you touch an engine, add matching tests to the same file. For a
fast package/frontmatter check while editing `SKILL.md`, run:

```bash
python3 scripts/tests.py TestSkillPackage
```

### 2. Template regeneration and the byte-identical gate

The `.spec.json` and `.drawio` files in `templates/` are committed as pairs,
and CI verifies that regenerating with the current engine produces
byte-identical output. If you intentionally change the engine's output,
**regenerate all templates and include them in the commit**:

```bash
for f in templates/*.spec.json; do
  python3 scripts/build_drawio.py "$f" -o "${f%.spec.json}.drawio"
done
git diff --stat -- templates/   # eyeball that the diff is what you intended
```

Every template must build at 0 errors / 0 warnings
(`=== 0 error(s), 0 warning(s) ===`). Pushing without regenerating fails the
template sync gate in CI.

### 3. Router checks for routing quality

Changes that touch routing or placement must pass the router checks in
addition to the validator — 17 checks: 10 routing-geometry checks (connection
anchors / fan-out symmetry / lane separation / exit direction / vertical-pair
centering / sibling-container dimensions / fan side consistency / max bends /
same-side port separation / fork shape) plus 7 shape-and-contract checks
(decision vertices / safe cell ids / both-end labels / per-end ER
cardinality / stereotype italics / flow shapes and links / gateway topology):

```bash
python3 evals/check_diagram.py <out.drawio> --router
```

The checks are calibrated to zero false positives on the templates and
regression fixtures, so if a violation appears, suspect the engine, not the
check.

### 4. Fail-before verification (routing regression fixtures)

Routing improvements are pinned with
`evals/files/router-regression/verify.py`:

```bash
# pass-after: current engine, zero violations on all specs
python3 evals/files/router-regression/verify.py

# fail-before: confirm the targeted check actually fails on a snapshot of the
# pre-fix engine
python3 evals/files/router-regression/verify.py \
    --engine <path to the old build_drawio.py> --expect-fail --era <r3|r4|r5|r7|sem>
```

A check without a confirmed fail-before is not a regression guard (a check
that passes from day one protects nothing), so it does not get merged.

## How fixes work — repro spec → fail-before → regression tests

Routing/layout bug fixes proceed in this order:

1. **Repro spec**: build the smallest `.spec.json` that reproduces the issue
   (the same required fields as the "Routing / layout bug report" issue form).
2. **fail-before**: before fixing, write a check in `check_diagram.py` that
   machine-detects the phenomenon, and measure that it **actually fails** on
   the current (pre-fix) engine.
3. **Fix**: change the engine and confirm the same check passes.
4. **Pin the regression**: add the repro spec to the fixtures in
   `evals/files/router-regression/`, and add a unit-level regression test to
   `scripts/tests.py`.
5. Regenerate all templates (step 2 above) + `python3 scripts/tests.py` all
   green.

"It looks fixed" is not a completion criterion. Done means: the check fails
on before and passes on after, and no new false positives appear on the
existing calibration files.

## Pull requests

- 1 PR = 1 logical change. Don't mix unrelated refactoring or reformatting.
- Follow the existing commit message conventions (`feat:` / `fix:` /
  `evals:` / `docs:` etc.).
- CI must be fully green to merge: regression tests on Python 3.10/3.13,
  template sync, fuzzer smoke, real draw.io render smoke, gitleaks.
- Report bugs via the issue templates (Routing / layout bug report /
  Structured feedback). A report with "phenomenon + reproduction + measured
  values" can be turned into a fail-before fixture as-is.

## Reporting vulnerabilities

For security-related reports, do not open an issue — follow the process in
[SECURITY.md](SECURITY.md).
