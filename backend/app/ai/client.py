"""Claude API wrapper for the AI layer (Section 5).

Three rules this wrapper exists to enforce, so no feature has to remember
them:

* **No cross-tenant data ever enters a prompt.** Every call carries the
  Organization it belongs to, and callers hand over already-scoped,
  structured signals rather than raw query access.
* **The model never executes anything.** It returns text or a structured
  proposal; execution always goes through our own code behind an explicit
  user confirmation (Section 9).
* **An unavailable model is never a broken feature.** Without an API key -
  or when a call fails - every caller gets a deterministic offline result
  built from the same rule-derived facts, so the numbers on screen stay
  correct and only the prose is missing.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

logger = logging.getLogger("fleetbeat.ai")

#: Opus 5 refuses rather than answering when a request trips a safety
#: classifier. Server-side fallbacks route those to another model instead of
#: surfacing an error, and cost nothing when they do not fire.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    #: True when produced by the offline fallback rather than the Claude API.
    fallback: bool = False
    #: Parsed JSON when the call requested a structured output.
    data: dict[str, Any] | None = None
    usage: dict[str, int] = field(default_factory=dict)


class ClaudeClient:
    """Thin async wrapper over the Anthropic SDK."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.anthropic_model
        self._client: Any | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _sdk(self) -> Any:
        if self._client is None:
            # Imported lazily so the whole app still starts, and every test
            # still runs, without the SDK installed.
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def complete(
        self,
        *,
        organization_id: uuid.UUID,
        system: str,
        prompt: str,
        max_tokens: int = 2048,
        json_schema: dict[str, Any] | None = None,
        offline_text: str | None = None,
        effort: str = "medium",
    ) -> LLMResponse:
        """One request. Returns prose, or validated JSON when a schema is given.

        ``offline_text`` is what callers get when the API is unavailable - it
        should be a usable, rule-derived summary, not an apology.
        """
        if not self.is_configured:
            logger.info(
                "ANTHROPIC_API_KEY is not set - using the offline result for "
                "organization %s",
                organization_id,
            )
            return self._offline(offline_text, json_schema)

        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            # Adaptive thinking: these are judgement calls over structured
            # signals, not lookups.
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort},
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }
        if json_schema is not None:
            request["output_config"]["format"] = {
                "type": "json_schema",
                "schema": json_schema,
            }

        try:
            response = await self._sdk().beta.messages.create(**request)
        except Exception:
            # The AI layer is an enhancement. A provider outage must never
            # take a fleet dashboard down with it.
            logger.exception("Claude request failed; falling back offline")
            return self._offline(offline_text, json_schema)

        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            logger.warning(
                "Claude declined the request (%s)",
                getattr(details, "category", "unknown"),
            )
            return self._offline(offline_text, json_schema)

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()

        data: dict[str, Any] | None = None
        if json_schema is not None and text:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Claude returned unparsable JSON; falling back offline")
                return self._offline(offline_text, json_schema)

        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=text,
            model=getattr(response, "model", self.model),
            data=data,
            usage={
                "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            }
            if usage
            else {},
        )

    def _offline(
        self, offline_text: str | None, json_schema: dict[str, Any] | None
    ) -> LLMResponse:
        return LLMResponse(
            text=offline_text or _DEFAULT_OFFLINE,
            model="offline",
            fallback=True,
            # A schema'd caller gets nothing rather than invented structure:
            # guessing an intent offline is how an assistant does the wrong
            # thing confidently.
            data=None if json_schema is not None else None,
        )


_DEFAULT_OFFLINE = (
    "AI narration is unavailable right now. The figures shown were computed by "
    "FleetBeat's own analysis and are unaffected."
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
