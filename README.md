# DocFieldBench

An open benchmark for structured extraction from documents. It measures what costs money in a document pipeline:
values that are wrong or invented, fields that should have stayed empty, responses that break the schema, and how
long it all takes. Run it on the included documents, or on your own.

> **Status: release candidate.** The dataset (260 documents) is built and in blind adjudication; v1.0.0 follows when
> the adjudication log is published. Nothing here is a result yet.

## What it measures
Every task is a document (PDF, image or HTML, up to 10 pages) with a JSON schema and a gold answer for every field.
Systems get the original file: reading it, through a text layer, OCR or vision, is part of the test. DocFieldBench
scores each field deterministically, with no LLM judge.

**The DocFieldBench score** (0-100) is the one number to compare systems by. Every field of a document earns a point
when it comes back right, including a field correctly left empty; an omitted value earns nothing; a silent error (a
wrong, swapped or invented value) costs a point. A document scores its points over its fields (never below 0), a
track the mean over its documents, and the score is the mean over the three tracks, which weigh the same. Answering
only pays when a system is more likely right than wrong, so answering everything and answering nothing both score
low: the all-null baseline scores the share of absent fields. The 95% CI comes from a bootstrap over documents within
each track. The metrics below explain the score:


- **Precision:** of the values a system returns, how many are right. One minus precision is the *silent error rate*:
  wrong, swapped or invented values that a pipeline would store without noticing.
- **Recall:** of the values a document contains, how many come back right.
- **Abstention:** of the fields a document does *not* contain, how many come back empty. About one field in eight is
  absent by design, verified against the document.
- **Swaps:** a value that belongs to another field of the same document (the buyer's name as the seller's).
- **Conformance:** first responses that parse and match the schema. Retries are recorded, never scored.
- **Latency and cost**, measured the same way for every system.
- Optional: if a system returns a confidence per field, how much can be auto-accepted at a target error rate.

Results come per track, per document condition (born-digital, scan, photo) and per field tag (look-alike values,
line items, values that need normalising), with 95% confidence intervals from a document bootstrap.

## Tracks
| track | what | gold from |
|---|---|---|
| Business (100) | invoices, receipts, bank and account statements, delivery notes, payslips | embedded e-invoice XML, hand labels, rendering records |
| Records (100) | court opinions, Federal Register rules, SEC cover pages and Form 4s | the documents' own markup and official metadata |
| Forms (60) | US government forms: page images and filled PDFs | dataset labels, programmatic form fills |

Single-page PDFs also come as a scan or photo with the same gold; those are reported by condition, not in the score.

No gold value comes from a model.

## Quickstart
```bash
pip install --pre docfieldbench
docfieldbench data download v1.0.0 --url RELEASE_URL           # or --from-file; every file is checked
docfieldbench run data/v1.0.0/tasks --system my_system.json --out preds.jsonl
docfieldbench score data/v1.0.0/tasks preds.jsonl --summary summary.json
docfieldbench baseline data/v1.0.0/tasks --out all_null.jsonl   # the all-null baseline, for comparison
```
A system config names an adapter and a reading step:
```json
{"name": "my-model", "adapter": "openai_compat", "reader": "native",
 "options": {"model": "vendor/model", "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"}}
```
- **Adapters:** `openai_compat` (any OpenAI-style chat API: hosted, vLLM, llama.cpp, Ollama) and `python` (your
  own function, `path/to/file.py:extract`).
- **Reading steps:** `native` (the file as it is), `pages_png` (PDF pages as images, for vision models without PDF
  input), `text` (text layer; Tesseract with default settings for images and scans). The step is part of the system
  and appears in its config hash.
- **Protocol:** the published prompt (`docfieldbench/prompt.py`), one request per document, the first reply scored;
  only transport failures are retried. `--pilot N` runs the N largest documents and projects the cost; `--budget`
  stops a run; `--resume` never pays twice. Each run writes spend and latency next to its predictions.

### Your own documents
`docfieldbench init` turns a folder and a schema into task stubs to label, `inject-absent` adds fields your documents
provably don't state, and `run` and `score` work as above. `examples/` walks through it with three receipts.
- **Tasks:** one JSON file per document, with its schema and a gold record per field. `GOLD_GUIDE.md` describes the
  format and the labelling rules.
- **Predictions:** one JSON object per line, either `{"task_id": ..., "raw": "<the system's reply>"}` (parsed the way
  `json.loads` would see it) or `{"task_id": ..., "parse_status": "ok", "parsed": {...}}`. A task without a line
  counts as a failed response.


## Licenses
Code: Apache-2.0. Schemas and gold: CC BY 4.0. Every document keeps its own license, listed per document in the
release manifest and summarised in `DATA_LICENSES.md`.

## Training-data canary
Every data file carries the string in `docfieldbench/__init__.py` (`CANARY`). Please filter it out of training
corpora.
