"""Message handling for chat sessions."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from rich.console import Group
from rich.markup import render
from rich.text import Text

from msagent.agents.context import AgentContext
from msagent.cli.bootstrap.initializer import initializer
from msagent.cli.builders import MessageContentBuilder
from msagent.cli.handlers import CompressionHandler, InterruptHandler
from msagent.cli.theme import console, theme
from msagent.core.constants import OS_VERSION, PLATFORM
from msagent.core.logging import get_logger
from msagent.utils.compression import should_auto_compress

if TYPE_CHECKING:
    from langgraph.types import Interrupt

logger = get_logger(__name__)


class MessageDispatcher:
    """Dispatch user message processing and AI response streaming."""

    _MAX_LOG_VALUE_LENGTH = 400

    def __init__(self, session) -> None:
        """Initialize with reference to CLI session."""
        self.session = session
        self.interrupt_handler = InterruptHandler(session=session)
        self.message_builder = MessageContentBuilder(Path(session.context.working_dir))
        self._pending_compression = False

    async def dispatch(self, content: str) -> None:
        """Dispatch user message and get AI response."""
        try:
            reference_mapping = self.session.prefilled_reference_mapping.copy()
            self.session.prefilled_reference_mapping.clear()

            message_content, image_refs = self.message_builder.build(content)

            reference_mapping.update(image_refs)

            human_message = HumanMessage(
                content=message_content,
                short_content=content,
                additional_kwargs={"reference_mapping": reference_mapping},
            )
            ctx = self.session.context
            now = datetime.now(timezone.utc).astimezone()
            user_memory = await initializer.load_user_memory(ctx.working_dir)
            agent_context = AgentContext(
                approval_mode=ctx.approval_mode,
                working_dir=ctx.working_dir,
                platform=PLATFORM,
                os_version=OS_VERSION,
                current_date_time_zoned=now.strftime("%Y-%m-%d %H:%M:%S %Z"),
                mcp_servers=(
                    ", ".join(initializer.cached_mcp_server_names)
                    if initializer.cached_mcp_server_names
                    else "None"
                ),
                user_memory=user_memory,
                tool_catalog=initializer.cached_tools_in_catalog,
                skill_catalog=initializer.cached_agent_skills,
                tool_output_max_tokens=ctx.tool_output_max_tokens,
            )

            graph_config = RunnableConfig(
                configurable={"thread_id": ctx.thread_id},
                recursion_limit=ctx.recursion_limit,
            )

            if ctx.stream_output:
                await self._stream_response(
                    {"messages": [human_message]},
                    graph_config,
                    agent_context,
                )
            else:
                await self._invoke_without_stream(
                    {"messages": [human_message]},
                    graph_config,
                    agent_context,
                )

        except Exception as e:
            error_msg = self._format_console_error(e)
            console.print_error(f"Error processing message: {error_msg}")
            console.print("")
            await self._log_processing_error(e)

    async def _stream_response(
        self,
        input_data: dict[str, Any] | Command,
        config: RunnableConfig,
        context: AgentContext,
    ) -> None:
        """Stream with automatic interrupt handling loop."""
        self._pending_compression = False
        current_input: dict[str, Any] | Command = input_data
        rendered_messages: set[str] = set()
        streaming_states: dict[tuple, dict[str, Any]] = {}

        self.session.current_stream_task = asyncio.current_task()

        try:
            while True:
                interrupted = False
                cancelled = False
                status = None

                try:
                    with console.console.status(
                        f"[{theme.spinner_color}]Thinking...[/{theme.spinner_color}]"
                    ) as status:
                        async for chunk in self.session.graph.astream(
                            current_input,
                            config,
                            context=context,
                            stream_mode=["messages", "updates"],
                            subgraphs=True,
                        ):
                            interrupts = self._extract_interrupts(chunk)
                            if interrupts:
                                # Clear all active streaming states on interrupt
                                for state in streaming_states.values():
                                    self._clear_preview(state)
                                status.stop()
                                resume_value = await self.interrupt_handler.handle(
                                    interrupts
                                )
                                # Sync approval mode from session context in case it changed during interrupt
                                context.approval_mode = (
                                    self.session.context.approval_mode
                                )

                                if isinstance(resume_value, dict):
                                    current_input = Command(resume=resume_value)
                                else:
                                    current_input = Command(
                                        resume={interrupts[0].id: resume_value}
                                    )
                                interrupted = True
                                break

                            namespace, mode, data = chunk

                            if mode == "messages":
                                await self._process_message_chunk(
                                    data,
                                    namespace,
                                    streaming_states,
                                    status,
                                    rendered_messages,
                                )
                            elif mode == "updates":
                                self._finalize_streaming(
                                    namespace,
                                    streaming_states,
                                    status,
                                    rendered_messages,
                                    stop_status=False,
                                )
                                await self._process_update_chunk(
                                    data, namespace, rendered_messages
                                )

                except (asyncio.CancelledError, KeyboardInterrupt):
                    if status:
                        status.stop()
                    self.session.prompt.reset_interrupt_state()
                    self._finalize_all_streaming(
                        streaming_states,
                        status,
                        rendered_messages,
                        stop_status=True,
                    )
                    cancelled = True

                if cancelled:
                    break

                if not interrupted:
                    self._finalize_all_streaming(
                        streaming_states,
                        status,
                        rendered_messages,
                        stop_status=True,
                    )
                    break

            if self._pending_compression and not cancelled:
                self._pending_compression = False
                try:
                    await self._execute_compression()
                except (asyncio.CancelledError, KeyboardInterrupt):
                    pass
        finally:
            self.session.current_stream_task = None

    async def _invoke_without_stream(
        self,
        input_data: dict[str, Any] | Command,
        config: RunnableConfig,
        context: AgentContext,
    ) -> None:
        """Run a request without token-by-token rendering."""
        result = await self.session.graph.ainvoke(input_data, config, context=context)

        if not isinstance(result, dict):
            return

        await self._update_token_tracking(result)

        messages = result.get("messages", [])
        for message in reversed(messages):
            if isinstance(message, (AIMessage, ToolMessage)):
                self.session.renderer.render_message(message)
                break

    async def _log_processing_error(self, error: Exception) -> None:
        """Log a message-processing failure with LLM and HTTP context."""
        log_fields = [
            f"thread_id={self.session.context.thread_id}",
            f"agent={self.session.context.agent}",
            f"model_alias={self.session.context.model}",
        ]
        log_fields.extend(await self._resolve_llm_log_fields())
        log_fields.extend(self._resolve_http_log_fields(error))

        exception_chain = self._format_exception_chain(error)
        if exception_chain:
            log_fields.append(f"exception_chain={exception_chain}")

        logger.exception("Message processing error [%s]", ", ".join(log_fields))

    async def _resolve_llm_log_fields(self) -> list[str]:
        """Resolve the current model configuration for error logging."""
        try:
            llm_config = await initializer.load_llm_config(
                self.session.context.model,
                Path(self.session.context.working_dir),
            )
        except Exception:
            logger.debug("Failed to resolve LLM config for error logging", exc_info=True)
            return []

        fields = [
            f"provider={llm_config.provider.value}",
            f"resolved_model={llm_config.model}",
        ]
        if llm_config.base_url:
            fields.append(f"base_url={llm_config.base_url}")
        return fields

    @classmethod
    def _resolve_http_log_fields(cls, error: BaseException) -> list[str]:
        """Extract request/response context from the exception chain."""
        fields: list[str] = []
        request = cls._find_exception_attr(error, "request")
        if request is not None:
            method = getattr(request, "method", None)
            url = getattr(request, "url", None)
            if method and url:
                fields.append(f"request={method} {url}")
            elif url:
                fields.append(f"request={url}")

        status_code = cls._find_exception_attr(error, "status_code")
        if status_code is not None:
            fields.append(f"status_code={status_code}")

        response_body = cls._extract_response_body(error)
        if response_body:
            fields.append(f"response_body={response_body}")

        return fields

    @classmethod
    def _extract_response_body(cls, error: BaseException) -> str | None:
        """Extract and normalize an API response body from the exception chain."""
        body = cls._find_exception_attr(error, "body")
        if body is not None and body != "":
            return cls._truncate_log_value(repr(body))

        response = cls._find_exception_attr(error, "response")
        if response is not None:
            text = getattr(response, "text", None)
            if text:
                return cls._truncate_log_value(str(text))

        return None

    @classmethod
    def _format_console_error(cls, error: BaseException) -> str:
        """Build a concise terminal-friendly error message."""
        message = (str(error) or type(error).__name__).strip()
        if message != "Connection error.":
            return message

        chain = list(cls._walk_exception_chain(error))
        for cause in chain[1:]:
            cause_message = str(cause).strip()
            if cause_message and cause_message != message:
                return cls._truncate_log_value(
                    f"{message} Cause: {type(cause).__name__}: {cause_message}",
                    limit=200,
                )
        return message

    @classmethod
    def _format_exception_chain(cls, error: BaseException) -> str:
        """Format the causal exception chain into a compact single line."""
        parts: list[str] = []
        for current in cls._walk_exception_chain(error):
            message = (str(current) or type(current).__name__).strip()
            parts.append(
                f"{type(current).__name__}: "
                f"{cls._truncate_log_value(message, limit=160)}"
            )
        return " <- ".join(parts)

    @staticmethod
    def _walk_exception_chain(
        error: BaseException, max_depth: int = 8
    ) -> list[BaseException]:
        """Collect the exception and its direct causes without looping forever."""
        chain: list[BaseException] = []
        seen: set[int] = set()
        current: BaseException | None = error

        while current is not None and id(current) not in seen and len(chain) < max_depth:
            chain.append(current)
            seen.add(id(current))
            current = current.__cause__ or current.__context__

        return chain

    @classmethod
    def _find_exception_attr(cls, error: BaseException, attr: str) -> Any | None:
        """Return the first non-empty attribute found in the exception chain."""
        for current in cls._walk_exception_chain(error):
            value = getattr(current, attr, None)
            if value is not None and value != "":
                return value
        return None

    @classmethod
    def _truncate_log_value(cls, value: str, limit: int | None = None) -> str:
        """Keep log fields compact and single-line."""
        max_length = limit or cls._MAX_LOG_VALUE_LENGTH
        normalized = " ".join(value.split())
        if len(normalized) <= max_length:
            return normalized
        return f"{normalized[: max_length - 3]}..."

    @staticmethod
    def _extract_interrupts(chunk) -> list[Interrupt] | None:
        """Extract interrupt data from chunk."""
        if isinstance(chunk, tuple) and len(chunk) == 3:
            _namespace, _mode, data = chunk
            if isinstance(data, dict):
                return data.get("__interrupt__")
        elif isinstance(chunk, dict):
            return chunk.get("__interrupt__")
        return None

    @staticmethod
    def _get_stable_message_id(message: AnyMessage) -> str:
        """Get a stable ID for deduplication, even when message.id is None.

        Returns a base ID without type suffix. Caller should append type if needed.
        """
        if message.id:
            return message.id

        content_str = str(message.content) if message.content else ""
        stable_key = hashlib.sha256(
            f"{content_str}:{message.type}".encode()
        ).hexdigest()[:8]
        return stable_key

    def _get_streaming_state(
        self, namespace: tuple, streaming_states: dict[tuple, dict[str, Any]]
    ) -> dict[str, Any]:
        """Get or create streaming state for namespace."""
        if namespace not in streaming_states:
            streaming_states[namespace] = {
                "active": False,
                "message_id": None,
                "preview_lines": [""],
                "chunks": [],
                "namespace": namespace,
            }
        return streaming_states[namespace]

    async def _process_message_chunk(
        self,
        data: tuple[AnyMessage, dict],
        namespace: tuple,
        streaming_states: dict[tuple, dict[str, Any]],
        status,
        rendered_messages: set[str],
    ) -> None:
        """Process message chunk for token-by-token streaming preview."""
        message_chunk, metadata = data

        streaming_state = self._get_streaming_state(namespace, streaming_states)

        if isinstance(message_chunk, AIMessageChunk):
            message_id = self._get_stable_message_id(message_chunk)

            if (
                not streaming_state["active"]
                or streaming_state["message_id"] != message_id
            ):
                self._finalize_streaming(
                    namespace,
                    streaming_states,
                    None,
                    rendered_messages,
                    stop_status=False,
                )
                streaming_state["active"] = True
                streaming_state["message_id"] = message_id
                streaming_state["preview_lines"] = [""]
                streaming_state["chunks"] = []

            streaming_state["chunks"].append(message_chunk)

            content = self._extract_chunk_content(message_chunk)
            if content:
                lines = content.split("\n")
                if len(lines) == 1:
                    streaming_state["preview_lines"][-1] += lines[0]
                else:
                    streaming_state["preview_lines"][-1] += lines[0]
                    for new_line in lines[1:]:
                        streaming_state["preview_lines"].append(new_line)
                    if len(streaming_state["preview_lines"]) > 4:
                        streaming_state["preview_lines"] = streaming_state[
                            "preview_lines"
                        ][-4:]

                indent_level = len(namespace)
                indent = "  " * indent_level

                spinner_text = render(
                    f"[{theme.spinner_color}]{indent}Thinking...[/{theme.spinner_color}]"
                )
                preview_text = "\n".join(
                    f"{indent}{line}" for line in streaming_state["preview_lines"][-3:]
                )
                status.update(Group(spinner_text, Text(preview_text, style="dim")))

    async def _process_update_chunk(
        self, data: dict, namespace: tuple, rendered_messages: set[str]
    ) -> None:
        """Process update chunk for tools/state (batch mode)."""
        for _node_name, node_data in data.items():
            if not isinstance(node_data, dict):
                continue

            await self._update_token_tracking(node_data)

            if node_data and "messages" in node_data and node_data["messages"]:
                messages = node_data["messages"]
                last_message: AnyMessage = messages[-1]
                base_id = self._get_stable_message_id(last_message)
                message_id = f"{base_id}_{last_message.type}"

                if message_id in rendered_messages:
                    continue

                rendered_messages.add(message_id)

                if isinstance(last_message, (AIMessage, ToolMessage)):
                    indent_level = len(namespace)
                    self.session.renderer.render_message(
                        last_message, indent_level=indent_level
                    )

    @staticmethod
    def _extract_chunk_content(chunk: AIMessageChunk) -> str:
        """Extract text content from AI message chunk."""
        if isinstance(chunk.content, str):
            return chunk.content
        elif isinstance(chunk.content, list):
            texts = []
            for block in chunk.content:
                if isinstance(block, str):
                    texts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
            return "".join(texts)
        return ""

    @staticmethod
    def _clear_preview(streaming_state: dict) -> None:
        """Clear preview without rendering final message."""
        if streaming_state["active"]:
            streaming_state["active"] = False
            streaming_state["message_id"] = None
            streaming_state["preview_lines"] = [""]
            streaming_state["chunks"] = []

    def _finalize_streaming(
        self,
        namespace: tuple,
        streaming_states: dict[tuple, dict[str, Any]],
        status,
        rendered_messages: set[str],
        *,
        stop_status: bool = True,
    ) -> None:
        """Finalize active streaming message and render final version."""
        streaming_state = self._get_streaming_state(namespace, streaming_states)

        if streaming_state["active"]:
            if stop_status and status:
                status.stop()

            if streaming_state["chunks"]:
                final_message = self._merge_chunks(streaming_state["chunks"])
                indent_level = len(namespace)
                self.session.renderer.render_assistant_message(
                    final_message, indent_level=indent_level
                )
                message_id = f"{streaming_state['message_id']}_{final_message.type}"
                rendered_messages.add(message_id)

            self._clear_preview(streaming_state)

    def _finalize_all_streaming(
        self,
        streaming_states: dict[tuple, dict[str, Any]],
        status,
        rendered_messages: set[str],
        *,
        stop_status: bool = True,
    ) -> None:
        """Finalize all active streaming messages."""
        for namespace in streaming_states:
            self._finalize_streaming(
                namespace,
                streaming_states,
                status,
                rendered_messages,
                stop_status=stop_status,
            )

    @staticmethod
    def _merge_chunks(chunks: list[AIMessageChunk]) -> AIMessage:
        """Merge message chunks into final AIMessage, preserving all attributes."""
        if not chunks:
            return AIMessage(content="")

        merged = chunks[0]
        for chunk in chunks[1:]:
            merged = merged + chunk

        return AIMessage(
            content=merged.content,
            additional_kwargs=merged.additional_kwargs,
            response_metadata=merged.response_metadata,
            tool_calls=merged.tool_calls,
            id=merged.id,
            name=merged.name,
        )

    async def _update_token_tracking(self, node_data: dict[str, Any]) -> None:
        """Update session context with token tracking data if present in node."""
        token_fields = {
            "current_input_tokens",
            "current_output_tokens",
        }

        # Check if any token tracking fields are present
        if not any(field in node_data for field in token_fields):
            return

        # Extract and update context
        updates = {
            field: node_data.get(field) for field in token_fields if field in node_data
        }

        if updates:
            self.session.update_context(**updates)
            # Check if auto-compression should be triggered after token update
            await self._check_auto_compression()

    async def _check_auto_compression(self) -> None:
        """Check if auto-compression should be triggered."""
        try:
            ctx = self.session.context
            config_data = await initializer.load_agents_config(ctx.working_dir)
            agent_config = config_data.get_agent_config(ctx.agent)

            if (
                agent_config
                and agent_config.compression
                and agent_config.compression.auto_compress_enabled
                and should_auto_compress(
                    ctx.current_input_tokens or 0,
                    ctx.context_window,
                    agent_config.compression.auto_compress_threshold,
                )
            ):
                self._pending_compression = True

        except Exception as e:
            logger.warning(f"Auto-compression check failed: {e}", exc_info=True)

    async def _execute_compression(self) -> None:
        """Execute compression after streaming completes."""
        ctx = self.session.context
        usage_pct = int(
            (ctx.current_input_tokens or 0) / ctx.context_window * 100
            if ctx.context_window
            else 0
        )

        with console.console.status(
            f"[{theme.spinner_color}]Context at {usage_pct}%, auto-compressing to new thread...[/{theme.spinner_color}]"
        ):
            await CompressionHandler(self.session).handle()

    async def resume_from_interrupt(
        self, thread_id: str, interrupts: list[Interrupt]
    ) -> None:
        """Resume graph from pending interrupts.

        Shows approval panel and resumes graph execution.
        """
        # Show approval panel
        resume_value = await self.interrupt_handler.handle(interrupts)
        if resume_value is None:
            return

        # Build Command
        cmd: Command
        if isinstance(resume_value, dict):
            cmd = Command(resume=resume_value)
        else:
            cmd = Command(resume={interrupts[0].id: resume_value})

        # Reuse existing context creation + streaming
        ctx = self.session.context
        now = datetime.now(timezone.utc).astimezone()
        user_memory = await initializer.load_user_memory(ctx.working_dir)
        agent_context = AgentContext(
            approval_mode=ctx.approval_mode,
            working_dir=ctx.working_dir,
            platform=PLATFORM,
            os_version=OS_VERSION,
            current_date_time_zoned=now.strftime("%Y-%m-%d %H:%M:%S %Z"),
            mcp_servers=(
                ", ".join(initializer.cached_mcp_server_names)
                if initializer.cached_mcp_server_names
                else "None"
            ),
            user_memory=user_memory,
            tool_catalog=initializer.cached_tools_in_catalog,
            skill_catalog=initializer.cached_agent_skills,
            tool_output_max_tokens=ctx.tool_output_max_tokens,
        )

        graph_config = RunnableConfig(
            configurable={"thread_id": thread_id},
            recursion_limit=ctx.recursion_limit,
        )

        await self._stream_response(cmd, graph_config, agent_context)
