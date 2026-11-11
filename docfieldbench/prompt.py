"""The published prompt. Every adapter sends the same words, so systems differ only in the model and the reading step.

A run records PROMPT_ID; a changed prompt gets a new id, and results under different ids are not compared.
"""
from __future__ import annotations

import json

from .schema import to_json_schema

PROMPT_ID = "dfb-prompt-1"

SYSTEM = (
    "You extract structured data from documents. Return only a JSON object that matches the given JSON Schema. "
    "Use null for any field the document does not state; never guess or compute a value. Dates: ISO 8601 "
    "(YYYY-MM-DD, or YYYY-MM / YYYY when the document gives less). Numbers: JSON numbers without currency symbols or "
    "thousands separators. Copy text values as printed."
)


def schema_text(schema: dict) -> str:
    return json.dumps(to_json_schema(schema), indent=1)


def user_text(schema: dict, document_text: str | None = None) -> str:
    """The user message: the schema, then the document's text, or a pointer to the attached file."""
    if document_text is not None:
        return f"JSON Schema:\n{schema_text(schema)}\n\nDocument:\n{document_text}\n\nReturn only the JSON object."
    return f"JSON Schema:\n{schema_text(schema)}\n\nThe document is attached. Return only the JSON object."
