"""Turn a system's raw reply into (parse_status, parsed JSON) the way a pipeline calling json.loads would see it."""
from __future__ import annotations

import json
import re

_FENCE = re.compile(r"^\s*```(?:json|JSON)?\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


def parse_response(raw: str | None) -> tuple[str, object]:
    """('ok' | 'fenced' | 'unparseable' | 'empty', parsed or None).

    A reply wrapped in a ```json fence is parsed and reported as `fenced`: stripping a fence is one line in any client,
    so it is counted apart rather than as a failure. Prose around the JSON, truncation or anything else that json.loads
    rejects is `unparseable`.
    """
    if raw is None or not str(raw).strip():
        return "empty", None
    text = str(raw).strip()
    try:
        return "ok", json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _FENCE.match(text)
    if m:
        try:
            return "fenced", json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return "unparseable", None
