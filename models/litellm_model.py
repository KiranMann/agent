"""OpenAI Agent SDK LiteLLM extension's LiteLLMModel class implementation.

Copy-pasted it here since the extension requirements required packages that caused issues.

Code modified from
https://github.com/openai/openai-agents-python/blob/main/src/agents/extensions/models/litellm_model.py#L56

"""

from __future__ import annotations

import copy
import json
import os
import time
from typing import TYPE_CHECKING, Any, Literal, cast, overload

import litellm
from agents import _debug
from agents.exceptions import ModelBehaviorError
from agents.items import ModelResponse, TResponseInputItem, TResponseStreamEvent
from agents.logger import logger
from agents.models.chatcmpl_converter import Converter
from agents.models.chatcmpl_helpers import HEADERS
from agents.models.chatcmpl_stream_handler import ChatCmplStreamHandler
from agents.models.fake_id import FAKE_RESPONSES_ID
from agents.models.interface import Model, ModelTracing
from agents.tracing import generation_span
from agents.usage import Usage
from openai import NOT_GIVEN, AsyncStream, NotGiven
from openai.types.chat import ChatCompletionChunk, ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_message import Annotation, AnnotationURLCitation, ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import Function
from openai.types.responses import Response
from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails

from common.logging import logger as local_logger
from common.logging.core import log_error

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agents.agent_output import AgentOutputSchemaBase
    from agents.handoffs import Handoff
    from agents.model_settings import ModelSettings
    from agents.tool import Tool
    from agents.tracing.span_data import GenerationSpanData
    from agents.tracing.spans import Span

# Set logging based off of ENV
litellm_debug = os.environ.get("LITELLM_DEBUG", "false").lower() == "true"
litellm.json_logs = litellm_debug
if litellm_debug:
    litellm._turn_on_debug()
else:
    local_logger.info("LiteLLM debugging not turned on. Set LITELLM_DEBUG to turn it on.")

# Claude models which matche these patterns that support prompt caching
PROMPT_CACHING_SUPPORTED_MODELS = ["claude-4", "claude-4-5-sonnet", "claude-3-7-sonnet"]


def serialize_object(obj: Any) -> Any:
    """Convert complex objects to JSON-serializable format."""
    if hasattr(obj, "__dict__"):
        result = {"_type": type(obj).__name__}
        for key, value in obj.__dict__.items():
            result[key] = serialize_object(value)
        return result
    elif isinstance(obj, list | tuple):
        return [serialize_object(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: serialize_object(value) for key, value in obj.items()}
    else:
        return str(obj)


class InternalChatCompletionMessage(ChatCompletionMessage):
    """An internal subclass to carry reasoning_content without modifying the original model."""

    reasoning_content: str


class LitellmModel(Model):
    """This class enables using any model via LiteLLM. LiteLLM allows you to acess OpenAPI, Anthropic, Gemini, Mistral, and many other models.

    See supported models here: [litellm models](https://docs.litellm.ai/docs/providers).
    """

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize LitellmModel."""
        self.model = model
        self.base_url = base_url
        self.api_key = api_key

    @staticmethod
    def _coerce_int_usage_value(value: Any) -> int:
        """Return a safe integer usage value.

        LiteLLM response usage values are sometimes represented as mocks in unit tests.
        Those values should be treated as missing unless they are real numeric types.
        """
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return 0

    @classmethod
    def _get_cached_tokens(cls, response_usage: Any) -> int:
        """Extract cached tokens from response usage."""
        prompt_tokens_details = getattr(response_usage, "prompt_tokens_details", None)
        if prompt_tokens_details is None:
            return 0
        return cls._coerce_int_usage_value(getattr(prompt_tokens_details, "cached_tokens", 0))

    @classmethod
    def _get_reasoning_tokens(cls, response_usage: Any) -> int:
        """Extract reasoning tokens from response usage."""
        completion_tokens_details = getattr(response_usage, "completion_tokens_details", None)
        if completion_tokens_details is None:
            return 0
        return cls._coerce_int_usage_value(getattr(completion_tokens_details, "reasoning_tokens", 0))

    def _create_usage_from_response(self, response_usage: Any) -> Usage:
        """Create Usage object from response usage data."""
        cached_tokens = self._get_cached_tokens(response_usage)
        reasoning_tokens = self._get_reasoning_tokens(response_usage)
        prompt_tokens = self._coerce_int_usage_value(getattr(response_usage, "prompt_tokens", 0))
        completion_tokens = self._coerce_int_usage_value(getattr(response_usage, "completion_tokens", 0))
        total_tokens = self._coerce_int_usage_value(getattr(response_usage, "total_tokens", 0))

        return Usage(
            requests=1,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            total_tokens=total_tokens,
            input_tokens_details=InputTokensDetails(cached_tokens=cached_tokens),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=reasoning_tokens),
        )

    @staticmethod
    def _create_default_usage() -> Usage:
        """Create default Usage object when no usage data is available."""
        return Usage(
            requests=1,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            input_tokens_details=InputTokensDetails(cached_tokens=0),
            output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        )

    def _log_cache_usage(self, cached_tokens: int, response_usage: Any) -> None:
        """Log cache usage information."""
        logger.info(response_usage)

        if cached_tokens > 0:
            cache_percentage = (cached_tokens / response_usage.prompt_tokens) * 100
            logger.info(
                f"🚀 CACHE HIT: {cached_tokens}/{response_usage.prompt_tokens} tokens cached({cache_percentage:.1f}%) - Model: {self.model}"
            )
        else:
            logger.info(f"📝 CACHE MISS: No cached tokens - Model: {self.model}")

    def _process_response_usage(self, response: Any, model_settings: ModelSettings) -> Usage:
        """Process response usage and return Usage object."""
        if not hasattr(response, "usage") or not response.usage:
            logger.warning("No usage information returned from Litellm")
            return self._create_default_usage()

        response_usage = response.usage
        usage = self._create_usage_from_response(response_usage)

        cached_tokens = self._get_cached_tokens(response_usage)
        self._log_cache_usage(cached_tokens, response_usage)
        self._add_cache_metadata_if_supported(cached_tokens, response_usage, model_settings)

        return usage

    @classmethod
    def get_prompt_caching_generation_metadata(cls, response_usage: Any, model: str) -> dict[str, Any]:
        """Build Langfuse generation metadata for prompt caching details.

        Args:
            response_usage: LiteLLM response usage object.
            model: Model name used for the request.

        Returns:
            Dict containing a prompt_caching metadata payload. Returns an empty dict
            when usage details are unavailable.
        """
        if response_usage is None:
            return {}

        prompt_tokens_details = getattr(response_usage, "prompt_tokens_details", None)
        cached_tokens = 0
        if prompt_tokens_details is not None:
            cached_tokens = cls._coerce_int_usage_value(getattr(prompt_tokens_details, "cached_tokens", 0))

        total_prompt_tokens = cls._coerce_int_usage_value(getattr(response_usage, "prompt_tokens", 0))
        cache_percentage = (cached_tokens / total_prompt_tokens * 100) if total_prompt_tokens > 0 else 0.0
        cache_creation_tokens = cls._coerce_int_usage_value(getattr(response_usage, "cache_creation_input_tokens", 0))

        return {
            "prompt_caching": {
                "cached_tokens": cached_tokens,
                "cache_hit": cached_tokens > 0,
                "cache_percentage": round(cache_percentage, 1),
                "total_prompt_tokens": total_prompt_tokens,
                "cache_creation_input_tokens": cache_creation_tokens,
                "model": model,
            }
        }

    @staticmethod
    def _log_model_response(response: Any) -> None:
        """Log the model response based on debug settings."""
        if _debug.DONT_LOG_MODEL_DATA:
            logger.debug("Received model response")
        else:
            logger.debug(
                f"""LLM resp:\n{json.dumps(response.choices[0].message.model_dump(), indent=2, ensure_ascii=False)}\n"""
            )

    @staticmethod
    def _update_span_data(span_generation: Any, response: Any, usage: Usage, tracing: ModelTracing) -> None:
        """Update span generation data with response and usage information."""
        if tracing.include_data():
            span_generation.span_data.output = [response.choices[0].message.model_dump()]

        span_generation.span_data.usage = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        previous_response_id: str | None = None,  # noqa: ARG002
        conversation_id: str | None = None,  # noqa: ARG002
        prompt: str | None = None,  # noqa: ARG002
    ) -> ModelResponse:
        with generation_span(
            model=str(self.model),
            model_config=model_settings.to_json_dict()
            | {"base_url": str(self.base_url or ""), "model_impl": "litellm"},
            disabled=tracing.is_disabled(),
        ) as span_generation:
            response = await self._fetch_response(
                system_instructions,
                input,
                model_settings,
                tools,
                output_schema,
                handoffs,
                span_generation,
                tracing,
                stream=False,
            )

            assert isinstance(response.choices[0], litellm.types.utils.Choices)

            self._log_model_response(response)
            usage = self._process_response_usage(response, model_settings)
            self._update_span_data(span_generation, response, usage, tracing)

            items = Converter.message_to_output_items(
                LitellmConverter.convert_message_to_openai(response.choices[0].message)
            )

            return ModelResponse(
                output=items,
                usage=usage,
                response_id=None,
            )

    async def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        previous_response_id: str | None,  # noqa: ARG002
    ) -> AsyncIterator[TResponseStreamEvent]:
        with generation_span(
            model=str(self.model),
            model_config=model_settings.to_json_dict()
            | {"base_url": str(self.base_url or ""), "model_impl": "litellm"},
            disabled=tracing.is_disabled(),
        ) as span_generation:
            response, stream = await self._fetch_response(
                system_instructions,
                input,
                model_settings,
                tools,
                output_schema,
                handoffs,
                span_generation,
                tracing,
                stream=True,
            )

            final_response: Response | None = None
            async for chunk in ChatCmplStreamHandler.handle_stream(response, stream):
                yield chunk

                if chunk.type == "response.completed":
                    final_response = chunk.response

            if tracing.include_data() and final_response:
                span_generation.span_data.output = [final_response.model_dump()]

            if final_response and final_response.usage:
                span_generation.span_data.usage = {
                    "input_tokens": final_response.usage.input_tokens,
                    "output_tokens": final_response.usage.output_tokens,
                }

    @overload
    async def _fetch_response(
        self,
        system_instructions: str | None,
        input_value: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        span: Span[GenerationSpanData],
        tracing: ModelTracing,
        stream: Literal[True],
    ) -> tuple[Response, AsyncStream[ChatCompletionChunk]]: ...

    @overload
    async def _fetch_response(
        self,
        system_instructions: str | None,
        input_value: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        span: Span[GenerationSpanData],
        tracing: ModelTracing,
        stream: Literal[False],
    ) -> litellm.types.utils.ModelResponse: ...

    async def _fetch_response(
        self,
        system_instructions: str | None,
        input_value: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        span: Span[GenerationSpanData],
        tracing: ModelTracing,
        stream: bool = False,
    ) -> litellm.types.utils.ModelResponse | tuple[Response, AsyncStream[ChatCompletionChunk]]:
        converted_messages = Converter.items_to_messages(input_value)

        if system_instructions:
            self._add_system_instructions(converted_messages, system_instructions)
        if tracing.include_data():
            span.span_data.input = converted_messages

        parallel_tool_calls = self._get_parallel_tool_calls_setting(model_settings, tools)
        tool_choice = Converter.convert_tool_choice(model_settings.tool_choice)
        response_format = Converter.convert_response_format(output_schema)

        converted_tools = [Converter.tool_to_openai(tool) for tool in tools] if tools else []

        converted_tools.extend(Converter.convert_handoff_tool(handoff) for handoff in handoffs)

        self._log_llm_call(converted_messages, converted_tools, stream, tool_choice, response_format)

        reasoning_effort = model_settings.reasoning.effort if model_settings.reasoning else None

        stream_options = self._get_stream_options(stream, model_settings)

        extra_kwargs = self._build_extra_kwargs(model_settings)

        # Extract timeout parameters to pass correctly
        timeout = extra_kwargs.pop("timeout", None)

        try:
            ret = await litellm.acompletion(
                model=self.model,
                tools=converted_tools or None,
                temperature=model_settings.temperature,
                messages=converted_messages,
                top_p=model_settings.top_p,
                frequency_penalty=model_settings.frequency_penalty,
                presence_penalty=model_settings.presence_penalty,
                max_tokens=model_settings.max_tokens,
                tool_choice=self._remove_not_given(tool_choice),
                response_format=self._remove_not_given(response_format),
                parallel_tool_calls=parallel_tool_calls,
                stream=stream,
                stream_options=stream_options,
                reasoning_effort=reasoning_effort,
                extra_headers={**HEADERS, **(model_settings.extra_headers or {})},
                api_key=self.api_key,
                base_url=self.base_url,
                extra_body={
                    **({"timeout": timeout} if timeout is not None else {}),
                },
                **(extra_kwargs or {}),
            )

        except Exception as e:
            # Handle all LiteLLM exceptions with logging and user-friendly messages
            self._handle_litellm_exception(e)
            ret = None

        if isinstance(ret, litellm.types.utils.ModelResponse):
            return ret

        response = Response(
            id=FAKE_RESPONSES_ID,
            created_at=time.time(),
            model=self.model,
            object="response",
            output=[],
            tool_choice=(
                cast("Literal['auto', 'required', 'none']", tool_choice) if tool_choice != NOT_GIVEN else "auto"
            ),
            top_p=model_settings.top_p,
            temperature=model_settings.temperature,
            tools=[],
            parallel_tool_calls=parallel_tool_calls or False,
            reasoning=model_settings.reasoning,
        )
        return response, ret

    def _add_cache_metadata_if_supported(
        self,
        cached_tokens: int,
        response_usage: Any,
        model_settings: ModelSettings,
    ) -> None:
        """Add cache metadata for supported Claude models."""
        if not (
            hasattr(model_settings, "metadata")
            and model_settings.metadata
            and any(model in self.model for model in PROMPT_CACHING_SUPPORTED_MODELS)
        ):
            return

        cache_percentage = (
            (cached_tokens / response_usage.prompt_tokens * 100)
            if cached_tokens > 0 and response_usage.prompt_tokens > 0
            else 0.0
        )

        cache_creation_tokens = getattr(response_usage, "cache_creation_input_tokens", 0) or 0

        model_settings.metadata["prompt_caching"] = json.dumps(
            {
                "cached_tokens": cached_tokens,
                "cache_hit": cached_tokens > 0,
                "cache_percentage": round(cache_percentage, 1),
                "total_prompt_tokens": response_usage.prompt_tokens,
                "cache_creation_input_tokens": cache_creation_tokens,
                "model": self.model,
            }
        )
        logger.info(
            f"Added cache data to metadata.prompt_caching: {cached_tokens}/{response_usage.prompt_tokens} tokens ({cache_percentage:.1f}%), cache_creation: {cache_creation_tokens}"
        )

    def _supports_prompt_caching(self) -> bool:
        """Return whether the configured model supports prompt caching."""
        return self._supports_prompt_caching_for_model(self.model)

    @staticmethod
    def _supports_prompt_caching_for_model(model: str) -> bool:
        """Return whether the provided model supports prompt caching."""
        return any(model_name in model for model_name in PROMPT_CACHING_SUPPORTED_MODELS)

    @staticmethod
    def prepare_messages_for_prompt_caching(
        messages: list[dict[str, Any]],
        model: str,
    ) -> list[dict[str, Any]]:
        """Add prompt caching annotations to the system message when supported.

        Args:
            messages: Pre-built chat completion messages.
            model: Model name used to determine prompt caching support.

        Returns:
            The original message list with cache-control metadata added for supported models.
        """
        if LitellmModel._supports_prompt_caching_for_model(model):
            for message in messages:
                if message.get("role") == "system":
                    # Only set a default cache_control if the caller has not specified one.
                    if "cache_control" not in message:
                        message["cache_control"] = {"type": "ephemeral"}
                    break

        return messages

    def _add_system_instructions(self, converted_messages: list[dict[str, Any]], system_instructions: str) -> None:
        """Add system instructions with cache control if supported."""
        if self._supports_prompt_caching():
            converted_messages.insert(
                0,
                {
                    "content": system_instructions,
                    "role": "system",
                    "cache_control": {"type": "ephemeral"},
                },
            )
        else:
            converted_messages.insert(
                0,
                {
                    "content": system_instructions,
                    "role": "system",
                },
            )

    def _log_llm_call(
        self,
        converted_messages: list[dict[str, Any]],
        converted_tools: list[dict[str, Any]],
        stream: bool,
        tool_choice: Any,
        response_format: Any,
    ) -> None:
        """Log debug information for LLM call."""
        if _debug.DONT_LOG_MODEL_DATA:
            logger.debug("Calling LLM")
        else:
            logger.debug(
                f"Calling Litellm model: {self.model}\n"
                f"{json.dumps(converted_messages, indent=2, ensure_ascii=False)}\n"
                f"Tools:\n{json.dumps(converted_tools, indent=2, ensure_ascii=False)}\n"
                f"Stream: {stream}\n"
                f"Tool choice: {tool_choice}\n"
                f"Response format: {response_format}\n"
            )

    @staticmethod
    def _get_parallel_tool_calls_setting(model_settings: ModelSettings, tools: list[Tool]) -> bool | None:
        """Determine parallel tool calls setting."""
        if model_settings.parallel_tool_calls and tools and len(tools) > 0:
            return True
        elif model_settings.parallel_tool_calls is False:
            return False
        return None

    @staticmethod
    def _get_stream_options(stream: bool, model_settings: ModelSettings) -> dict[str, Any] | None:
        """Get stream options if needed."""
        if stream and model_settings.include_usage is not None:
            return {"include_usage": model_settings.include_usage}
        return None

    @staticmethod
    def _build_extra_kwargs(model_settings: ModelSettings) -> dict[str, Any]:
        """Build extra kwargs from model settings.

        Note: We create a copy of metadata to prevent LiteLLM from mutating
        the original model_settings.metadata object, which would cause Pydantic
        validation errors when the agents SDK tries to use dataclasses.replace().
        """
        extra_kwargs = {}
        if model_settings.extra_query:
            extra_kwargs["extra_query"] = model_settings.extra_query
        if model_settings.metadata:
            # Create a deep copy to prevent LiteLLM from mutating the original
            extra_kwargs["metadata"] = copy.deepcopy(model_settings.metadata)
        if model_settings.extra_body and isinstance(model_settings.extra_body, dict):
            extra_kwargs.update(model_settings.extra_body)
        if hasattr(model_settings, "extra_args") and model_settings.extra_args:
            extra_kwargs.update(model_settings.extra_args)
        return extra_kwargs

    @staticmethod
    def _remove_not_given(value: Any) -> Any:
        """Normalise "not provided" sentinels to None before calling LiteLLM.

        The `agents` SDK uses the OpenAI Python SDK's internal sentinels
        (e.g. `openai.Omit`) when a field is intentionally omitted.

        LiteLLM's `tool_choice` validation expects either:
        - a string: "auto" | "required" | "none"
        - or an OpenAI-spec dict
        - or `None`

        Passing `openai.Omit` through triggers: "Invalid tool choice".
        """
        # Sentinel used by OpenAI SDK to indicate a parameter should be omitted.
        # We don't want to pass that through to LiteLLM.
        if type(value).__name__ == "Omit":
            return None

        if isinstance(value, NotGiven):
            return None

        return value

    def _handle_litellm_exception(self, error: Exception, context: str = "litellm_model._fetch_response") -> None:
        """Handle and log LiteLLM exceptions with appropriate context.

        Args:
            error: The exception that was raised
            context: Context string for logging

        Raises:
            ValueError: Always raises with user-friendly error message
        """
        error_details = {
            "model": self.model,
            "base_url": self.base_url,
            "error_type": type(error).__name__,
        }

        log_error(error, context=context, **error_details)

        # Convert to ValueError with user-friendly messages
        if isinstance(error, getattr(litellm.exceptions, "BadRequestError", type(None))):
            raise ValueError(
                f"Invalid model request for '{self.model}': {error!s}. Please check model name and configuration."
            ) from error
        elif isinstance(error, getattr(litellm.exceptions, "AuthenticationError", type(None))):
            raise ValueError(
                f"Authentication failed for model '{self.model}': {error!s}. Please verify API credentials."
            ) from error
        elif isinstance(error, getattr(litellm.exceptions, "RateLimitError", type(None))):
            raise ValueError(
                f"Rate limit exceeded for model '{self.model}': {error!s}. Please retry after some time."
            ) from error
        elif isinstance(error, getattr(litellm.exceptions, "ServiceUnavailableError", type(None))):
            raise ValueError(
                f"Model service unavailable for '{self.model}': {error!s}. Please try again later."
            ) from error
        elif isinstance(error, getattr(litellm.exceptions, "Timeout", type(None))):
            raise ValueError(
                f"Model request timeout for '{self.model}': {error!s}. Please retry or adjust timeout settings."
            ) from error
        else:
            # Generic exception handling
            raise ValueError(f"Unexpected error calling model '{self.model}': {error!s}") from error


class LitellmConverter:
    @classmethod
    def convert_message_to_openai(cls, message: litellm.types.utils.Message) -> ChatCompletionMessage:
        if message.role != "assistant":
            raise ModelBehaviorError(f"Unsupported role: {message.role}")

        tool_calls = (
            [LitellmConverter.convert_tool_call_to_openai(tool) for tool in message.tool_calls]
            if message.tool_calls
            else None
        )

        provider_specific_fields = message.get("provider_specific_fields", None)
        refusal = provider_specific_fields.get("refusal", None) if provider_specific_fields else None

        reasoning_content = ""
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            reasoning_content = message.reasoning_content

        return InternalChatCompletionMessage(
            content=message.content,
            refusal=refusal,
            role="assistant",
            annotations=cls.convert_annotations_to_openai(message),
            audio=message.get("audio", None),  # litellm deletes audio if not present
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
        )

    @classmethod
    def convert_annotations_to_openai(cls, message: litellm.types.utils.Message) -> list[Annotation] | None:
        annotations: list[litellm.types.llms.openai.ChatCompletionAnnotation] | None = message.get("annotations", None)
        if not annotations:
            return None

        return [
            Annotation(
                type="url_citation",
                url_citation=AnnotationURLCitation(
                    start_index=annotation["url_citation"]["start_index"],
                    end_index=annotation["url_citation"]["end_index"],
                    url=annotation["url_citation"]["url"],
                    title=annotation["url_citation"]["title"],
                ),
            )
            for annotation in annotations
        ]

    @classmethod
    def convert_tool_call_to_openai(
        cls, tool_call: litellm.types.utils.ChatCompletionMessageToolCall
    ) -> ChatCompletionMessageToolCall:
        return ChatCompletionMessageToolCall(
            id=tool_call.id,
            type="function",
            function=Function(
                name=tool_call.function.name or "",
                arguments=tool_call.function.arguments,
            ),
        )
