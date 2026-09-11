"""Thin, swappable wrapper around the Claude API.

Two rules this wrapper exists to enforce:

* **No cross-tenant data ever enters a prompt.** Every call carries the
  Organization it belongs to, and callers hand over already-scoped, structured
  signals.
* **The LLM never executes anything.** It returns text or a structured
  proposal; execution always goes through our own code behind an explicit
  user confirmation (Section 9).

Phase 1 ships the interface and a deterministic offline fallback so the rest
of the system can be built and tested without an API key.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import settings

logger = logging.getLogger("fleetbeat.ai")


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    #: True when produced by the offline fallback rather than the Claude API.
    fallback: bool = False
    raw: dict[str, Any] | None = None


class ClaudeClient:
    """Minimal async client. Phase 5 wires the real HTTP call."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.anthropic_model

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def complete(
        self,
        *,
        organization_id: uuid.UUID,
        system: str,
        prompt: str,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self.is_configured:
            logger.info(
                "ANTHROPIC_API_KEY is not set - returning the offline fallback "
                "for organization %s",
                organization_id,
            )
            return LLMResponse(
                text=_offline_fallback(prompt), model="offline", fallback=True
            )
        raise NotImplementedError(
            "The Claude API call is wired up in Phase 5 (Section 5, item 3)."
        )


def _offline_fallback(prompt: str) -> str:
    return (
        "AI narration is unavailable (no ANTHROPIC_API_KEY configured). "
        "The underlying figures below were computed by FleetBeat's own "
        "rule-based analysis and are unaffected.\n\n" + prompt.strip()[:1500]
    )


_client: ClaudeClient | None = None


def get_claude_client() -> ClaudeClient:
    global _client
    if _client is None:
        _client = ClaudeClient()
    return _client


def set_claude_client(client: ClaudeClient) -> None:
    """Swap the client (tests, or a different provider later)."""
    global _client
    _client = client
