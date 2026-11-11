"""Adapters: how a run reaches a system.

  openai_compat  OpenAI-style chat completions: OpenRouter, OpenAI, vLLM, llama.cpp, Ollama, LM Studio
  python         your own function: `module:function` or `path/to/file.py:function`
"""
from __future__ import annotations

from .base import Adapter, Reply, TransportError


def get_adapter(name: str, options: dict, transport=None) -> Adapter:
    from . import openai_compat, python
    table = {"openai_compat": openai_compat.OpenAICompat, "python": python.Python}
    if name not in table:
        raise ValueError(f"unknown adapter {name!r}; one of {sorted(table)}")
    return table[name](transport=transport, **options)


__all__ = ["Adapter", "Reply", "TransportError", "get_adapter"]
