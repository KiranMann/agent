"""This module contains the RagKnowledgeBaseClient class.

This class provides a client for interacting with an AWS Bedrock Knowledge Base using the
Bedrock Agent Runtime service. It supports both local development (using explicit AWS credentials)
and production (using IAM roles or default credentials).

If AWS credentials are set in the environment or config (e.g., via .env.local), they will be used
for authentication. Otherwise, the default AWS credential provider chain is used (e.g., ECS Task Role,
EC2 Instance Role, etc.).
"""

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast, overload

from common.models.feature_flags import FeatureFlags
from common.services.launchdarkly_service import get_string_feature_flag

if TYPE_CHECKING:
    from common.services.llm_reranker_service import LLMRerankerService

from urllib.parse import urlparse

import boto3

from common.configs.app_config_settings import AppConfig
from common.logging.core import log_error, logger
from common.services.llm_reranker_service import get_llm_reranker_service
from common.utils.runtime_utils import IN_DEV


@dataclass
class MetaDataResult:
    """Represents a single MetaDataResult from the knowledge base. source-uri s3 bucket path is removed."""

    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Automatically parses the source-uri, removing bucket prefix and validates URLs."""
        url = self.metadata.get("url", "")
        uri = self.metadata.get("x-amz-bedrock-kb-source-uri", "")
        if not url and uri.startswith(
            (
                "https://www.cfs.com.au",
                "http://www.cfs.com.au",
                "https://www.commsec.com.au",
                "http://www.commsec.com.au",
                "http://www.commbank.com.au",
                "https://www.commbank.com.au",
                "http://policy.poweredbycovermore.com",
                "https://policy.poweredbycovermore.com",
                "https://www2.commsec.com.au",
                "http://www2.commsec.com.au",
            )
        ):
            # If URL is empty and URI is a web URL, use the URI
            self.metadata["url"] = uri
        parsed = urlparse(uri)
        self.metadata["x-amz-bedrock-kb-source-uri"] = parsed.path.lstrip("/")


class RagKnowledgeBaseClient:
    """Client for querying an AWS Bedrock Knowledge Base using the Bedrock Agent Runtime API.

    - In local development, uses explicit AWS credentials and disables SSL verification.
    - In production, relies on IAM roles or default AWS credential resolution.
    """

    def __init__(
        self,
        max_results: int = 10,
        search_type: str = "SEMANTIC",
        similarity_threshold: float = 0.3,
        enable_score_filtering: bool = True,
        enable_deduplication: bool = True,
        dedup_similarity_threshold: float = 0.90,
        enable_reranking: bool = True,
        reranker_top_n: int | None = None,
    ):
        """Initialize the Bedrock Knowledge Base client.

        Args:
            max_results: Maximum number of results to retrieve
            search_type: Type of search - SEMANTIC, HYBRID, or KEYWORD
            similarity_threshold: Minimum similarity score for filtering
            enable_score_filtering: Whether to filter results by similarity threshold
            enable_deduplication: Whether to remove duplicate/similar chunks (default: True)
            dedup_similarity_threshold: Similarity threshold for deduplication (default: 0.90)
            enable_reranking: Whether to enable LLM-based reranking of results (default: True)
            reranker_top_n: Maximum number of results to return after reranking (uses Config.RERANKER_TOP_N if None)

        Raises:
            ValueError: If required knowledge base config values are missing.
        """
        # Store optimisation parameters
        self.max_results = max_results
        self.search_type = search_type
        self.similarity_threshold = similarity_threshold
        self.enable_score_filtering = enable_score_filtering

        # Store deduplication parameters
        self.enable_deduplication = enable_deduplication

        # Validate dedup_similarity_threshold is within valid range [0.0, 1.0]
        if not (0.0 <= dedup_similarity_threshold <= 1.0):
            raise ValueError("dedup_similarity_threshold must be between 0.0 and 1.0")
        self.dedup_similarity_threshold = dedup_similarity_threshold

        # Store reranking parameters
        self.enable_reranking = enable_reranking
        # Ensure reranker_top_n is always an int
        config_top_n = getattr(AppConfig, "RERANKER_TOP_N", 20)
        self.reranker_top_n: int = reranker_top_n if reranker_top_n is not None else config_top_n

        # Initialize reranker service if enabled
        self._reranker_service = None
        if self.enable_reranking:
            self._reranker_service = self._initialize_reranker_service()

        client_kwargs = {
            "service_name": "bedrock-agent-runtime",
            "region_name": os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2"),
        }

        # Local development
        if IN_DEV:
            dev_kwargs: dict[str, Any] = {
                "aws_access_key_id": AppConfig.AWS_ACCESS_KEY_ID,
                "aws_secret_access_key": AppConfig.AWS_SECRET_ACCESS_KEY,
                "aws_session_token": AppConfig.AWS_SESSION_TOKEN,
                "verify": False,
            }
            client_kwargs.update(dev_kwargs)

        self.client = boto3.client(**client_kwargs)  # type: ignore[call-overload, unused-ignore]
        self.knowledge_base_id: str | None = None  # Will be set by update_kb_id()
        self.model_arn = AppConfig.RAG_KNOWLEDGE_BASE_MODEL

        if not self.model_arn:
            raise ValueError("RAG_KNOWLEDGE_BASE_MODEL must be set in the environment or config.")

        self.update_kb_id()
        if not self.knowledge_base_id:
            raise ValueError("RAG_KNOWLEDGE_BASE_ID must be set in the environment or config.")

    def update_kb_id(self) -> None:
        """Update knowledge base ID from LaunchDarkly feature flag.

        This is called before each retrieve() to allow dynamic KB switching.
        """
        previous_kb_id = getattr(self, "knowledge_base_id", None)
        self.knowledge_base_id = get_string_feature_flag(
            FeatureFlags.USE_LD_KNOWLEDGE_BASE_ID, default_value=AppConfig.RAG_KNOWLEDGE_BASE_ID
        )
        if self.knowledge_base_id != previous_kb_id:
            logger.info(f"Using Knowledge Base ID: {self.knowledge_base_id}")
        else:
            logger.debug(f"Using Knowledge Base ID (unchanged): {self.knowledge_base_id}")

    def _initialize_reranker_service(self) -> "LLMRerankerService | None":
        """Initialize the reranker service if available."""
        try:
            service = get_llm_reranker_service()
            logger.info("LLM reranker service initialized")
            return service
        except Exception as e:
            log_error(e, context="initialize_reranker_service")
            logger.warning("Failed to initialize reranker service, disabling reranking")
            self.enable_reranking = False
            return None

    async def retrieve(
        self,
        question: str,
        get_metadata: bool = False,
        metadata_filter_key: str = "",
        metadata_filter_value: str = "",
        user_context: dict[str, Any] | None = None,
        enable_reranking: bool | None = None,
    ) -> list[str] | list[MetaDataResult]:
        """Retrieve relevant documents/passages from the knowledge base.

        Args:
            question (str): The input question to search for.
            get_metadata (bool): If True, return a list of MetaDataResult objects (with text, score, and metadata).
                                 If False (default), return a list of text strings only.
            metadata_filter_key (str): Metadata key to filter results by (optional).
            metadata_filter_value (str): Metadata value to filter results by (optional).
            user_context (Optional[Dict[str, Any]]): User context for personalized reranking (optional).
            enable_reranking (Optional[bool]): Override instance reranking setting for this query (optional).

        Returns:
            List[str]: List of retrieved text passages if get_metadata is False.
            List[MetaDataResult]: List of metadata result objects if get_metadata is True.

        Example MetaDataResult:
            MetaDataResult(
                text="The retrieved passage text.",
                score=0.0,
                metadata={
                    "x-amz-bedrock-kb-source-uri": "",
                    "x-amz-bedrock-kb-chunk-id": "",
                    "x-amz-bedrock-kb-data-source-id": ""
                }
            )
        """
        # Build optimised retrieval configuration
        retrieval_config: dict[str, Any] = {
            "vectorSearchConfiguration": {
                "numberOfResults": min(self.max_results, 100),
            }
        }

        # Add search type configuration
        if self.search_type == "HYBRID":
            retrieval_config["vectorSearchConfiguration"]["overrideSearchType"] = "HYBRID"
        elif self.search_type == "SEMANTIC":
            retrieval_config["vectorSearchConfiguration"]["overrideSearchType"] = "SEMANTIC"

        # Add metadata filters if provided
        if metadata_filter_key and metadata_filter_value:
            retrieval_config["vectorSearchConfiguration"]["filter"] = {
                "equals": {
                    "key": metadata_filter_key,
                    "value": metadata_filter_value,
                }
            }
            logger.info(f"Knowledge base retrieval with metadata filtering for key = {metadata_filter_key}")
        else:
            logger.info("Knowledge base retrieval without metadata filtering")

        # Execute retrieval with optimized configuration
        self.update_kb_id()
        response = self.client.retrieve(
            knowledgeBaseId=self.knowledge_base_id,
            retrievalQuery={"text": question},
            retrievalConfiguration=retrieval_config,
        )

        # Process results with optional similarity filtering
        results = []
        for result in response.get("retrievalResults", []):
            score = result.get("score", 0.0)

            # Apply similarity threshold filtering if enabled
            if self.enable_score_filtering and score < self.similarity_threshold:
                continue

            if get_metadata:
                results.append(
                    MetaDataResult(
                        text=result.get("content", {}).get("text", ""),
                        score=score,
                        metadata=result.get("metadata", {}),
                    )
                )
            else:
                results.append(result.get("content", {}).get("text", ""))

        # Apply deduplication if enabled
        results = self._apply_deduplication(results, get_metadata)

        # Apply reranking if enabled and we have results
        should_rerank = enable_reranking if enable_reranking is not None else self.enable_reranking
        if should_rerank and results and self._reranker_service:
            # mypy: The _apply_reranking method preserves the input type based on get_metadata
            results = await self._apply_reranking(  # type: ignore[assignment]
                results, question, get_metadata, user_context
            )

        return results

    @staticmethod
    def _calculate_jaccard_similarity(text1: str, text2: str) -> float:
        """Calculate Jaccard similarity between two texts using word sets.

        Args:
            text1: First text to compare
            text2: Second text to compare

        Returns:
            float: Jaccard similarity score between 0.0 and 1.0
        """
        try:
            # Handle very large texts by truncating if necessary (prevent memory issues)
            max_text_length = 50000  # Reasonable limit for similarity calculation
            if len(text1) > max_text_length:
                logger.warning(f"Text1 length ({len(text1)}) exceeds limit, truncating for similarity calculation")
                text1 = text1[:max_text_length]
            if len(text2) > max_text_length:
                logger.warning(f"Text2 length ({len(text2)}) exceeds limit, truncating for similarity calculation")
                text2 = text2[:max_text_length]

            # Fast tokenisation and normalisation
            words1 = set(text1.lower().split())
            words2 = set(text2.lower().split())

            # Early exit for empty texts
            if len(words1) == 0 and len(words2) == 0:
                return 1.0
            if len(words1) == 0 or len(words2) == 0:
                return 0.0

            # Calculate Jaccard similarity with error handling for set operations
            intersection_size = len(words1 & words2)
            union_size = len(words1 | words2)

            return intersection_size / union_size if union_size > 0 else 0.0

        except MemoryError as e:
            logger.error(f"Memory error during similarity calculation: {e}")
            return 0.0
        except Exception as e:
            logger.error(f"Unexpected error during similarity calculation: {e}")
            return 0.0

    def _deduplicate_results(self, results: list[MetaDataResult]) -> list[MetaDataResult]:
        """Remove duplicate/similar results based on text similarity.

        Args:
            results: List of MetaDataResult objects to deduplicate

        Returns:
            list[MetaDataResult]: Deduplicated results with highest-scoring duplicates kept
        """
        if not results or len(results) <= 1:
            return results

        deduplicated: list[MetaDataResult] = []

        for current_result in results:
            duplicate_index = self._find_duplicate_index(current_result, deduplicated)

            if duplicate_index is None:
                deduplicated.append(current_result)
            elif current_result.score > deduplicated[duplicate_index].score:
                deduplicated[duplicate_index] = current_result

        return deduplicated

    def _find_duplicate_index(self, result: MetaDataResult, existing: list[MetaDataResult]) -> int | None:
        """Find the index of a duplicate result in the existing list.

        Args:
            result: The result to check for duplicates
            existing: List of existing results to check against

        Returns:
            int | None: Index of duplicate if found, None otherwise
        """
        for i, existing_result in enumerate(existing):
            similarity = self._calculate_jaccard_similarity(result.text, existing_result.text)
            if similarity >= self.dedup_similarity_threshold:
                return i
        return None

    @overload
    def _apply_deduplication(self, results: list[MetaDataResult], get_metadata: bool) -> list[MetaDataResult]: ...

    @overload
    def _apply_deduplication(self, results: list[str], get_metadata: bool) -> list[str]: ...

    def _apply_deduplication(
        self, results: list[str] | list[MetaDataResult], get_metadata: bool
    ) -> list[str] | list[MetaDataResult]:
        """Apply deduplication to results if enabled.

        Args:
            results: List of results (either strings or MetaDataResult objects)
            get_metadata: Whether results contain metadata objects

        Returns:
            list: Deduplicated results with same type as input
        """
        if self.enable_deduplication and get_metadata and len(results) > 1:
            results = self._deduplicate_results(cast("list[MetaDataResult]", results))
            logger.info(f"After deduplication: {len(results)} chunks remain.")
        elif not get_metadata and self.enable_deduplication and len(results) > 1:
            # For text-only results, convert to MetaDataResult temporarily for deduplication
            temp_results = [MetaDataResult(text=str(text), score=0.0, metadata={}) for text in results]
            deduplicated = self._deduplicate_results(temp_results)
            results = [result.text for result in deduplicated]
            logger.info(f"After deduplication: {len(results)} chunks remain.")
        else:
            logger.info(f"Retrieved {len(results)} chunks after filtering.")

        return results

    async def _apply_reranking(
        self,
        results: list[str] | list[MetaDataResult],
        query: str,
        get_metadata: bool,
        user_context: dict[str, Any] | None = None,
    ) -> list[str] | list[MetaDataResult]:
        """Apply LLM-based reranking to results if enabled and available.

        Args:
            results: List of results (either strings or MetaDataResult objects)
            query: The original search query
            get_metadata: Whether results contain metadata objects
            user_context: Optional user context for personalized reranking

        Returns:
            List: Reranked results with same type as input
        """
        try:
            if not self._reranker_service or not results:
                return results

            logger.info(f"Applying LLM reranking to {len(results)} results")

            # Convert results to documents format expected by reranker
            documents = []
            for i, result in enumerate(results):
                if get_metadata and isinstance(result, MetaDataResult):
                    doc = {
                        "text": result.text,
                        "original_score": result.score,
                        "metadata": result.metadata,
                        "original_index": i,
                    }
                else:
                    doc = {
                        "text": str(result),
                        "original_score": 1.0 - (i * 0.01),  # Synthetic score based on position
                        "original_index": i,
                    }
                documents.append(doc)

            # Process user context for reranking
            rerank_context = self._process_user_context_for_reranking(user_context)

            # Perform reranking
            rerank_response = await self._reranker_service.rerank(
                query=query,
                documents=documents,
                top_n=min(self.reranker_top_n, len(documents)),
                user_context=rerank_context,
            )

            # Convert reranked results back to original format
            reranked_results = []
            for rerank_result in rerank_response.results:
                original_index = rerank_result.document.get("original_index", 0)

                if get_metadata:
                    # Create new MetaDataResult with reranking information
                    original_result = results[original_index]
                    if isinstance(original_result, MetaDataResult):
                        # Add reranking metadata
                        enhanced_metadata = original_result.metadata.copy()
                        enhanced_metadata["rerank_score"] = rerank_result.relevance_score
                        enhanced_metadata["original_score"] = original_result.score
                        enhanced_metadata["reranked"] = True

                        reranked_results.append(
                            MetaDataResult(
                                text=original_result.text,
                                score=rerank_result.relevance_score,
                                metadata=enhanced_metadata,
                            )
                        )
                else:
                    # Return text only
                    reranked_results.append(results[original_index])

            logger.info(f"Reranking completed: {len(reranked_results)} results returned")
            return reranked_results

        except Exception as e:
            log_error(e, context="rag_reranking", query=query[:100])
            logger.warning("Reranking failed, returning original results")
            return results

    def _extract_agent_type_for_reranking(self, user_context: dict[str, Any]) -> dict[str, str]:
        """Extract agent type information for reranking.

        Args:
            user_context: Raw user context data

        Returns:
            Dict containing agent_type if found
        """
        if "agent_type" in user_context:
            return {"agent_type": user_context["agent_type"]}
        elif "current_agent" in user_context:
            return {"agent_type": user_context["current_agent"]}
        return {}

    def _extract_preferences_for_reranking(self, user_context: dict[str, Any]) -> dict[str, Any]:
        """Extract user preferences for reranking (PII-safe).

        Args:
            user_context: Raw user context data

        Returns:
            Dict containing safe preferences if found
        """
        if "preferences" not in user_context:
            return {}

        prefs = user_context["preferences"]
        if not isinstance(prefs, dict):
            return {}

        safe_prefs: dict[str, bool] = {}
        allowed_keys = [
            "financial_goals",
            "investment_experience",
            "risk_tolerance",
        ]

        for key, value in prefs.items():
            if key in allowed_keys:
                safe_prefs[key] = bool(value)  # Convert to boolean to avoid PII

        return {"preferences": safe_prefs} if safe_prefs else {}

    def _extract_topic_for_reranking(self, user_context: dict[str, Any]) -> dict[str, str]:
        """Extract current topic information for reranking.

        Args:
            user_context: Raw user context data

        Returns:
            Dict containing current_topic if found
        """
        if "current_topic" in user_context:
            return {"current_topic": user_context["current_topic"]}
        return {}

    def _process_user_context_for_reranking(self, user_context: dict[str, Any] | None) -> dict[str, Any] | None:
        """Process user context for reranking service.

        Args:
            user_context: Raw user context data

        Returns:
            Optional[Dict[str, Any]]: Processed context for reranker
        """
        if not user_context:
            return None

        try:
            processed_context = {}

            # Extract agent type
            agent_info = self._extract_agent_type_for_reranking(user_context)
            processed_context.update(agent_info)

            # Extract user preferences (be careful with PII)
            preferences_info = self._extract_preferences_for_reranking(user_context)
            processed_context.update(preferences_info)

            # Extract current topic or focus
            topic_info = self._extract_topic_for_reranking(user_context)
            processed_context.update(topic_info)

            return processed_context if processed_context else None

        except Exception as e:
            log_error(e, context="process_user_context_for_reranking")
            return None

    def set_reranking_enabled(self, enabled: bool) -> None:
        """Enable or disable reranking for this client instance.

        Args:
            enabled: Whether to enable reranking
        """
        if enabled and not self._reranker_service:
            self._reranker_service = self._initialize_reranker_service()
            if not self._reranker_service:
                enabled = False

        self.enable_reranking = enabled
        logger.info(f"Reranking {'enabled' if enabled else 'disabled'} for RAG client")

    def get_reranking_stats(self) -> dict[str, Any]:
        """Get reranking statistics and configuration.

        Returns:
            Dict[str, Any]: Reranking configuration and stats
        """
        stats = {
            "reranking_enabled": self.enable_reranking,
            "reranker_top_n": self.reranker_top_n,
            "reranker_service_available": self._reranker_service is not None,
        }

        if self._reranker_service:
            try:
                stats.update(self._reranker_service.get_cache_stats())
            except Exception as e:
                log_error(e, context="get_reranking_stats")

        return stats
