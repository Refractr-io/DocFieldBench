# Writing gold for your own documents

Twenty documents labelled carefully say more about your pipeline than two hundred labelled in a hurry. This guide is
the rulebook the scorer follows; the included gold follows it too.

## 1. One schema per document family
Write the schema before you look at any system's output, with the field names your product actually uses.
- Every field is nullable: `{"type": ["string", "null"]}`.
- Use a name that can't be misread (`total_incl_tax`, not `total`). Schemas carry no descriptions; the name is the
  contract.
- Types: `string`, `string` with `"format": "date"`, `integer`, `number`, `boolean`, objects, and arrays of either.
- Split addresses into parts (`street`, `postcode`, `city`, `country`).

## 2. What counts as the value
- **As the document states it.** No arithmetic, no lookups, no inference from other fields.
- **Dates:** ISO `YYYY-MM-DD`. If the document gives only a month or a year, give `YYYY-MM` or `YYYY`.
- **Amounts:** a JSON number in the document's currency, without symbols (`1234.56`). Put the currency in its own
  field if you need it.
- **Identifiers** (invoice numbers, VAT IDs, IBANs): as printed. The scorer ignores spaces, punctuation and case.
- **Names and short text:** as printed. The scorer ignores case, extra spaces and punctuation at the ends. For
  `name` fields, titles and salutations ("Dr.", "Herrn") and a trailing legal form ("GmbH", "SARL", "Ltd",
  "S.A. de C.V.") are optional. List other acceptable spellings under `accept`.
- **Amounts printed negative** (a deduction, a credit-note line): give the value as the structured data has it and
  add the negated value under `accept`, or list the column under `item_sign_either` for line items. Either sign then
  scores.
- **Booleans:** a checkbox or an explicit yes/no in the document. Never a guess from context.
- **Lists:** every item, in document order.

## 3. Absent fields
A field the document doesn't give has gold `null` (or `[]` for a list) and status `absent`. Check twice: search the
document for the label and for any value of that shape. The `inject-absent` command adds plausible absent fields to
your schemas automatically, verified the same way, so you can measure invented values without extra labelling.

## 4. When to exclude a field
Mark a field `excluded`, with a reason, when the document is genuinely ambiguous (two candidate values and nothing
to choose between them) or unreadable. Excluded fields are asked but not scored.

## 5. Per-field record
```json
"/seller/vat_id": {
  "status": "present",
  "value": "DE123456789",
  "accept": [],
  "match": "id",
  "provenance": "human",
  "evidence": {"page": 1, "text": "USt-IdNr. DE 123 456 789"}
}
```
Match kinds: `id`, `date`, `amount`, `number`, `integer`, `boolean`, `name`, `short_text`, and for arrays
`array_scalars` or `array_objects` (with `item_match` giving the kind per item field).
