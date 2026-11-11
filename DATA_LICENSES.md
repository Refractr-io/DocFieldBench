# Data licenses

Every document in a release has its source in its task file (`source`, `source_ref`, `license`) and a sha256 in
`manifest.json`. This page summarises them. Schemas and gold written for DocFieldBench are CC BY 4.0.

| source | documents | license | notes |
|---|---|---|---|
| ZUGFeRD corpus (github.com/ZUGFeRD/corpus) | 29 | Apache-2.0 | e-invoice PDFs; gold from the embedded XML |
| invoice2data test invoices (github.com/invoice-x/invoice2data) | 11 (+4 scans) | MIT (repository) | third-party invoices published as test files |
| Caselaw Access Project (case.law) | 48 | CC0-1.0 | opinion text as published by the project |
| Federal Register (federalregister.gov) | 27 | public domain | US government work; 21 as printed PDFs, 6 as the HTML edition |
| SEC EDGAR (sec.gov) | 25 | public domain filing system | 10-Q/10-K cover pages and Form 4 renderings; the content is filed by the registrant or reporting person |
| VAREX (huggingface.co/datasets/ibm-research/VAREX) | 40 | CDLA-Permissive-2.0 | US government form images |
| IRS forms filled for this benchmark | 20 | forms: public domain; values: CC BY 4.0 | fillable irs.gov PDFs, filled with synthetic values and flattened |
| Documents rendered for this benchmark | 60 | CC BY 4.0 | records, templates and word lists written for this repository; DejaVu fonts (Bitstream Vera license, bundled) |

Scan and photo variants are derived from the documents above and keep their licenses.

*Each source's terms are checked again before every release.*
