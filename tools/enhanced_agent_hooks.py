"""Enhanced Agent Hooks with Progress Tracking.

This module provides an enhanced version of AgentRunHooks that adds
real-time progress tracking capabilities to the existing langfuse hooks.
The progress tracking is completely separate from Langfuse and only stores
messages in an in-memory store for web UI consumption.
"""

# pylint: disable=unused-argument,broad-exception-caught

import time
from typing import Any

from agents import Agent, RunContextWrapper, Tool

from common.logging.core import logger
from common.metrics import record_tool_execution, record_tool_execution_duration
from common.tools.progress_store import (
    get_agent_end_message,
    get_agent_start_message,
    get_tool_end_message,
    get_tool_start_message,
    progress_store,
)
from common.tools.util_langfuse import AgentRunHooks


class EnhancedAgentHooks(AgentRunHooks):
    """Enhanced Agent Hooks that extends AgentRunHooks with progress tracking.

    This class maintains full compatibility with the existing langfuse hooks while adding
    real-time progress updates that are stored in-memory for web UI consumption.
    The progress tracking is completely separate from Langfuse operations.
    """

    def __init__(
        self,
        conversation_id: str,
        parent_span_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        model_name: str | None = None,
    ):
        """Initialize enhanced hooks with progress tracking.

        Args:
            conversation_id: The conversation/thread ID
            parent_span_id: Optional parent span ID for langfuse tracing
            user_id: Optional user ID for langfuse tracing
            session_id: Optional session ID (defaults to conversation_id)
            model_name: Optional model name for langfuse tracing
        """
        # Initialize the base langfuse hooks (unchanged)
        super().__init__(
            conversation_id=conversation_id,
            parent_span_id=parent_span_id,
            user_id=user_id,
            model_name=model_name,
        )

        # Store session ID for progress tracking (separate system)
        self.session_id = session_id or conversation_id
        self._tool_start_times: dict[tuple[int, str], list[float]] = {}

        logger.info(f"Enhanced hooks initialized for session: {self.session_id}")

    def _get_tool_start_key(self, context: RunContextWrapper, tool_name: str) -> tuple[int, str]:
        """Build a stable key for transient tool timing state.

        Args:
            context: Run context wrapper for the current execution
            tool_name: Name of the tool being executed

        Returns:
            tuple[int, str]: Context-scoped key for tool timing state
        """
        return id(context.context), tool_name

    def _clear_tool_start_times_for_context(self, context: RunContextWrapper) -> None:
        """Clear transient timing state for a completed context.

        Args:
            context: Run context wrapper whose timing state should be removed
        """
        context_id = id(context.context)
        keys_to_remove = [key for key in self._tool_start_times if key[0] == context_id]
        for key in keys_to_remove:
            self._tool_start_times.pop(key, None)

    async def on_agent_start(self, context: RunContextWrapper, agent: Agent) -> None:
        """Called when an agent starts execution.

        Extends the base method with progress tracking.
        """
        try:
            # Call the parent langfuse method first (unchanged Langfuse behavior)
            await super().on_agent_start(context, agent)

            # Add progress tracking (separate in-memory store, no Langfuse interaction)
            message = get_agent_start_message(agent.name)

            progress_store.update_progress(
                session_id=self.session_id,
                message=message,
                step_type="agent_start",
                details=f"Starting {agent.name}",
                agent_name=agent.name,
            )

            logger.debug(f"Progress: Agent {agent.name} started for session {self.session_id}")

        except Exception as e:
            logger.error(f"Error in enhanced on_agent_start: {e}")
            # Don't re-raise to avoid breaking the agent execution

    async def on_agent_end(self, context: RunContextWrapper, agent: Agent, output: Any) -> None:
        """Called when an agent completes execution.

        Extends the base method with progress tracking.
        """
        try:
            # Call the parent langfuse method first (unchanged Langfuse behavior)
            await super().on_agent_end(context, agent, output)

            # Add progress tracking (separate in-memory store, no Langfuse interaction)
            message = get_agent_end_message(agent.name)

            progress_store.update_progress(
                session_id=self.session_id,
                message=message,
                step_type="agent_end",
                details=f"Completed {agent.name}",
                agent_name=agent.name,
            )

            logger.debug(f"Progress: Agent {agent.name} completed for session {self.session_id}")

        except Exception as e:
            logger.error(f"Error in enhanced on_agent_end: {e}")
            # Don't re-raise to avoid breaking the agent execution
        finally:
            self._clear_tool_start_times_for_context(context)

    async def on_tool_start(self, context: RunContextWrapper, agent: Agent, tool: Tool) -> None:
        """Called when a tool starts execution.

        Extends the base method with progress tracking and guardrail checking.
        This is where we centrally enforce that all tools wait for guardrail completion.

        Note: Guardrail checking only applies to the principal agent, not sub-agents.
        Sub-agents are assumed to be safe since they're called by the principal agent
        which has already passed guardrail checks.
        """
        try:
            # Call the parent langfuse method (unchanged Langfuse behavior)
            await super().on_tool_start(context, agent, tool)

            # Store tool start time for duration metric
            tool_start_key = self._get_tool_start_key(context, tool.name)
            self._tool_start_times.setdefault(tool_start_key, []).append(time.perf_counter())

            # Add progress tracking (separate in-memory store, no Langfuse interaction)
            message = get_tool_start_message(tool.name)

            progress_store.update_progress(
                session_id=self.session_id,
                message=message,
                step_type="tool_start",
                details=f"Executing {tool.name}",
                agent_name=agent.name,
                tool_name=tool.name,
            )

            logger.debug(f"Progress: Tool {tool.name} started by {agent.name} for session {self.session_id}")

        except Exception as e:
            logger.error(f"Error in enhanced on_tool_start: {e}")
            # Re-raise to prevent tool execution if guardrail fails
            raise

    async def on_tool_end(self, context: RunContextWrapper, agent: Agent, tool: Tool, result: str) -> None:
        """Called when a tool completes execution.

        Extends the base method with progress tracking and tool response capture.
        """
        tool_start_key = self._get_tool_start_key(context, tool.name)
        tool_start_stack = self._tool_start_times.get(tool_start_key, [])
        tool_start = tool_start_stack.pop() if tool_start_stack else None
        if not tool_start_stack:
            self._tool_start_times.pop(tool_start_key, None)

        try:
            # Call the parent langfuse method first (unchanged Langfuse behavior)
            await super().on_tool_end(context, agent, tool, result)

        except Exception as e:
            logger.error(f"Error in enhanced on_tool_end langfuse cleanup: {e}")

        try:
            # Record tool execution metric
            record_tool_execution(tool_name=tool.name, agent_name=agent.name)

            # Record tool duration metric
            if tool_start is not None:
                record_tool_execution_duration(
                    time.perf_counter() - tool_start,
                    tool_name=tool.name,
                    agent_name=agent.name,
                )

            # Capture tool execution data for guardrails
            if not hasattr(context.context, "tool_execution_data"):
                context.context.tool_execution_data = []

            # Create tool execution record
            tool_execution = {
                "id": f"tool_{len(context.context.tool_execution_data)}",
                "name": tool.name,
                "caller": agent.name,
                "outputs": str(result),
            }

            context.context.tool_execution_data.append(tool_execution)

            logger.debug(
                f"Captured tool response - {tool.name} by {agent.name}, total tools: {len(context.context.tool_execution_data)}"
            )

            # Add progress tracking (separate in-memory store, no Langfuse interaction)
            message = get_tool_end_message(tool.name)

            progress_store.update_progress(
                session_id=self.session_id,
                message=message,
                step_type="tool_end",
                details=f"Completed {tool.name}",
                agent_name=agent.name,
                tool_name=tool.name,
            )

            logger.debug(f"Progress: Tool {tool.name} completed by {agent.name} for session {self.session_id}")

        except Exception as e:
            logger.error(f"Error in enhanced on_tool_end post-processing: {e}")
            # Don't re-raise to avoid breaking the agent execution

    async def on_handoff(self, context: RunContextWrapper, from_agent: Agent, to_agent: Agent) -> None:
        """Called when there's a handoff between agents.

        Extends the base method with progress tracking.
        """
        try:
            # Call the parent langfuse method first (unchanged Langfuse behavior)
            await super().on_handoff(context, from_agent, to_agent)

            # Add progress tracking for handoff (separate in-memory store, no Langfuse interaction)
            message = f"🔄 Handing off from {from_agent.name} to {to_agent.name}..."

            progress_store.update_progress(
                session_id=self.session_id,
                message=message,
                step_type="handoff",
                details=f"Handoff: {from_agent.name} → {to_agent.name}",
                agent_name=from_agent.name,
            )

            logger.debug(f"Progress: Handoff from {from_agent.name} to {to_agent.name} for session {self.session_id}")

        except Exception as e:
            logger.error(f"Error in enhanced on_handoff: {e}")
            # Don't re-raise to avoid breaking the agent execution

    def update_custom_progress(self, message: str, details: str | None = None) -> None:
        """Update progress with a custom message.

        Args:
            message: Custom progress message
            details: Optional additional details
        """
        try:
            progress_store.update_progress(
                session_id=self.session_id,
                message=message,
                step_type="custom",
                details=details,
            )

            logger.debug(f"Progress: Custom update '{message}' for session {self.session_id}")

        except Exception as e:
            logger.error(f"Error in update_custom_progress: {e}")

    def clear_progress(self) -> None:
        """Clear progress for this session."""
        try:
            progress_store.clear_progress(self.session_id)
            logger.debug(f"Progress: Cleared for session {self.session_id}")

        except Exception as e:
            logger.error(f"Error in clear_progress: {e}")
