"""Application service layer for msagent frontends."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Literal

from .interfaces import AgentBackend, AgentEvent, AgentStatus

UserIntentType = Literal[
    "chat",
    "clear",
    "new_session",
    "exit",
    "ignore",
    "backend_status",
    "backend_switch",
]


@dataclass(frozen=True, slots=True)
class UserIntent:
    """Parsed user intent from raw input."""

    type: UserIntentType
    message: str = ""


class ChatApplicationService:
    """Coordinates frontend actions with backend use-cases."""

    _EXIT_COMMANDS = frozenset({"/exit"})
    _CLEAR_COMMANDS = frozenset({"/clear"})
    _NEW_SESSION_COMMANDS = frozenset({"/new"})
    _BACKEND_STATUS_COMMANDS = frozenset({"/backend", "/backend status", "/shell", "/shell status"})
    _BACKEND_SWITCH_MAP = {
        "/backend filesystem": "filesystem",
        "/backend local_shell": "local_shell",
        "/shell on": "local_shell",
        "/shell off": "filesystem",
    }
    _COMMAND_HELP: tuple[tuple[str, str], ...] = (
        ("/new", "开启新会话并清空上下文"),
        ("/clear", "清空当前会话历史"),
        ("/backend status", "查看当前 deepagents backend"),
        ("/backend filesystem", "切换到 FilesystemBackend"),
        ("/backend local_shell", "切换到 LocalShellBackend（高风险）"),
        ("/shell on", "开启 LocalShellBackend（高风险）"),
        ("/shell off", "关闭 LocalShellBackend"),
        ("/exit", "退出 msAgent"),
    )

    def __init__(self, backend: AgentBackend):
        self._backend = backend

    @property
    def backend(self) -> AgentBackend:
        return self._backend

    async def initialize(self) -> bool:
        return await self._backend.initialize()

    async def shutdown(self) -> None:
        await self._backend.shutdown()

    def get_status(self) -> AgentStatus:
        return self._backend.get_status()

    def get_status_message(self) -> str:
        status = self._backend.get_status()
        backend_mode = status.backend_mode
        backend_name = (
            "LocalShellBackend" if backend_mode == "local_shell" else "FilesystemBackend"
        )
        lines = [f"当前 deepagents backend：{backend_name} ({backend_mode})。"]
        if backend_mode == "local_shell":
            lines.append("⚠️ `execute` 会直接在当前机器上执行 shell 命令，没有沙箱隔离。")
        else:
            lines.append("当前未启用宿主机 shell 执行能力。")
        lines.append(
            "命令：/backend filesystem | /backend local_shell | /shell on | /shell off"
        )
        return "\n".join(lines)

    def resolve_user_input(self, raw_input: str) -> UserIntent:
        text = raw_input.strip()
        if not text:
            return UserIntent("ignore")

        normalized = " ".join(text.lower().split())
        if normalized in self._EXIT_COMMANDS:
            return UserIntent("exit")
        if normalized in self._CLEAR_COMMANDS:
            return UserIntent("clear")
        if normalized in self._NEW_SESSION_COMMANDS:
            return UserIntent("new_session")
        if normalized in self._BACKEND_STATUS_COMMANDS:
            return UserIntent("backend_status")
        backend_mode = self._BACKEND_SWITCH_MAP.get(normalized)
        if backend_mode is not None:
            return UserIntent("backend_switch", message=backend_mode)
        return UserIntent("chat", message=text)

    async def chat(self, user_input: str) -> str:
        return await self._backend.chat(user_input)

    async def chat_stream(self, user_input: str) -> AsyncGenerator[str, None]:
        async for chunk in self._backend.chat_stream(user_input):
            yield chunk

    async def stream_chat_events(self, user_input: str) -> AsyncGenerator[AgentEvent, None]:
        async for event in self._backend.stream_chat_events(user_input):
            yield event

    def clear_history(self) -> None:
        self._backend.clear_history()

    def start_new_session(self) -> int:
        return self._backend.start_new_session()

    def switch_deepagents_backend(self, mode: str) -> str:
        return self._backend.switch_deepagents_backend(mode)

    def find_local_files(self, query: str, limit: int = 8) -> list[str]:
        return self._backend.find_local_files(query, limit=limit)

    def find_commands(self, query: str, limit: int = 8) -> list[tuple[str, str]]:
        normalized_query = " ".join(query.strip().lower().split())
        if not normalized_query:
            return list(self._COMMAND_HELP[:limit])

        scored: list[tuple[int, int, str, str]] = []
        for idx, (command, description) in enumerate(self._COMMAND_HELP):
            normalized_command = " ".join(command.lower().split())
            if normalized_command == normalized_query:
                score = 0
            elif normalized_command.startswith(normalized_query):
                score = 1
            elif normalized_query in normalized_command:
                score = 2
            else:
                continue
            scored.append((score, idx, command, description))

        scored.sort(key=lambda item: (item[0], item[1], len(item[2]), item[2]))
        return [(command, description) for _, _, command, description in scored[:limit]]
