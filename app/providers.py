"""Model-agnostic LLM provider interface.

Default is no LLM at all ("local"): the app still works with rules + retrieval.
Cloud providers are opt-in: they need COMPANION_CLOUD_OPT_IN=1 *and* an API key in the environment.
Keys are never written to disk or returned by the API. Cloud use is a *real* integration but is NOT
covered by live tests in this repo (no key was available); it is tested against a mocked transport.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


@dataclass
class Completion:
    text: str
    tokens_in: int
    tokens_out: int


class ProviderError(Exception):
    pass


class Provider:
    name = "local"
    is_cloud = False
    available = False

    def complete(self, system: str, user: str, max_tokens: int = 400) -> Completion:  # pragma: no cover
        raise ProviderError("no LLM provider configured")

    def describe(self) -> dict:
        return {"name": self.name, "cloud": self.is_cloud, "available": self.available}


class HTTPProvider(Provider):
    """OpenAI-compatible (`kind='openai'`) or Anthropic Messages (`kind='anthropic'`) endpoint."""
    is_cloud = True
    available = True

    def __init__(self, kind: str, base_url: str, api_key: str, model: str, client: httpx.Client | None = None,
                 timeout: float = 20.0):
        self.kind, self.base_url, self._key, self.model = kind, base_url.rstrip("/"), api_key, model
        self.name = f"{kind}:{model}"
        self.client = client or httpx.Client(timeout=timeout)

    def complete(self, system: str, user: str, max_tokens: int = 400) -> Completion:
        try:
            if self.kind == "anthropic":
                r = self.client.post(f"{self.base_url}/v1/messages", headers={
                    "x-api-key": self._key, "anthropic-version": "2023-06-01"}, json={
                    "model": self.model, "max_tokens": max_tokens, "system": system,
                    "messages": [{"role": "user", "content": user}]})
                r.raise_for_status()
                d = r.json()
                text = "".join(b.get("text", "") for b in d.get("content", []))
                u = d.get("usage", {})
                return Completion(text.strip(), u.get("input_tokens", 0), u.get("output_tokens", 0))
            r = self.client.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self._key}"}, json={
                "model": self.model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            r.raise_for_status()
            d = r.json()
            u = d.get("usage", {})
            return Completion(d["choices"][0]["message"]["content"].strip(), u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise ProviderError(f"{type(e).__name__}: {e}") from e

    def describe(self) -> dict:
        return {"name": self.name, "cloud": True, "available": True}


def provider_from_env(env=os.environ) -> Provider:
    kind = env.get("COMPANION_PROVIDER", "local").lower()
    if kind == "local":
        return Provider()
    if env.get("COMPANION_CLOUD_OPT_IN") != "1":
        raise SystemExit("Cloud provider requested but COMPANION_CLOUD_OPT_IN=1 is not set (cloud processing is opt-in).")
    key = env.get("COMPANION_API_KEY", "")
    if not key:
        raise SystemExit("COMPANION_API_KEY is required for a cloud provider.")
    model = env.get("COMPANION_MODEL", "")
    if not model:
        raise SystemExit("COMPANION_MODEL is required for a cloud provider.")
    if kind == "anthropic":
        return HTTPProvider("anthropic", env.get("COMPANION_BASE_URL", "https://api.anthropic.com"), key, model)
    if kind in ("openai", "openai_compat"):
        return HTTPProvider("openai", env.get("COMPANION_BASE_URL", "https://api.openai.com/v1"), key, model)
    raise SystemExit(f"Unknown COMPANION_PROVIDER: {kind}")
