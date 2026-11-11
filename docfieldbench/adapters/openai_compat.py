from __future__ import annotations

from ..prompt import SYSTEM, user_text
from ..schema import to_openai_response_format
from .base import Adapter, Reply, TransportError, b64


class OpenAICompat(Adapter):
    """Chat completions. Files go in as OpenAI content parts: images as `image_url`, PDFs as `file` (OpenRouter and
    OpenAI accept both). `openrouter_pdf_engine` picks OpenRouter's PDF handling (native, pdf-text, mistral-ocr)."""

    def __init__(self, model: str, base_url: str = "https://openrouter.ai/api/v1", api_key_env: str | None =
                 "OPENROUTER_API_KEY", temperature: float = 0, max_tokens: int = 16384, response_format: str = "none",
                 openrouter_pdf_engine: str | None = None, extra_body: dict | None = None, **kw):
        if response_format not in ("none", "json_object", "json_schema"):
            raise ValueError("response_format: none | json_object | json_schema")
        super().__init__(model=model, base_url=base_url, api_key_env=api_key_env, temperature=temperature,
                         max_tokens=max_tokens, response_format=response_format,
                         openrouter_pdf_engine=openrouter_pdf_engine, extra_body=extra_body or {}, **kw)

    def body(self, schema: dict, doc) -> dict:
        o = self.options
        body = {"model": o["model"], "temperature": o["temperature"], "max_tokens": o["max_tokens"],
                **o["extra_body"]}
        if doc.text is not None:
            content = user_text(schema, doc.text)
        else:
            content = [{"type": "text", "text": user_text(schema)}]
            for media, data, name in doc.files:
                url = f"data:{media};base64,{b64(data)}"
                content.append({"type": "image_url", "image_url": {"url": url}} if media.startswith("image/")
                               else {"type": "file", "file": {"filename": name, "file_data": url}})
            if o["openrouter_pdf_engine"] and any(m == "application/pdf" for m, _, _ in doc.files):
                body["plugins"] = [{"id": "file-parser", "pdf": {"engine": o["openrouter_pdf_engine"]}}]
        if o["response_format"] == "json_object":
            body["response_format"] = {"type": "json_object"}
        elif o["response_format"] == "json_schema":
            body["response_format"] = to_openai_response_format(schema)
        body["messages"] = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]
        return body

    def extract(self, schema: dict, doc) -> Reply:
        o = self.options
        key = self.key(o["api_key_env"])
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        j = self.post(o["base_url"].rstrip("/") + "/chat/completions", json=self.body(schema, doc), headers=headers)
        if not j.get("choices"):
            raise TransportError(f"no choices in the response: {str(j.get('error'))[:200]}")
        ch = j["choices"][0]
        usage = j.get("usage") or {}
        cost = usage.get("cost")
        if cost is None:
            cost = self.cost(usage.get("prompt_tokens"), usage.get("completion_tokens"))
        return Reply(raw=(ch.get("message") or {}).get("content"), cost_usd=cost, served_by=j.get("provider"),
                     finish_reason=ch.get("finish_reason"), usage={k: v for k, v in usage.items() if k != "cost"})
