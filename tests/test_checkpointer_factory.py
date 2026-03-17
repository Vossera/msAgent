from contextlib import asynccontextmanager

import pytest

from msagent.checkpointer.factory import CheckpointerFactory
from msagent.checkpointer.impl.memory import MemoryCheckpointer
from msagent.checkpointer.impl.sqlite import AsyncSqliteCheckpointer
from msagent.configs import CheckpointerConfig, CheckpointerProvider


@pytest.mark.asyncio
async def test_memory_checkpointer_is_reused_across_calls() -> None:
    factory = CheckpointerFactory()
    config = CheckpointerConfig(type=CheckpointerProvider.MEMORY)

    async with factory.create(config, ":memory:") as first:
        async with factory.create(config, ":memory:") as second:
            assert isinstance(first, MemoryCheckpointer)
            assert first is second


@pytest.mark.asyncio
async def test_sqlite_checkpointer_factory_delegates_to_async_creator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = CheckpointerFactory()
    config = CheckpointerConfig(type=CheckpointerProvider.SQLITE)
    captured: dict[str, str] = {}
    sentinel = object()

    @asynccontextmanager
    async def fake_create(connection_string: str):
        captured["connection_string"] = connection_string
        yield sentinel

    monkeypatch.setattr(AsyncSqliteCheckpointer, "create", fake_create)

    async with factory.create(config, "sqlite:///tmp/msagent.db") as checkpointer:
        assert checkpointer is sentinel

    assert captured["connection_string"] == "sqlite:///tmp/msagent.db"
