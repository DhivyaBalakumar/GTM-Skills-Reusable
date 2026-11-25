"""Thin Claude wrapper for GTM agents: JSON-only outputs, schema validation,
retries, and an offline mock so pipelines/tests run without an API key.

Set ANTHROPIC_API_KEY to call Claude. Set GTM_LLM_MOCK=1 to force the mock.
Model is configurable via CLAUDE_MODEL.
"""
from __future__ import annotations

import json
import os
import re
import time

DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")


class LLMError(Exception):
    pass


def _extract_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise LLMError(f"No JSON in model output: {text[:200]}")
    return json.loads(text[start:])


def _check_schema(obj: dict, required: dict[str, type]) -> None:
    missing = [k for k in required if k not in obj]
    wrong = [k for k, t in required.items() if k in obj and not isinstance(obj[k], t)]
    if missing or wrong:
        raise LLMError(f"Schema mismatch. missing={missing} wrong_type={wrong}")


def complete_json(system: str, user: str, required: dict[str, type], mock: dict | None = None,
                  model: str | None = None, max_tokens: int = 2000, retries: int = 2) -> dict:
    """Ask Claude for a JSON object with the `required` keys/types. Retries on bad JSON."""
    if os.environ.get("GTM_LLM_MOCK") == "1" or not os.environ.get("ANTHROPIC_API_KEY"):
        if mock is None:
            raise LLMError("No ANTHROPIC_API_KEY and no mock provided")
        _check_schema(mock, required)
        return mock

    import anthropic  # pip install anthropic

    client = anthropic.Anthropic()
    msgs = [{"role": "user", "content": user}]
    last = None
    for attempt in range(retries + 1):
        text = ""
        try:
            resp = client.messages.create(model=model or DEFAULT_MODEL, max_tokens=max_tokens,
                                          system=system + "\n\nRespond with ONLY a JSON object. No prose.",
                                          messages=msgs)
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            obj = _extract_json(text)
            _check_schema(obj, required)
            return obj
        except (LLMError, json.JSONDecodeError) as e:
            last = e
            msgs = msgs[:1] + [{"role": "assistant", "content": text or "(empty)"},
                               {"role": "user", "content": f"That was invalid: {e}. Return ONLY the corrected JSON."}]
        except anthropic.RateLimitError as e:
            last = e
            time.sleep(2 ** attempt * 5)
    raise LLMError(f"Claude did not return valid JSON after {retries + 1} attempts: {last}")
