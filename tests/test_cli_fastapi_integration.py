import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from msagent.cli.bootstrap import app as cli_app
from msagent.cli.bootstrap import chat, server, webapp
from msagent.cli.core.context import Context
from msagent.configs import ApprovalMode


def _build_context(tmp_path: Path, **overrides) -> Context:
    data = {
        "agent": "msagent",
        "model": "default",
        "model_display": "deepseek-chat (openai)",
        "thread_id": "thread-1",
        "working_dir": tmp_path,
        "approval_mode": ApprovalMode.ACTIVE,
        "recursion_limit": 80,
        "stream_output": True,
    }
    data.update(overrides)
    return Context(**data)


@pytest.mark.asyncio
async def test_main_routes_bare_invocation_to_session_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_configure_logging(*, show_logs: bool, working_dir: Path) -> None:
        captured["show_logs"] = show_logs
        captured["working_dir"] = working_dir

    async def fake_dispatch(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 0

    monkeypatch.setattr(cli_app, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(cli_app, "dispatch_legacy_command", fake_dispatch)
    monkeypatch.setattr(
        cli_app.sys,
        "argv",
        ["msagent", "--no-stream", "-w", str(tmp_path), "分析慢卡原因"],
    )

    exit_code = await cli_app.main()

    args = captured["args"]
    assert exit_code == 0
    assert isinstance(args, argparse.Namespace)
    assert args.cli_command == "__session__"
    assert args.message == "分析慢卡原因"
    assert args.stream is False
    assert captured["show_logs"] is False
    assert captured["working_dir"] == tmp_path


@pytest.mark.asyncio
async def test_handle_chat_command_one_shot_sends_message_with_resume_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    context = _build_context(tmp_path)

    async def fake_create(**kwargs) -> Context:
        captured["context_kwargs"] = kwargs
        return context

    class FakeSession:
        def __init__(self, runtime_context: Context) -> None:
            captured["session_context"] = runtime_context
            self.needs_reload = False

        async def send(self, message: str, resume_thread_id: str | None = None) -> int:
            captured["message"] = message
            captured["resume_thread_id"] = resume_thread_id
            return 0

    monkeypatch.setattr(chat.Context, "create", fake_create)
    monkeypatch.setattr(chat, "Session", FakeSession)

    args = argparse.Namespace(
        message="给出优化建议",
        timer=False,
        agent="msagent",
        model="default",
        resume=True,
        working_dir=str(tmp_path),
        approval_mode=ApprovalMode.SEMI_ACTIVE.value,
        stream=False,
    )

    exit_code = await chat.handle_chat_command(args)

    assert exit_code == 0
    assert captured["session_context"] is context
    assert captured["message"] == "给出优化建议"
    assert captured["resume_thread_id"] == "thread-1"
    assert captured["context_kwargs"] == {
        "agent": "msagent",
        "model": "default",
        "resume": True,
        "working_dir": tmp_path,
        "approval_mode": ApprovalMode.SEMI_ACTIVE.value,
        "stream_output": False,
    }


@pytest.mark.asyncio
async def test_handle_chat_command_recreates_session_when_reload_is_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _build_context(tmp_path)
    start_calls: list[tuple[bool, str | None]] = []
    created_sessions: list[int] = []

    async def fake_create(**kwargs) -> Context:
        return context

    class FakeSession:
        def __init__(self, runtime_context: Context) -> None:
            assert runtime_context is context
            self.index = len(created_sessions)
            self.needs_reload = False
            created_sessions.append(self.index)

        async def start(
            self,
            *,
            show_welcome: bool,
            resume_thread_id: str | None = None,
        ) -> None:
            start_calls.append((show_welcome, resume_thread_id))
            self.needs_reload = self.index == 0

    monkeypatch.setattr(chat.Context, "create", fake_create)
    monkeypatch.setattr(chat, "Session", FakeSession)

    args = argparse.Namespace(
        message=None,
        timer=False,
        agent="msagent",
        model=None,
        resume=True,
        working_dir=str(tmp_path),
        approval_mode=ApprovalMode.ACTIVE.value,
        stream=True,
    )

    exit_code = await chat.handle_chat_command(args)

    assert exit_code == 0
    assert created_sessions == [0, 1]
    assert start_calls == [
        (False, "thread-1"),
        (False, None),
    ]


@pytest.mark.asyncio
async def test_handle_server_command_runs_end_to_end_happy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    working_dir = tmp_path / "workspace"
    langgraph_bin = tmp_path / "bin" / "langgraph"
    python_bin = tmp_path / "bin" / "python"
    git_exclude = working_dir / ".git" / "info" / "exclude"
    working_dir.mkdir(parents=True)
    git_exclude.parent.mkdir(parents=True)
    langgraph_bin.parent.mkdir(parents=True)
    python_bin.write_text("", encoding="utf-8")
    langgraph_bin.write_text("", encoding="utf-8")

    captured: dict[str, object] = {}

    async def fake_load_agent_config(agent: str | None, directory: Path):
        captured["load_agent"] = (agent, directory)
        return SimpleNamespace(name="msagent")

    async def fake_load_llm_config(model: str, directory: Path):
        captured["load_llm"] = (model, directory)
        return SimpleNamespace(alias=model)

    async def fake_wait_for_server_ready(client, server_url: str) -> bool:
        captured["ready_url"] = server_url
        return True

    async def fake_upsert_assistant(client, server_url: str, name: str, config: dict):
        captured["assistant_name"] = name
        captured["assistant_config"] = config
        return (
            {
                "assistant_id": "assistant-1",
                "name": name,
                "version": 3,
            },
            False,
        )

    async def fake_send_message(
        client,
        server_url: str,
        assistant_id: str,
        message: str,
        resume: bool,
    ) -> tuple[int, str]:
        captured["sent_message"] = (server_url, assistant_id, message, resume)
        return 0, "thread-9"

    class FakeProcess:
        def __init__(self, command: list[str], cwd: Path, env: dict[str, str]) -> None:
            captured["popen_command"] = command
            captured["popen_cwd"] = cwd
            captured["popen_env"] = env
            self.terminated = False

        def terminate(self) -> None:
            self.terminated = True

        def wait(self) -> int:
            return 0

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(server.initializer, "load_agent_config", fake_load_agent_config)
    monkeypatch.setattr(server.initializer, "load_llm_config", fake_load_llm_config)
    monkeypatch.setattr(server, "_wait_for_server_ready", fake_wait_for_server_ready)
    monkeypatch.setattr(server, "_upsert_assistant", fake_upsert_assistant)
    monkeypatch.setattr(server, "_send_message", fake_send_message)
    monkeypatch.setattr(server.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        lambda command, cwd, env: FakeProcess(command, cwd, env),
    )
    monkeypatch.setattr(server.sys, "executable", str(python_bin))
    monkeypatch.setattr(
        server.settings.server,
        "langgraph_server_url",
        "http://127.0.0.1:2024",
    )

    args = argparse.Namespace(
        working_dir=str(working_dir),
        agent="msagent",
        model="default",
        approval_mode=ApprovalMode.SEMI_ACTIVE.value,
        message="请分析集群慢卡",
        resume=True,
    )

    exit_code = await server.handle_server_command(args)

    langgraph_json = working_dir / ".msagent" / "langgraph.json"

    assert exit_code == 0
    assert captured["load_agent"] == ("msagent", working_dir)
    assert captured["load_llm"] == ("default", working_dir)
    assert captured["ready_url"] == "http://127.0.0.1:2024"
    assert captured["assistant_name"] == "msagent Assistant"
    assert captured["assistant_config"] == {
        "graph_id": "agent",
        "config": {
            "configurable": {
                "approval_mode": ApprovalMode.SEMI_ACTIVE.value,
                "working_dir": str(working_dir),
            }
        },
        "name": "msagent Assistant",
    }
    assert captured["sent_message"] == (
        "http://127.0.0.1:2024",
        "assistant-1",
        "请分析集群慢卡",
        True,
    )
    assert captured["popen_command"] == [
        str(langgraph_bin),
        "dev",
        "--config",
        str(langgraph_json),
    ]
    assert captured["popen_cwd"] == working_dir
    assert captured["popen_env"]["MSAGENT_WORKING_DIR"] == str(working_dir)
    assert captured["popen_env"]["MSAGENT_AGENT"] == "msagent"
    assert captured["popen_env"]["MSAGENT_MODEL"] == "default"
    assert langgraph_json.exists()
    assert ".langgraph_api/" in git_exclude.read_text(encoding="utf-8")


def test_fastapi_app_lifespan_runs_via_testclient(
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

    monkeypatch.setenv("MSAGENT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("MSAGENT_AGENT", "msagent")
    monkeypatch.setenv("MSAGENT_MODEL", "default")
    monkeypatch.setattr(webapp.initializer, "create_graph", fake_create_graph)

    with TestClient(webapp.app) as client:
        response = client.get("/")
        assert response.status_code == 404
        assert asyncio.run(server.get_graph()) == "compiled-graph"
        assert webapp.app.state.graph == "compiled-graph"

    assert cleanup_calls == ["cleanup"]
