from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

from .base import Adapter, Reply


def load_callable(spec: str):
    target, _, name = spec.rpartition(":")
    if not target or not name:
        raise ValueError("callable: 'module.path:function' or 'path/to/file.py:function'")
    if target.endswith(".py"):
        path = Path(target).resolve()
        mod_spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(mod_spec)
        mod_spec.loader.exec_module(mod)
    else:
        mod = importlib.import_module(target)
    return getattr(mod, name)


class Python(Adapter):
    """Your own function: fn(schema: dict, document: Document) -> dict | str. A dict is the extraction; a str is the
    raw reply, parsed like any API's. Raise TransportError for a failure that should be retried."""

    def __init__(self, callable: str, **kw):  # noqa: A002 - the config key
        super().__init__(callable=callable, **kw)
        self.fn = load_callable(callable)

    def extract(self, schema: dict, doc) -> Reply:
        out = self.fn(schema=schema, document=doc)
        if isinstance(out, Reply):
            return out
        return Reply(raw=out if isinstance(out, str) or out is None else json.dumps(out, ensure_ascii=False))
