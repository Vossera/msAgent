import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import ToolException
from pydantic import BaseModel

from msagent.skills.factory import Skill
from msagent.tools.catalog.skills import fetch_skills, get_skill
from msagent.tools.catalog.tools import fetch_tools, get_tool, run_tool


class RuntimeArgs(BaseModel):
    query: str
    runtime: object | None = None


def _make_runtime(*, tools=None, skills=None):
    return SimpleNamespace(
        context=SimpleNamespace(
            tool_catalog=list(tools or []),
            skill_catalog=list(skills or []),
        )
    )


@pytest.mark.asyncio
async def test_fetch_tools_filters_by_name_and_description() -> None:
    tools = [
        SimpleNamespace(
            name="read_file",
            description="Read a file from disk",
            tool_call_schema={"type": "object", "properties": {}},
            args_schema=None,
        ),
        SimpleNamespace(
            name="web_fetch",
            description="Fetch content from the web",
            tool_call_schema={"type": "object", "properties": {}},
            args_schema=None,
        ),
    ]

    result = await fetch_tools.coroutine(
        runtime=_make_runtime(tools=tools),
        pattern="web|disk",
    )

    assert result.splitlines() == ["read_file", "web_fetch"]


@pytest.mark.asyncio
async def test_fetch_tools_rejects_invalid_regex() -> None:
    with pytest.raises(ToolException, match="Invalid regex pattern"):
        await fetch_tools.coroutine(runtime=_make_runtime(tools=[]), pattern="(")


@pytest.mark.asyncio
async def test_get_tool_returns_json_schema_for_tool() -> None:
    tool = SimpleNamespace(
        name="search",
        description="Search indexed traces",
        tool_call_schema=RuntimeArgs,
        args_schema=RuntimeArgs,
    )

    result = await get_tool.coroutine(
        tool_name="search",
        runtime=_make_runtime(tools=[tool]),
    )
    payload = json.loads(result)

    assert payload["name"] == "search"
    assert payload["description"] == "Search indexed traces"
    assert "query" in payload["parameters"]["properties"]


@pytest.mark.asyncio
async def test_run_tool_injects_runtime_when_tool_accepts_it() -> None:
    invoke = AsyncMock(return_value="ok")
    tool = SimpleNamespace(
        name="search",
        description="Search indexed traces",
        tool_call_schema=RuntimeArgs,
        args_schema=RuntimeArgs,
        ainvoke=invoke,
    )
    runtime = _make_runtime(tools=[tool])

    result = await run_tool.coroutine(
        tool_name="search",
        tool_args={"query": "slow rank"},
        runtime=runtime,
    )

    assert result == "ok"
    invoke.assert_awaited_once()
    call_args = invoke.await_args.args[0]
    assert call_args["query"] == "slow rank"
    assert call_args["runtime"] is runtime


@pytest.mark.asyncio
async def test_fetch_skills_returns_display_name_and_filters(tmp_path: Path) -> None:
    skills = [
        Skill(
            name="cluster-fast-slow-rank-detector",
            description="Detect slow ranks in distributed runs",
            category="analysis",
            path=tmp_path / "analysis" / "cluster-fast-slow-rank-detector" / "SKILL.md",
        ),
        Skill(
            name="op-mfu-calculator",
            description="Compute operator MFU",
            category="default",
            path=tmp_path / "op-mfu-calculator" / "SKILL.md",
        ),
    ]

    result = await fetch_skills.coroutine(
        runtime=_make_runtime(skills=skills),
        pattern="analysis|mfu",
    )
    payload = json.loads(result)

    assert payload == [
        {
            "display_name": "analysis/cluster-fast-slow-rank-detector",
            "category": "analysis",
            "name": "cluster-fast-slow-rank-detector",
            "description": "Detect slow ranks in distributed runs",
        },
        {
            "display_name": "op-mfu-calculator",
            "category": "default",
            "name": "op-mfu-calculator",
            "description": "Compute operator MFU",
        },
    ]


@pytest.mark.asyncio
async def test_get_skill_requires_category_when_names_are_duplicated(
    tmp_path: Path,
) -> None:
    alpha_dir = tmp_path / "analysis" / "shared-skill"
    beta_dir = tmp_path / "debug" / "shared-skill"
    alpha_dir.mkdir(parents=True)
    beta_dir.mkdir(parents=True)
    (alpha_dir / "SKILL.md").write_text(
        "---\nname: shared-skill\ndescription: analysis skill\n---\nalpha",
        encoding="utf-8",
    )
    (beta_dir / "SKILL.md").write_text(
        "---\nname: shared-skill\ndescription: debug skill\n---\nbeta",
        encoding="utf-8",
    )

    skills = [
        Skill(
            name="shared-skill",
            description="analysis skill",
            category="analysis",
            path=alpha_dir / "SKILL.md",
        ),
        Skill(
            name="shared-skill",
            description="debug skill",
            category="debug",
            path=beta_dir / "SKILL.md",
        ),
    ]

    with pytest.raises(ToolException, match="Specify category: analysis, debug"):
        await get_skill.coroutine(
            name="shared-skill",
            runtime=_make_runtime(skills=skills),
        )


@pytest.mark.asyncio
async def test_get_skill_reads_selected_skill_content(tmp_path: Path) -> None:
    skill_dir = tmp_path / "analysis" / "rank-detector"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\nname: rank-detector\ndescription: detect slow ranks\n---\nrun steps",
        encoding="utf-8",
    )
    skill = Skill(
        name="rank-detector",
        description="detect slow ranks",
        category="analysis",
        path=skill_path,
    )

    result = await get_skill.coroutine(
        name="rank-detector",
        category="analysis",
        runtime=_make_runtime(skills=[skill]),
    )

    assert "run steps" in result
