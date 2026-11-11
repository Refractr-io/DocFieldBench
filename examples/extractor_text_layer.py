"""An example extractor for `docfieldbench run` (adapter `python`): read the text the harness hands over (reader
`text`) and ask any OpenAI-compatible endpoint for the JSON. Point it at a local server (llama.cpp, vLLM, Ollama) or
an API with EXAMPLE_BASE_URL, EXAMPLE_MODEL and EXAMPLE_API_KEY.

  {"name": "my extractor", "adapter": "python", "reader": "text",
   "options": {"callable": "examples/extractor_text_layer.py:extract"}}
"""
import json
import os

import httpx

from docfieldbench.prompt import SYSTEM, user_text


def extract(schema, document):
    r = httpx.post(os.environ.get("EXAMPLE_BASE_URL", "http://localhost:8080/v1").rstrip("/") + "/chat/completions",
                   headers={"Authorization": f"Bearer {os.environ.get('EXAMPLE_API_KEY', 'none')}"}, timeout=300,
                   json={"model": os.environ.get("EXAMPLE_MODEL", "local"), "temperature": 0,
                         "messages": [{"role": "system", "content": SYSTEM},
                                      {"role": "user", "content": user_text(schema, document.text)}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def extract_offline(schema, document):
    """No model: the first date and amount in the text. For trying the pipeline end to end."""
    from docfieldbench.baselines import first_candidate
    from docfieldbench.byo import stub_fields
    task = {"task_id": "x", "schema": schema, "fields": stub_fields(schema)}
    return json.loads(json.dumps(first_candidate(task, document.text or "")["parsed"]))
