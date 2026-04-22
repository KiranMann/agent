"""LLM-based Reranker Service Module.

This module provides functionality to rerank documents for improving RAG (Retrieval-Augmented
Generation) search result relevance using available LLM models. It uses the existing OpenAI-compatible
API to perform intelligent reranking based on query-document relevance.

The service follows Financial Companion patterns for authentication, error handling,
caching, and logging. It supports both production and development environments with
proper fallback mechanisms.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx

from common.configs.agent_config_settings import AgentConfig
from common.configs.app_config_settings import AppConfig
from common.logging.core import log_error, logger
from common.services.service_api_base import AuthType, ServiceAPIBase

# Constants
CACHE_SIZE_LIMIT = 1000
HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_TOO_MANY_REQUESTS = 429


@dataclass
class RerankResult:
    """Represents a single reranked result."""

    index: int
    relevance_score: float
    document: dict[str, Any]


@dataclass
class RerankResponse:
    """Represents the complete response from rerank API."""

    results: list[RerankResult]
    meta: dict[str, Any]


class LLMRerankerService(ServiceAPIBase):
    """LLM-based reranker for improving RAG search result relevance.

    This service uses available LLM models to intelligently rerank retrieved documents
    based on query relevance. It includes comprehensive error handling, caching capabilities,
    and follows Financial Companion service patterns.

    Features:
    - Uses existing OpenAI-compatible API infrastructure
    - Configurable result limits and thresholds
    - Caching for performance optimization
    - Comprehensive error handling with fallbacks
    - User context integration for personalized reranking
    - Feature flag support for gradual rollout
    """

    def __init__(
        self,
        name: str = "LLM-Reranker-Service",
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        top_n: int | None = None,
        enable_caching: bool = True,
        cache_ttl_seconds: int = 300,  # 5 minutes default
    ):
        """Initialize the LLMRerankerService instance.

        Args:
            name: Identifier for the service instance
            base_url: Base URL for the API endpoints. If None, uses Config.OPENAI_BASE_URL
            api_key: API key. If None, uses Config.OPENAI_API_KEY
            model: Reranking model to use. If None, uses Config.RERANKER_MODEL or defaults to Claude
            top_n: Maximum number of results to return after reranking
            enable_caching: Whether to enable response caching
            cache_ttl_seconds: Cache time-to-live in seconds

        Raises:
            ValueError: If API key is not provided and not set in config
        """
        # Get configuration from parameters or config
        self._api_key = api_key or AppConfig.OPENAI_API_KEY
        self._base_url = base_url or AppConfig.OPENAI_BASE_URL
        self._model = model or getattr(AppConfig, "RERANKER_MODEL", "bedrock-claude-4-5-haiku")
        # Ensure _top_n is always an int
        config_top_n = getattr(AppConfig, "RERANKER_TOP_N", 20)
        self._top_n: int = top_n if top_n is not None else config_top_n

        # Caching configuration
        self._enable_caching = enable_caching
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, dict[str, Any]] = {}

        # Validate API key
        if not self._api_key:
            logger.error("OPENAI_API_KEY must be set in environment variables or provided as parameter")
            self._credentials_valid = False
        else:
            self._credentials_valid = True
            logger.info(f"LLM Reranker Service initialized with model: {self._model}")

        # Initialize base service
        super().__init__(
            name=name,
            base_url=self._base_url,
            client_id="",  # Not used for OpenAI API
            scope="",  # Not used for OpenAI API
        )

    def _get_cache_key(self, query: str, documents: list[dict[str, Any]], **kwargs: Any) -> str:
        """Generate cache key for rerank request."""
        # Create a deterministic hash of the request parameters
        cache_data = {
            "query": query,
            "documents": [doc.get("text", "") for doc in documents],
            "model": self._model,
            "top_n": kwargs.get("top_n", self._top_n),
        }
        cache_string = str(sorted(cache_data.items()))
        return hashlib.sha256(cache_string.encode()).hexdigest()

    def _get_cached_result(self, cache_key: str) -> RerankResponse | None:
        """Retrieve cached rerank result if valid."""
        if not self._enable_caching or cache_key not in self._cache:
            return None

        cached_entry = self._cache[cache_key]
        if time.time() - cached_entry["timestamp"] > self._cache_ttl_seconds:
            # Cache expired, remove entry
            del self._cache[cache_key]
            return None

        logger.debug(f"Cache hit for rerank request: {cache_key}")
        return cached_entry["result"]  # type: ignore[no-any-return]

    def _cache_result(self, cache_key: str, result: RerankResponse) -> None:
        """Cache rerank result."""
        if not self._enable_caching:
            return

        self._cache[cache_key] = {"result": result, "timestamp": time.time()}

        # Simple cache cleanup - remove oldest entries if cache gets too large
        if len(self._cache) > CACHE_SIZE_LIMIT:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k]["timestamp"])
            del self._cache[oldest_key]

    async def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_n: int | None = None,
        model: str | None = None,
        user_context: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> RerankResponse:
        """Rerank documents based on query relevance using LLM.

        Args:
            query: The search query to rerank documents against
            documents: List of documents to rerank. Each document should have 'text' field
            top_n: Maximum number of results to return (overrides instance default)
            model: Reranking model to use (overrides instance default)
            user_context: Optional user context for personalized reranking
            headers: Optional additional headers

        Returns:
            RerankResponse: Reranked results with relevance scores

        Raises:
            Exception: On API errors or invalid responses
        """
        # Check if reranking is enabled via configuration
        enable_reranking = getattr(AgentConfig, "ENABLE_RAG_RERANKING", True)
        if not enable_reranking:
            logger.debug("LLM reranker disabled by configuration, returning original order")
            return self._create_fallback_response(documents)

        if not self._credentials_valid:
            logger.error("Invalid API credentials - returning original document order")
            return self._create_fallback_response(documents)

        if not documents:
            logger.warning("No documents provided for reranking")
            return RerankResponse(results=[], meta={})

        # Use provided parameters or fall back to instance defaults
        effective_top_n = top_n or self._top_n
        effective_model = model or self._model

        # Check cache first
        cache_key = self._get_cache_key(query, documents, top_n=effective_top_n)

        cached_result = self._get_cached_result(cache_key)
        if cached_result:
            return cached_result

        logger.info(f"Reranking {len(documents)} documents with query: {query[:100]}...")

        try:
            # Create reranking prompt
            rerank_prompt = self._create_reranking_prompt(query, documents, user_context)

            # Prepare request payload for chat completion
            chat_data = {
                "model": effective_model,
                "messages": [{"role": "user", "content": rerank_prompt}],
                "temperature": 0.1,  # Low temperature for consistent ranking
                "max_tokens": 2000,
            }

            # Prepare headers
            request_headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            if headers:
                request_headers.update(headers)

            # Make API call
            response = await self.post_call(
                path="/v1/chat/completions",
                payload=chat_data,
                headers=request_headers,
                auth_type=AuthType.NONE,  # We handle auth in headers
            )

            # Handle response
            if response.status_code == HTTP_OK:
                response_data = response.json()
                rerank_response = self._parse_llm_rerank_response(response_data, documents, int(effective_top_n))

                # Cache successful result
                self._cache_result(cache_key, rerank_response)

                logger.info(f"Successfully reranked documents, returned {len(rerank_response.results)} results")
                return rerank_response

            elif response.status_code == HTTP_BAD_REQUEST:
                logger.error(f"Bad request to LLM rerank API: {response.text}")
                return self._create_fallback_response(documents)

            elif response.status_code == HTTP_UNAUTHORIZED:
                logger.error("Unauthorized access to LLM rerank API - check API key")
                return self._create_fallback_response(documents)

            elif response.status_code == HTTP_TOO_MANY_REQUESTS:
                logger.warning("Rate limit exceeded for LLM rerank API")
                return self._create_fallback_response(documents)

            else:
                logger.error(f"LLM rerank API error: {response.status_code} - {response.text}")
                return self._create_fallback_response(documents)

        except httpx.TimeoutException as e:
            log_error(e, context="llm_rerank_timeout")
            logger.warning("LLM rerank API timeout - returning original document order")
            return self._create_fallback_response(documents)

        except Exception as e:
            log_error(e, context="llm_rerank_error", query=query[:100])
            logger.error(f"Unexpected error during reranking: {e!s}")
            return self._create_fallback_response(documents)

    def _create_reranking_prompt(
        self,
        query: str,
        documents: list[dict[str, Any]],
        user_context: dict[str, Any] | None = None,
    ) -> str:
        """Create a prompt for LLM-based reranking."""
        # Build document list for the prompt
        doc_list = []
        for i, doc in enumerate(documents):
            text = doc.get("text", str(doc))
            doc_list.append(f"Document {i}: {text}")

        # Add user context if available
        context_info = ""
        if user_context and user_context.get("agent_type"):
            context_info = f"\nUser is currently using the {user_context['agent_type']} agent."

        prompt = f"""You are a document relevance expert. Given a user query and a list of documents, rank the documents by their relevance to the query. Return only a JSON array of document indices in order of relevance (most relevant first).

Query: {query}{context_info}

Documents:
{chr(10).join(doc_list)}

Instructions:
1. Analyze each document's relevance to the query
2. Consider semantic meaning, not just keyword matching
3. Return a JSON array of document indices (0-based) in order of relevance
4. Include only the most relevant documents (up to {min(len(documents), int(self._top_n))})
5. Format: [0, 3, 1, 5, ...]
6. Your response should contain ONLY the JSON array, with no additional text, explanation, or formatting.

Response:"""

        return prompt

    def _parse_llm_rerank_response(
        self,
        response_data: dict[str, Any],
        original_documents: list[dict[str, Any]],
        top_n: int,
    ) -> RerankResponse:
        """Parse LLM API response into RerankResponse object."""
        results = []

        try:
            # Extract the content from the LLM response
            content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")

            # Try to parse JSON from the response
            # Look for JSON array in the response
            json_match = re.search(r"\[[\d,\s]+\]", content)
            # Fallback: try to parse the entire content as JSON
            ranked_indices = json.loads(json_match.group()) if json_match else json.loads(content.strip())

            # Create results based on ranked indices
            for rank, index in enumerate(ranked_indices[:top_n]):
                if 0 <= index < len(original_documents):
                    document = original_documents[index].copy()
                    # Calculate relevance score based on rank (higher rank = lower score)
                    relevance_score = 1.0 - (rank * 0.05)  # Decreasing scores
                    document["rerank_score"] = relevance_score
                    document["original_index"] = index

                    results.append(
                        RerankResult(
                            index=index,
                            relevance_score=relevance_score,
                            document=document,
                        )
                    )

        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            logger.warning(f"Failed to parse LLM reranking response: {e}")
            # Fallback to original order
            return self._create_fallback_response(original_documents)

        meta = {"model": self._model, "total_results": len(results), "reranked": True}

        return RerankResponse(results=results, meta=meta)

    def _create_fallback_response(self, documents: list[dict[str, Any]]) -> RerankResponse:
        """Create fallback response when reranking fails."""
        results = []

        for i, doc in enumerate(documents):
            doc_copy = doc.copy()
            doc_copy["rerank_score"] = 1.0 - (i * 0.01)  # Decreasing scores
            doc_copy["original_index"] = i

            results.append(RerankResult(index=i, relevance_score=1.0 - (i * 0.01), document=doc_copy))

        meta = {"model": "fallback", "total_results": len(results), "reranked": False}

        return RerankResponse(results=results, meta=meta)

    async def health_check(self) -> bool:
        """Check if the LLM rerank service is available.

        Returns:
            bool: True if service is healthy, False otherwise
        """
        if not self._credentials_valid:
            return False

        try:
            # Simple test with minimal data
            test_response = await self.rerank(query="test", documents=[{"text": "test document"}], top_n=1)
            return bool(test_response.meta.get("reranked", False))

        except Exception as e:
            log_error(e, context="llm_rerank_health_check")
            return False

    def clear_cache(self) -> None:
        """Clear the reranking cache."""
        self._cache.clear()
        logger.info("LLM reranker cache cleared")

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "cache_size": len(self._cache),
            "cache_enabled": self._enable_caching,
            "cache_ttl_seconds": self._cache_ttl_seconds,
        }


# Create singleton instance for module-level access
@lru_cache(maxsize=1)
def get_llm_reranker_service() -> LLMRerankerService:
    """Get or create the global LLM reranker service instance."""
    return LLMRerankerService()


# Module-level convenience function
async def rerank_documents(
    query: str,
    documents: list[dict[str, Any]],
    top_n: int | None = None,
    user_context: dict[str, Any] | None = None,
) -> RerankResponse:
    """Convenience function to rerank documents using the global service instance.

    Args:
        query: The search query
        documents: List of documents to rerank
        top_n: Maximum number of results to return
        user_context: Optional user context for personalization

    Returns:
        RerankResponse: Reranked results
    """
    service = get_llm_reranker_service()
    return await service.rerank(query=query, documents=documents, top_n=top_n, user_context=user_context)
