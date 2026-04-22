"""Centralised OpenTelemetry custom metrics for Financial Companion.

All custom business metrics are defined in this module and exposed as thin
helper functions so that call-sites remain decoupled from the OTel API.

Metrics are **only recorded** when ``OTLP_METRICS_ENABLED`` is ``True``.

Metric catalogue
----------------
| Name | Type | Description |
|------|------|-------------|
| ``fc.agent.execution.count`` | Counter | Sub-agent executions |
| ``fc.agent.execution.duration`` | Histogram | Sub-agent execution latency (s) |
| ``fc.tool.execution.count`` | Counter | Tool invocations |
| ``fc.tool.execution.duration`` | Histogram | Tool execution latency (s) |
| ``fc.genui.component.count`` | Counter | GenUI widget creations |
| ``fc.error.count`` | Counter | Handled errors (per agent/tool) |
| ``fc.warning.count`` | Counter | Handled warnings (per agent/tool) |
| ``fc.log.error.count`` | Counter | All error/critical log events |
| ``fc.log.warning.count`` | Counter | All warning log events |
| ``fc.user.unique`` | UpDownCounter | Unique users (CIF) gauge approx |
| ``fc.message.count`` | Counter | Total messages processed |
| ``fc.conversation.count`` | Counter | New conversations started |
| ``fc.conversation.message.count`` | Histogram | Messages per conversation |
| ``fc.guardrail.trigger.count`` | Counter | Guardrail triggers |
| ``fc.guardrail.rewrite.count`` | Counter | Guardrail output rewrites |
| ``fc.intent.classification.count`` | Counter | Intent classification routing |
| ``fc.rag.retrieval.count`` | Counter | RAG knowledge base retrievals |
| ``fc.conversation.closure.count`` | Counter | Conversations closed |
| ``fc.feedback.count`` | Counter | Feedback submissions |
| ``fc.feedback.score`` | Histogram | Feedback score distribution |
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from opentelemetry import metrics

from common.configs.app_config_settings import AppConfig

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider

_meter = metrics.get_meter("financial_companion.business")

# Common metric attribute keys used in multiple helper functions.
ATTR_TOOL_NAME = "fc.tool.name"
ATTR_AGENT_NAME = "fc.agent.name"
ATTR_USER_CIF_HASH = "fc.user.cif_hash"
ATTR_SESSION_ID = "fc.session.id"
METRIC_LOG_ERROR_COUNT = "fc.log.error.count"
UNIT_ERROR = "{error}"
UNIT_WARNING = "{warning}"
UNIT_MESSAGE = "{message}"

# ---------------------------------------------------------------------------
# Instrument registry — single source of truth for all business metrics.
# Each entry maps: (metric_name -> (variable_name, factory_method, description, unit))
# ``factory_method`` is the ``Meter`` method name used to create the instrument.
# ---------------------------------------------------------------------------
_INSTRUMENT_DEFS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "fc.agent.execution.count",
        "_agent_execution_count",
        "create_counter",
        "Number of sub-agent executions",
        "{execution}",
    ),
    (
        "fc.tool.execution.count",
        "_tool_execution_count",
        "create_counter",
        "Number of tool invocations",
        "{invocation}",
    ),
    (
        "fc.genui.component.count",
        "_genui_component_count",
        "create_counter",
        "Number of GenUI widget components created",
        "{component}",
    ),
    ("fc.error.count", "_error_count", "create_counter", "Number of handled errors", UNIT_ERROR),
    ("fc.warning.count", "_warning_count", "create_counter", "Number of handled warnings", UNIT_WARNING),
    (
        METRIC_LOG_ERROR_COUNT,
        "_log_error_count",
        "create_counter",
        "Number of all emitted ERROR/CRITICAL logs",
        UNIT_ERROR,
    ),
    (
        "fc.log.warning.count",
        "_log_warning_count",
        "create_counter",
        "Number of all emitted WARNING logs",
        UNIT_WARNING,
    ),
    (
        "fc.user.unique.count",
        "_unique_user_count",
        "create_counter",
        "Distinct authenticated user interactions (CIF)",
        "{user}",
    ),
    ("fc.message.count", "_message_count", "create_counter", "Total messages processed", UNIT_MESSAGE),
    ("fc.conversation.count", "_conversation_count", "create_counter", "New conversations started", "{conversation}"),
    (
        "fc.conversation.message.count",
        "_conversation_message_count",
        "create_histogram",
        "Number of messages per conversation at response time",
        UNIT_MESSAGE,
    ),
    (
        "fc.agent.execution.duration",
        "_agent_execution_duration",
        "create_histogram",
        "Sub-agent execution latency",
        "s",
    ),
    ("fc.tool.execution.duration", "_tool_execution_duration", "create_histogram", "Tool execution latency", "s"),
    (
        "fc.guardrail.trigger.count",
        "_guardrail_trigger_count",
        "create_counter",
        "Number of guardrail triggers",
        "{trigger}",
    ),
    (
        "fc.guardrail.rewrite.count",
        "_guardrail_rewrite_count",
        "create_counter",
        "Number of guardrail output rewrites by origin type",
        "{rewrite}",
    ),
    (
        "fc.intent.classification.count",
        "_intent_classification_count",
        "create_counter",
        "Intent classification routing decisions",
        "{classification}",
    ),
    (
        "fc.rag.retrieval.count",
        "_rag_retrieval_count",
        "create_counter",
        "RAG knowledge base retrieval attempts",
        "{retrieval}",
    ),
    (
        "fc.conversation.closure.count",
        "_conversation_closure_count",
        "create_counter",
        "Conversations closed (guardrail or natural)",
        "{closure}",
    ),
    ("fc.feedback.count", "_feedback_count", "create_counter", "Feedback submissions", "{feedback}"),
    ("fc.feedback.score", "_feedback_score", "create_histogram", "Distribution of feedback scores", "{score}"),
)

# Metrics that must remain on the global (obstack-enabled) ``MeterProvider``.
# Instruments whose metric name appears here are **not** rebound when
# ``initialise_meter_provider()`` is called; they keep the default meter
# created at import time (which inherits the ``obstack=true`` resource set by
# ``observability.init()``).
#
# To move a metric between providers, simply add or remove its name here.
OBSTACK_INSTRUMENTS: frozenset[str] = frozenset(
    {
        # -- add metric names that should carry obstack=true, e.g.:
        # "fc.error.count",
        METRIC_LOG_ERROR_COUNT,
        # "fc.log.warning.count",
    }
)

# ---------------------------------------------------------------------------
# Instrument definitions
# ---------------------------------------------------------------------------

_agent_execution_count = _meter.create_counter(
    name="fc.agent.execution.count",
    description="Number of sub-agent executions",
    unit="{execution}",
)

_tool_execution_count = _meter.create_counter(
    name="fc.tool.execution.count",
    description="Number of tool invocations",
    unit="{invocation}",
)

_genui_component_count = _meter.create_counter(
    name="fc.genui.component.count",
    description="Number of GenUI widget components created",
    unit="{component}",
)

_error_count = _meter.create_counter(
    name="fc.error.count",
    description="Number of handled errors",
    unit=UNIT_ERROR,
)

_warning_count = _meter.create_counter(
    name="fc.warning.count",
    description="Number of handled warnings",
    unit=UNIT_WARNING,
)

_log_error_count = _meter.create_counter(
    name=METRIC_LOG_ERROR_COUNT,
    description="Number of all emitted ERROR/CRITICAL logs",
    unit=UNIT_ERROR,
)

_log_warning_count = _meter.create_counter(
    name="fc.log.warning.count",
    description="Number of all emitted WARNING logs",
    unit=UNIT_WARNING,
)

_unique_user_count = _meter.create_counter(
    name="fc.user.unique.count",
    description="Distinct authenticated user interactions (CIF)",
    unit="{user}",
)

_message_count = _meter.create_counter(
    name="fc.message.count",
    description="Total messages processed",
    unit=UNIT_MESSAGE,
)

_conversation_count = _meter.create_counter(
    name="fc.conversation.count",
    description="New conversations started",
    unit="{conversation}",
)

_conversation_message_count = _meter.create_histogram(
    name="fc.conversation.message.count",
    description="Number of messages per conversation at response time",
    unit=UNIT_MESSAGE,
)

_agent_execution_duration = _meter.create_histogram(
    name="fc.agent.execution.duration",
    description="Sub-agent execution latency",
    unit="s",
)

_tool_execution_duration = _meter.create_histogram(
    name="fc.tool.execution.duration",
    description="Tool execution latency",
    unit="s",
)

_guardrail_trigger_count = _meter.create_counter(
    name="fc.guardrail.trigger.count",
    description="Number of guardrail triggers",
    unit="{trigger}",
)

_guardrail_rewrite_count = _meter.create_counter(
    name="fc.guardrail.rewrite.count",
    description="Number of guardrail output rewrites by origin type",
    unit="{rewrite}",
)

_intent_classification_count = _meter.create_counter(
    name="fc.intent.classification.count",
    description="Intent classification routing decisions",
    unit="{classification}",
)

_rag_retrieval_count = _meter.create_counter(
    name="fc.rag.retrieval.count",
    description="RAG knowledge base retrieval attempts",
    unit="{retrieval}",
)

_conversation_closure_count = _meter.create_counter(
    name="fc.conversation.closure.count",
    description="Conversations closed (guardrail or natural)",
    unit="{closure}",
)

_feedback_count = _meter.create_counter(
    name="fc.feedback.count",
    description="Feedback submissions",
    unit="{feedback}",
)

_feedback_score = _meter.create_histogram(
    name="fc.feedback.score",
    description="Distribution of feedback scores",
    unit="{score}",
)

# ---------------------------------------------------------------------------
# Provider (re-)initialisation
# ---------------------------------------------------------------------------


def initialise_meter_provider(provider: SdkMeterProvider) -> None:
    """Rebind non-obstack business metric instruments to the given ``MeterProvider``.

    Instruments whose metric name appears in :data:`OBSTACK_INSTRUMENTS` are
    left untouched — they keep the global meter (``obstack=true``) created at
    module import time.  All other instruments are recreated from *provider*
    so they carry the non-obstack resource attributes.

    Must be called **once** during application startup, after the provider has
    been constructed.

    Args:
        provider: An SDK ``MeterProvider`` whose resource carries the desired
            attributes for non-obstack business metrics.

    """
    ns = globals()
    meter = provider.get_meter("financial_companion.business")
    ns["_meter"] = meter

    for metric_name, var_name, factory, description, unit in _INSTRUMENT_DEFS:
        if metric_name in OBSTACK_INSTRUMENTS:
            continue
        ns[var_name] = getattr(meter, factory)(
            name=metric_name,
            description=description,
            unit=unit,
        )


# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------


def _is_enabled() -> bool:
    """Return True when OTLP metrics collection is active."""
    return bool(AppConfig.OTLP_METRICS_ENABLED)


def _hash_identifier(value: str) -> str:
    """Return a deterministic one-way hash for user identifiers."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record_agent_execution(
    agent_type: str,
    *,
    success: bool = True,
) -> None:
    """Record a sub-agent execution.

    Args:
        agent_type: Agent type value, e.g. ``"SavingsAgent"``.
        success: Whether the execution succeeded.
    """
    if not _is_enabled():
        return
    attributes: dict[str, Any] = {
        "fc.agent.type": agent_type,
        "fc.agent.success": success,
    }
    _agent_execution_count.add(1, attributes)


def record_tool_execution(
    tool_name: str,
    agent_name: str,
) -> None:
    """Record a tool invocation.

    Args:
        tool_name: Name of the tool that was executed.
        agent_name: Name of the agent that invoked the tool.
    """
    if not _is_enabled():
        return
    attributes: dict[str, Any] = {
        ATTR_TOOL_NAME: tool_name,
        ATTR_AGENT_NAME: agent_name,
    }
    _tool_execution_count.add(1, attributes)


def record_genui_component(
    widget_type: str,
    agent_name: str = "",
) -> None:
    """Record a GenUI widget component creation.

    Args:
        widget_type: The widget type string, e.g. ``"goal_tracker"``.
        agent_name: Name of the agent that created the component.
    """
    if not _is_enabled():
        return
    attributes: dict[str, Any] = {
        "fc.genui.widget_type": widget_type,
    }
    if agent_name:
        attributes[ATTR_AGENT_NAME] = agent_name
    _genui_component_count.add(1, attributes)


def record_error(
    *,
    context: str,
    agent_name: str = "",
    tool_name: str = "",
    error_type: str = "",
) -> None:
    """Record a handled error.

    Args:
        context: Where the error occurred, e.g. ``"agent_pool.execute"``.
        agent_name: Agent involved, if applicable.
        tool_name: Tool involved, if applicable.
        error_type: Exception class name.
    """
    if not _is_enabled():
        return
    attributes: dict[str, Any] = {"fc.error.context": context}
    if agent_name:
        attributes[ATTR_AGENT_NAME] = agent_name
    if tool_name:
        attributes[ATTR_TOOL_NAME] = tool_name
    if error_type:
        attributes["fc.error.type"] = error_type
    _error_count.add(1, attributes)


def record_warning(
    *,
    context: str,
    agent_name: str = "",
    tool_name: str = "",
) -> None:
    """Record a handled warning.

    Args:
        context: Where the warning occurred.
        agent_name: Agent involved, if applicable.
        tool_name: Tool involved, if applicable.
    """
    if not _is_enabled():
        return
    attributes: dict[str, Any] = {"fc.warning.context": context}
    if agent_name:
        attributes[ATTR_AGENT_NAME] = agent_name
    if tool_name:
        attributes[ATTR_TOOL_NAME] = tool_name
    _warning_count.add(1, attributes)


def record_unique_user(cif_code: str) -> None:
    """Record an authenticated user interaction.

    Each call adds 1; downstream dashboards should apply ``count_distinct``
    or similar aggregation to derive true unique counts per time window.

    The raw CIF is never emitted into metric attributes; a deterministic
    one-way hash is used instead.

    Args:
        cif_code: Customer information file code (opaque id).
    """
    if not _is_enabled():
        return
    _unique_user_count.add(1, {ATTR_USER_CIF_HASH: _hash_identifier(cif_code)})


def record_message(
    *,
    role: str,
    session_id: str = "",
    cif_code: str = "",
) -> None:
    """Record a message (user or assistant).

    Args:
        role: ``"user"`` or ``"assistant"``.
        session_id: Conversation session identifier.
        cif_code: Customer information file code.
    """
    if not _is_enabled():
        return
    attributes: dict[str, Any] = {"fc.message.role": role}
    if session_id:
        attributes[ATTR_SESSION_ID] = session_id
    if cif_code:
        attributes[ATTR_USER_CIF_HASH] = _hash_identifier(cif_code)
    _message_count.add(1, attributes)


def record_conversation(
    *,
    session_id: str,
    cif_code: str = "",
) -> None:
    """Record a new conversation.

    Args:
        session_id: Conversation session identifier.
        cif_code: Customer information file code.
    """
    if not _is_enabled():
        return
    attributes: dict[str, Any] = {ATTR_SESSION_ID: session_id}
    if cif_code:
        attributes[ATTR_USER_CIF_HASH] = _hash_identifier(cif_code)
    _conversation_count.add(1, attributes)


def record_log_level_event(
    *,
    level: str,
    logger_name: str = "",
    module_name: str = "",
    function_name: str = "",
) -> None:
    """Record warning/error metrics from the central logger.

    Args:
        level: Log level name (e.g. ``"WARNING"``, ``"ERROR"``, ``"CRITICAL"``).
        logger_name: Logger namespace from the logging record.
        module_name: Module name from the logging record.
        function_name: Function name from the logging record.
    """
    if not _is_enabled():
        return

    attributes: dict[str, Any] = {"fc.log.level": level}
    if logger_name:
        attributes["fc.log.logger"] = logger_name
    if module_name:
        attributes["fc.log.module"] = module_name
    if function_name:
        attributes["fc.log.function"] = function_name

    if level == "WARNING":
        _log_warning_count.add(1, attributes)
        return

    if level in {"ERROR", "CRITICAL"}:
        _log_error_count.add(1, attributes)


def record_conversation_message_count(
    message_count: int,
    *,
    session_id: str = "",
) -> None:
    """Record the number of messages in a conversation at response time.

    Emits a histogram observation so Grafana can compute distributions
    (p50, p95, avg messages per conversation).

    Args:
        message_count: Total messages in the conversation so far.
        session_id: Conversation session identifier.
    """
    if not _is_enabled():
        return
    attributes: dict[str, Any] = {}
    if session_id:
        attributes[ATTR_SESSION_ID] = session_id
    _conversation_message_count.record(message_count, attributes)


def record_agent_execution_duration(
    duration: float,
    agent_type: str,
    *,
    success: bool = True,
) -> None:
    """Record sub-agent execution latency.

    Args:
        duration: Execution time in seconds.
        agent_type: Agent type value, e.g. ``"SavingsAgent"``.
        success: Whether the execution succeeded.
    """
    if not _is_enabled():
        return
    _agent_execution_duration.record(
        duration,
        {"fc.agent.type": agent_type, "fc.agent.success": success},
    )


def record_tool_execution_duration(
    duration: float,
    tool_name: str,
    agent_name: str,
) -> None:
    """Record tool execution latency.

    Args:
        duration: Execution time in seconds.
        tool_name: Name of the tool that was executed.
        agent_name: Name of the agent that invoked the tool.
    """
    if not _is_enabled():
        return
    _tool_execution_duration.record(
        duration,
        {ATTR_TOOL_NAME: tool_name, ATTR_AGENT_NAME: agent_name},
    )


def record_guardrail_trigger(
    *,
    guardrail_name: str,
    check_type: str,
    triggered: bool = True,
) -> None:
    """Record a guardrail check result.

    Args:
        guardrail_name: Name of the guardrail, e.g. ``"jailbreak_check"``.
        check_type: ``"input"`` or ``"output"``.
        triggered: Whether the guardrail was triggered (blocked the request).
    """
    if not _is_enabled():
        return
    _guardrail_trigger_count.add(
        1,
        {
            "fc.guardrail.name": guardrail_name,
            "fc.guardrail.check_type": check_type,
            "fc.guardrail.triggered": triggered,
        },
    )


def record_guardrail_rewrite(
    *,
    origin: str,
) -> None:
    """Record a guardrail output rewrite event.

    Args:
        origin: The ``ResponseOrigin`` value describing how the response was generated,
                e.g. ``"output_rewritten"``, ``"input_trigger_pre_canned"``.
    """
    if not _is_enabled():
        return
    _guardrail_rewrite_count.add(1, {"fc.guardrail.origin": origin})


def record_intent_classification(
    *,
    agent_domain: str,
    confidence_score: float,
    is_multi_agent: bool = False,
    is_fallback: bool = False,
) -> None:
    """Record an intent classification routing decision.

    Called once per routed sub-agent in the classification result.

    Args:
        agent_domain: Domain name, e.g. ``"savings"``, ``"homebuying"``.
        confidence_score: Confidence score from the classifier (0.0-1.0).
        is_multi_agent: Whether this is part of a multi-agent routing.
        is_fallback: Whether this is a low-confidence fallback to general_queries.
    """
    if not _is_enabled():
        return
    _intent_classification_count.add(
        1,
        {
            "fc.intent.agent_domain": agent_domain,
            "fc.intent.confidence_score": confidence_score,
            "fc.intent.multi_agent": is_multi_agent,
            "fc.intent.fallback": is_fallback,
        },
    )


def record_rag_retrieval(
    *,
    success: bool,
    chunks_retrieved: int = 0,
    reranking_applied: bool = False,
) -> None:
    """Record a RAG knowledge base retrieval attempt.

    Args:
        success: Whether the retrieval succeeded.
        chunks_retrieved: Number of chunks returned.
        reranking_applied: Whether LLM reranking was applied.
    """
    if not _is_enabled():
        return
    _rag_retrieval_count.add(
        1,
        {
            "fc.rag.success": success,
            "fc.rag.chunks_retrieved": chunks_retrieved,
            "fc.rag.reranking_applied": reranking_applied,
        },
    )


def record_conversation_closure(
    *,
    session_id: str = "",
    reason: str = "",
) -> None:
    """Record a conversation closure.

    Args:
        session_id: Conversation session identifier.
        reason: Reason or resume_point indicating why the conversation was closed.
    """
    if not _is_enabled():
        return
    attributes: dict[str, Any] = {}
    if session_id:
        attributes[ATTR_SESSION_ID] = session_id
    if reason:
        attributes["fc.closure.reason"] = reason
    _conversation_closure_count.add(1, attributes)


def record_feedback(
    *,
    rating: int,
    session_id: str = "",
) -> None:
    """Record a feedback submission.

    Args:
        rating: The feedback score (e.g. 1 for thumbs-up, -1 for thumbs-down).
        session_id: Conversation session identifier.
    """
    if not _is_enabled():
        return
    attributes: dict[str, Any] = {"fc.feedback.rating": rating}
    if session_id:
        attributes[ATTR_SESSION_ID] = session_id
    _feedback_count.add(1, attributes)
    _feedback_score.record(rating, attributes)
