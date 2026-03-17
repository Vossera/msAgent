import asyncio

from langchain_core.messages import AIMessage

from msagent.middlewares.token_cost import TokenCostMiddleware


def test_token_cost_middleware_reads_standard_usage_metadata() -> None:
    middleware = TokenCostMiddleware()
    state = {
        "messages": [
            AIMessage(
                content="done",
                usage_metadata={
                    "input_tokens": 321,
                    "output_tokens": 45,
                    "total_tokens": 366,
                },
            )
        ]
    }

    result = asyncio.run(middleware.aafter_model(state, None))  # type: ignore[arg-type]

    assert result == {
        "current_input_tokens": 321,
        "current_output_tokens": 45,
    }


def test_token_cost_middleware_reads_openai_style_response_metadata() -> None:
    middleware = TokenCostMiddleware()
    state = {
        "messages": [
            AIMessage(
                content="done",
                response_metadata={
                    "token_usage": {
                        "prompt_tokens": 2048,
                        "completion_tokens": 256,
                        "total_tokens": 2304,
                    }
                },
            )
        ]
    }

    result = asyncio.run(middleware.aafter_model(state, None))  # type: ignore[arg-type]

    assert result == {
        "current_input_tokens": 2048,
        "current_output_tokens": 256,
    }


def test_token_cost_middleware_reads_ollama_style_response_metadata() -> None:
    middleware = TokenCostMiddleware()
    state = {
        "messages": [
            AIMessage(
                content="done",
                response_metadata={
                    "prompt_eval_count": 987,
                    "eval_count": 123,
                },
            )
        ]
    }

    result = asyncio.run(middleware.aafter_model(state, None))  # type: ignore[arg-type]

    assert result == {
        "current_input_tokens": 987,
        "current_output_tokens": 123,
    }


def test_token_cost_middleware_uses_total_tokens_as_fallback() -> None:
    middleware = TokenCostMiddleware()
    state = {
        "messages": [
            AIMessage(
                content="done",
                response_metadata={
                    "usage": {
                        "prompt_tokens": 1500,
                        "total_tokens": 1630,
                    }
                },
            )
        ]
    }

    result = asyncio.run(middleware.aafter_model(state, None))  # type: ignore[arg-type]

    assert result == {
        "current_input_tokens": 1500,
        "current_output_tokens": 130,
    }


def test_token_cost_middleware_returns_none_without_usage_data() -> None:
    middleware = TokenCostMiddleware()
    state = {"messages": [AIMessage(content="done")]}

    result = asyncio.run(middleware.aafter_model(state, None))  # type: ignore[arg-type]

    assert result is None
