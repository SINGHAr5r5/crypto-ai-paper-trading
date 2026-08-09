"""Calls Claude (via OpenRouter) for the AI decision layer (spec §6).

Uses OpenRouter instead of the Anthropic API directly because that's where a
funded key was available; swap API_URL/HEADERS/payload shape if moving to a
direct Anthropic key later (see git history for the direct-API version).
"""

import json
import os
import re

import requests

from src.ai.schema import InvalidDecision, validate_decision

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-4.5"


class ClaudeCallFailed(Exception):
    pass


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    return json.loads(text)


def get_decision(system_prompt: str, user_content: str) -> dict:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ClaudeCallFailed("OPENROUTER_API_KEY not set")

    try:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 700,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            },
            timeout=30,
        )
    except requests.RequestException as e:
        raise ClaudeCallFailed(f"request error: {e}")

    if resp.status_code != 200:
        raise ClaudeCallFailed(f"HTTP {resp.status_code}: {resp.text[:300]}")

    body = resp.json()
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise ClaudeCallFailed(f"unexpected response shape: {body}")

    try:
        decision = _extract_json(text)
    except json.JSONDecodeError as e:
        raise ClaudeCallFailed(f"non-JSON response: {e}: {text[:300]}")

    try:
        decision = validate_decision(decision)
    except InvalidDecision as e:
        raise ClaudeCallFailed(f"invalid decision schema: {e}")

    decision["_model_version"] = body.get("model", MODEL)
    return decision
