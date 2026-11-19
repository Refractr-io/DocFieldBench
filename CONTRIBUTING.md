# Contributing

## Report a gold or scoring error
Open an issue with the `task_id`, the field (its JSON pointer, e.g. `/seller/name`), what the document shows and what
you think the gold or the verdict should be. Releases are immutable: an accepted fix goes into the next data version
with a changelog entry, never into `data/v1.0.0`.

## Submit a result
1. Run and score your system on the release:
   ```bash
   docfieldbench run data/v1.0.0/tasks --system my_system.json --out preds.jsonl
   docfieldbench score data/v1.0.0/tasks preds.jsonl --summary summary.json
   ```
2. Open an issue titled `Result: <system name>` and attach `preds.jsonl`, `summary.json`, the run file written next
   to the predictions (`preds.jsonl.run.json`) and your system config without secrets.
3. Say how the documents were read (native, page images or text) and on what hardware a local model ran.

A result is listed only with its predictions file, so anyone can rescore it. Do not tune a system on these documents;
the benchmark data carries a canary string and must stay out of training corpora.

## Change the code
```bash
pip install -e ".[dev]"
ruff check .
pytest -q
python scripts/guard.py        # no secrets, e-mail addresses or home paths
```
Matcher changes need a test in `tests/` and a note in `CHANGELOG.md`, because they move every system's score.
