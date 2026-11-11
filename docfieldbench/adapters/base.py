from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field

import httpx


@dataclass
class Reply:
    raw: str | None
    usage: dict = field(default_factory=dict)
    cost_usd: float | None = None              # provider-reported; else computed from `prices`
    served_by: str | None = None
    finish_reason: str | None = None


class TransportError(Exception):
    """The request never produced a reply (network, rate limit, server error). Only these are retried."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class Adapter:
    """Options are keyword arguments from the system config. `describe()` feeds the config hash."""

    def __init__(self, transport=None, timeout: float = 300, prices: dict | None = None, **options):
        self.options = options
        self.timeout = timeout
        self.prices = prices or {}
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def describe(self) -> dict:
        return {k: v for k, v in self.options.items() if not k.endswith("_env")}

    def key(self, env: str | None) -> str | None:
        if not env:
            return None
        k = os.environ.get(env)
        if not k:
            raise TransportError(f"environment variable {env} is not set", retryable=False)
        return k

    def cost(self, input_tokens, output_tokens) -> float | None:
        if not self.prices or input_tokens is None or output_tokens is None:
            return None
        return (input_tokens * self.prices.get("input_per_mtok", 0)
                + output_tokens * self.prices.get("output_per_mtok", 0)) / 1e6

    def post(self, url: str, **kw) -> dict:
        try:
            r = self._client.post(url, **kw)
        except httpx.HTTPError as e:
            raise TransportError(f"{type(e).__name__}: {e}") from e
        if r.status_code != 200:
            retry = r.status_code == 429 or r.status_code >= 500
            raise TransportError(f"http {r.status_code}: {r.text[:200]}", retryable=retry)
        try:
            return r.json()
        except ValueError as e:
            raise TransportError(f"non-JSON response body: {r.text[:200]}") from e

    def extract(self, schema: dict, doc) -> Reply:  # pragma: no cover - interface
        raise NotImplementedError
