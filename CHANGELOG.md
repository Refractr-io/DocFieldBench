# Changelog

## Unreleased
- The DocFieldBench score: one headline number (0-100) from per-field outcomes. A right value or a right empty field
  earns a point, a silent error costs one, per document clipped at 0, averaged per track, tracks weighed equally,
  with a within-track document bootstrap CI. `docfieldbench score` prints it first and writes it to the summary as
  `score`; each group row gets a `score` column (the document-macro field score).

## 0.1.0a1 (pre-release)
- First package on PyPI: the scoring core and the `validate`, `score` and `baseline` commands.
- Scoring core: schema subset, deterministic matchers, array alignment, per-field outcomes, metrics with document
  bootstrap, shortcut baselines.
