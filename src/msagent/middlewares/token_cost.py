"""Middleware for tracking token usage."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

from msagent.agents.context import AgentContext
from msagent.agents.state import AgentState
from msagent.core.logging import get_logger

if TYPE_CHECKING:
    from langgraph.runtime import Runtime

logger = get_logger(__name__)


def _normalize_token_value(value: Any) -> int | None:
    """Convert a token-like value to int when possible."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def _extract_nested_token_value(
    payload: Any,
    keys: tuple[str, ...],
    *,
    visited: set[int] | None = None,
) -> int | None:
    """Recursively extract a token value from common provider metadata shapes."""
    if payload is None:
        return None

    if visited is None:
        visited = set()

    payload_id = id(payload)
    if payload_id in visited:
        return None
    visited.add(payload_id)

    if isinstance(payload, Mapping):
        for key in keys:
            value = _normalize_token_value(payload.get(key))
            if value is not None:
                return value

        for nested_key in ("usage_metadata", "token_usage", "usage"):
            nested_value = _extract_nested_token_value(
                payload.get(nested_key), keys, visited=visited
            )
            if nested_value is not None:
                return nested_value

        return None

    for key in keys:
        value = _normalize_token_value(getattr(payload, key, None))
        if value is not None:
            return value

    for nested_key in ("usage_metadata", "token_usage", "usage"):
        nested_value = _extract_nested_token_value(
            getattr(payload, nested_key, None), keys, visited=visited
        )
        if nested_value is not None:
            return nested_value

    return None


def _extract_usage_counts(message: AIMessage) -> tuple[int, int] | None:
    """Extract input/output token counts from standardized and provider metadata."""
    candidates = [
        getattr(message, "usage_metadata", None),
        getattr(message, "response_metadata", None),
        getattr(message, "additional_kwargs", None),
    ]

    input_keys = (
        "input_tokens",
        "prompt_tokens",
        "prompt_token_count",
        "inputTokenCount",
        "prompt_eval_count",
    )
    output_keys = (
        "output_tokens",
        "completion_tokens",
        "completion_token_count",
        "outputTokenCount",
        "candidates_token_count",
        "eval_count",
    )
    total_keys = (
        "total_tokens",
        "total_token_count",
        "totalTokenCount",
    )

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    for candidate in candidates:
        if input_tokens is None:
            input_tokens = _extract_nested_token_value(candidate, input_keys)
        if output_tokens is None:
            output_tokens = _extract_nested_token_value(candidate, output_keys)
        if total_tokens is None:
            total_tokens = _extract_nested_token_value(candidate, total_keys)

    if total_tokens is not None:
        if input_tokens is not None and output_tokens is None:
            remainder = total_tokens - input_tokens
            output_tokens = remainder if remainder >= 0 else 0
        elif output_tokens is not None and input_tokens is None:
            remainder = total_tokens - output_tokens
            input_tokens = remainder if remainder >= 0 else 0

    if input_tokens is None and output_tokens is None:
        return None

    return input_tokens or 0, output_tokens or 0


class TokenCostMiddleware(AgentMiddleware[AgentState, AgentContext]):
    """Middleware to track token usage.

    Extracts usage metadata from model responses and updates state with:
    - current_input_tokens: Input tokens for this call
    - current_output_tokens: Output tokens accumulated for the turn
    """

    state_schema = AgentState

    async def aafter_model(
        self, state: AgentState, runtime: Runtime[AgentContext]
    ) -> dict[str, Any] | None:
        """Extract usage metadata after each model call."""
        messages = state.get("messages", [])
        if not messages:
            return None

        latest_message = messages[-1]
        if not isinstance(latest_message, AIMessage):
            return None

        usage_counts = _extract_usage_counts(latest_message)
        if usage_counts is None:
            return None

        input_tokens, output_tokens = usage_counts

        update: dict[str, Any] = {
            "current_input_tokens": input_tokens,
            "current_output_tokens": output_tokens,
        }
        logger.debug("Token usage: %s in, %s out", input_tokens, output_tokens)

        return update
