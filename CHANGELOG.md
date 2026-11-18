# Changelog

## Data v1.0.0 (2026-11-18)
- Data build: 260 documents in three tracks plus 86 scan/photo variants; absence library, field
  tags (lookalike, normalize, late, language), Rule 0 gate, PII and layout gates, manifest and diversity card.
- `docfieldbench run` (plain requests, OpenAI-compatible and Python adapters, native / page-image / text reading
  steps with Tesseract), `data download|verify`, `init` and `inject-absent` for your own documents, `adjudicate`.
- Scores report by condition and field tag; the headline counts each document once.
- The DocFieldBench score: one headline number (0-100) from per-field outcomes. A right value or a right empty field
  earns a point, a silent error costs one, per document clipped at 0, averaged per track, tracks weighed equally,
  with a within-track document bootstrap CI. `docfieldbench score` prints it first and writes it to the summary as
  `score`; each group row gets a `score` column (the document-macro field score).

- Blind adjudication applied to the release: 309 disputed fields reviewed, changes in `ADJUDICATION_LOG.md`. An
  accepted alternative for a value inside a list row is stored as `item_accept` on the field.
- Date matcher: a weekday before the date, a clock time after a numeric date and typographic dashes are read as the
  same date (found by the matcher audit).

## 0.1.0a1 (pre-release)
- First package on PyPI: the scoring core and the `validate`, `score` and `baseline` commands.
- Scoring core: schema subset, deterministic matchers, array alignment, per-field outcomes, metrics with document
  bootstrap, shortcut baselines.
