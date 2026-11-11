# Bring your own documents

Three receipts and a receipt schema, to try the whole loop on your own data:

```bash
docfieldbench init examples/my_docs --schema examples/receipt_schema.json --out my_bench --family receipt
# fill each my_bench/tasks/*.json: a value per field, or status "absent" / "excluded"
docfieldbench validate my_bench/tasks
docfieldbench inject-absent my_bench/tasks --fields examples/absent_fields.json      # optional
docfieldbench run my_bench/tasks --system my_system.json --out my_preds.jsonl
docfieldbench score my_bench/tasks my_preds.jsonl
```

`extractor_text_layer.py` is an example extractor for the `python` adapter: the document's text to any
OpenAI-compatible endpoint. `extract_offline` in the same file needs no model, for a dry run.
