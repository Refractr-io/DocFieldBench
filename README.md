# DocFieldBench

An open benchmark for structured extraction from documents. It measures what costs money in a document pipeline:
values that are wrong or invented, fields that should have stayed empty, responses that break the schema, and how
long it all takes. Run it on the included documents, or on your own.

> **Status: pre-release.** The scoring core is in place; the dataset (v1.0.0) is being built. Nothing here is a
> result yet.

## What it measures
Every task is a document (PDF, image or HTML, up to 10 pages) with a JSON schema and a gold answer for every field.
Systems get the original file: reading it, through a text layer, OCR or vision, is part of the test. DocFieldBench
scores each field deterministically, with no LLM judge:

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
| Business | invoices, credit notes, receipts, statements, delivery notes | embedded e-invoice XML, hand labels, rendering records |
| Records | filings, patents, rules, court opinions | the documents' own markup and official metadata |
| Forms | government forms | programmatic form fills |

No gold value comes from a model.

## Quickstart (once v1.0.0 is published)
```bash
pip install docfieldbench
docfieldbench data download v1.0.0
docfieldbench run --system openai_structured --model <model> --track business
docfieldbench report results/<run>
```
Bring your own extractor (a Python function or any HTTP endpoint) and your own documents (a folder plus a gold file
per document). See `GOLD_GUIDE.md`.

## Licenses
Code: Apache-2.0. Schemas and gold: CC BY 4.0. Every document keeps its own license, listed per document in the
release manifest and summarised in `DATA_LICENSES.md`.

## Training-data canary
Every data file carries the string in `docfieldbench/__init__.py` (`CANARY`). Please filter it out of training
corpora.
