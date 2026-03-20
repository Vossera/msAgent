from __future__ import annotations

import logging
from types import MethodType, SimpleNamespace
from pathlib import Path

import httpx
import pytest
from openai import APIConnectionError

from msagent.cli.dispatchers import messages as message_module
from msagent.cli.dispatchers.messages import MessageDispatcher
from msagent.configs import ApprovalMode, LLMConfig, LLMProvider


def _build_session(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        prefilled_reference_mapping={},
        current_stream_task=None,
        context=SimpleNamespace(
            approval_mode=ApprovalMode.ACTIVE,
            working_dir=tmp_path,
            thread_id="thread-1",
            recursion_limit=80,
            tool_output_max_tokens=None,
            stream_output=False,
            agent="msagent",
            model="default",
        ),
        graph=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_dispatch_logs_detailed_connection_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _build_session(tmp_path)
    dispatcher = MessageDispatcher(session)
    printed_errors: list[str] = []

    monkeypatch.setattr(
        dispatcher.message_builder,
        "build",
        lambda content: (content, {}),
    )

    async def fake_load_user_memory(_working_dir: Path) -> str:
        return ""

    async def fake_load_llm_config(_model: str, _working_dir: Path) -> LLMConfig:
        return LLMConfig(
            provider=LLMProvider.OPENAI,
            model="deepseek-chat",
            alias="default",
            base_url="https://api.deepseek.com/v1",
            max_tokens=4096,
            temperature=0.0,
        )

    async def fake_invoke_without_stream(self, *_args, **_kwargs) -> None:
        request = httpx.Request(
            "POST",
            "https://api.deepseek.com/v1/chat/completions",
        )
        try:
            raise httpx.ConnectError("all connection attempts failed", request=request)
        except httpx.ConnectError as err:
            raise APIConnectionError(request=request) from err

    monkeypatch.setattr(message_module.initializer, "load_user_memory", fake_load_user_memory)
    monkeypatch.setattr(message_module.initializer, "load_llm_config", fake_load_llm_config)
    monkeypatch.setattr(
        dispatcher,
        "_invoke_without_stream",
        MethodType(fake_invoke_without_stream, dispatcher),
    )
    monkeypatch.setattr(message_module.console, "print_error", printed_errors.append)
    monkeypatch.setattr(message_module.console, "print", lambda *args, **kwargs: None)

    with caplog.at_level(logging.ERROR, logger=message_module.logger.name):
        await dispatcher.dispatch("hello")

    assert printed_errors == [
        "Error processing message: Connection error. Cause: ConnectError: all connection attempts failed"
    ]
    assert "Message processing error [thread_id=thread-1" in caplog.text
    assert "provider=openai" in caplog.text
    assert "resolved_model=deepseek-chat" in caplog.text
    assert "base_url=https://api.deepseek.com/v1" in caplog.text
    assert "request=POST https://api.deepseek.com/v1/chat/completions" in caplog.text
    assert (
        "exception_chain=APIConnectionError: Connection error. <- "
        "ConnectError: all connection attempts failed"
    ) in caplog.text
