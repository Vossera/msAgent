import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from msagent.cli.bootstrap import server, webapp
from msagent.core.constants import CONFIG_LANGGRAPH_FILE_NAME


def _response(
    method: str,
    url: str,
    status_code: int,
    *,
    payload=None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request(method, url),
    )


def test_generate_langgraph_json_writes_server_config(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test", encoding="utf-8")

    server.generate_langgraph_json(tmp_path)

    config_path = tmp_path / CONFIG_LANGGRAPH_FILE_NAME
    payload = json.loads(config_path.read_text(encoding="utf-8"))

    assert payload["dependencies"] == [str(server.MSAGENT_ROOT)]
    assert payload["graphs"]["agent"] == "src/msagent/cli/bootstrap/server.py:get_graph"
    assert payload["http"]["app"] == "src/msagent/cli/bootstrap/server.py:app"
    assert payload["env"] == ".env"


@pytest.mark.asyncio
async def test_wait_for_server_ready_polls_until_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        async def get(self, url: str) -> httpx.Response:
            self.calls += 1
            status_code = 503 if self.calls < 3 else 200
            return _response("GET", url, status_code, payload={})

    async def fake_sleep(_: float) -> None:
        return None

    client = FakeClient()
    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)

    result = await server._wait_for_server_ready(
        client,
        "http://127.0.0.1:2024",
        timeout_seconds=2,
    )

    assert result is True
    assert client.calls == 3


@pytest.mark.asyncio
async def test_upsert_assistant_updates_existing_definition() -> None:
    calls: list[tuple[str, str, dict | None]] = []

    class FakeClient:
        async def post(self, url: str, json=None, timeout=None) -> httpx.Response:
            calls.append(("post", url, json))
            if url.endswith("/assistants/search"):
                return _response(
                    "POST",
                    url,
                    200,
                    payload=[{"assistant_id": "assistant-1"}],
                )
            if url.endswith("/latest"):
                return _response("POST", url, 200, payload={"ok": True})
            raise AssertionError(f"Unexpected POST {url}")

        async def patch(self, url: str, json=None, timeout=None) -> httpx.Response:
            calls.append(("patch", url, json))
            return _response(
                "PATCH",
                url,
                200,
                payload={
                    "assistant_id": "assistant-1",
                    "name": "msagent Assistant",
                    "version": 7,
                },
            )

    assistant, was_updated = await server._upsert_assistant(
        FakeClient(),
        "http://127.0.0.1:2024",
        "msagent Assistant",
        {"graph_id": "agent"},
    )

    assert was_updated is True
    assert assistant == {
        "assistant_id": "assistant-1",
        "name": "msagent Assistant",
        "version": 7,
    }
    assert (
        "patch",
        "http://127.0.0.1:2024/assistants/assistant-1",
        {"graph_id": "agent"},
    ) in calls
    assert (
        "post",
        "http://127.0.0.1:2024/assistants/assistant-1/latest",
        {"version": 7},
    ) in calls


@pytest.mark.asyncio
async def test_get_or_create_thread_prefers_last_thread_when_resuming() -> None:
    calls: list[tuple[str, str, dict | None]] = []

    class FakeClient:
        async def post(self, url: str, json=None) -> httpx.Response:
            calls.append(("post", url, json))
            if url.endswith("/threads/search"):
                return _response(
                    "POST",
                    url,
                    200,
                    payload=[{"thread_id": "thread-existing"}],
                )
            raise AssertionError(f"Unexpected POST {url}")

    thread_id = await server._get_or_create_thread(
        FakeClient(),
        "http://127.0.0.1:2024",
        resume=True,
    )

    assert thread_id == "thread-existing"
    assert calls == [
        (
            "post",
            "http://127.0.0.1:2024/threads/search",
            {"limit": 1, "offset": 0},
        )
    ]


@pytest.mark.asyncio
async def test_send_message_posts_to_runs_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    async def fake_get_or_create_thread(client, server_url: str, resume: bool) -> str:
        assert server_url == "http://127.0.0.1:2024"
        assert resume is True
        return "thread-42"

    class FakeClient:
        async def post(self, url: str, json=None) -> httpx.Response:
            calls.append((url, json))
            return _response("POST", url, 200, payload={"ok": True})

    monkeypatch.setattr(server, "_get_or_create_thread", fake_get_or_create_thread)

    exit_code, thread_id = await server._send_message(
        FakeClient(),
        "http://127.0.0.1:2024",
        "assistant-9",
        "分析慢卡根因",
        True,
    )

    assert exit_code == 0
    assert thread_id == "thread-42"
    assert calls == [
        (
            "http://127.0.0.1:2024/threads/thread-42/runs/wait",
            {
                "assistant_id": "assistant-9",
                "input": {"messages": [{"role": "user", "content": "分析慢卡根因"}]},
            },
        )
    ]


@pytest.mark.asyncio
async def test_webapp_lifespan_initializes_graph_and_runs_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_calls: list[str] = []

    async def fake_cleanup() -> None:
        cleanup_calls.append("cleanup")

    async def fake_create_graph(agent, model, working_dir):
        assert agent == "msagent"
        assert model == "default"
        assert working_dir == tmp_path
        return "compiled-graph", fake_cleanup

    app = FastAPI()
    monkeypatch.setenv("MSAGENT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("MSAGENT_AGENT", "msagent")
    monkeypatch.setenv("MSAGENT_MODEL", "default")
    monkeypatch.setattr(webapp.initializer, "create_graph", fake_create_graph)

    async with webapp.lifespan(app):
        assert app.state.graph == "compiled-graph"
        assert app.state.cleanup is fake_cleanup

    assert cleanup_calls == ["cleanup"]


@pytest.mark.asyncio
async def test_webapp_lifespan_requires_working_dir_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MSAGENT_WORKING_DIR", raising=False)

    with pytest.raises(
        ValueError,
        match="MSAGENT_WORKING_DIR environment variable is required",
    ):
        async with webapp.lifespan(FastAPI()):
            pass
