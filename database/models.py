"""SQLAlchemy models for the Financial Companion database.

This module contains all the SQLAlchemy ORM models used throughout the application.
Models are organized by domain and follow consistent naming and structure patterns.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from common.database.sqlalchemy_setup import Base


class ConversationMessage(Base):
    """SQLAlchemy model for conversation_messages table.

    This model represents individual messages within customer conversations,
    including user messages, assistant responses, and system messages.
    """

    __tablename__ = "conversation_messages"

    # Primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Core message fields
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    customer_id: Mapped[str | None] = mapped_column(String(255), index=True)
    role: Mapped[str | None] = mapped_column(String(20))
    content: Mapped[str | None] = mapped_column(Text)

    # JSON field for UI components
    ui_components: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    # JSON field for sources (RAG references, knowledge base citations, etc.)
    sources: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    # JSON field for guardrail audit trail (list of triggered guardrail types)
    guardrails_triggered: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        index=True,
    )

    # Message identification
    message_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Optional feedback
    feedback_score: Mapped[int | None] = mapped_column(Integer)

    # Tool call support fields
    item_type: Mapped[str] = mapped_column(String(50), nullable=False, default="message")
    call_id: Mapped[str | None] = mapped_column(String(255))
    function_name: Mapped[str | None] = mapped_column(String(255))
    function_arguments: Mapped[str | None] = mapped_column(Text)
    function_output: Mapped[str | None] = mapped_column(Text)

    # Table constraints
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system') OR item_type IN ('function_call', 'function_call_output')",
            name="chk_conversation_messages_role_or_type",
        ),
        CheckConstraint(
            "item_type IN ('message', 'function_call', 'function_call_output')",
            name="chk_conversation_messages_item_type",
        ),
        CheckConstraint(
            "(item_type = 'message') = (role IN ('user', 'assistant', 'system') AND content IS NOT NULL AND call_id IS NULL AND function_name IS NULL AND function_arguments IS NULL AND function_output IS NULL)",
            name="chk_conversation_messages_message_type",
        ),
        CheckConstraint(
            "(item_type = 'function_call') = (call_id IS NOT NULL AND function_name IS NOT NULL AND role IS NULL AND content IS NULL AND function_output IS NULL)",
            name="chk_conversation_messages_function_call_type",
        ),
        CheckConstraint(
            "(item_type = 'function_call_output') = (call_id IS NOT NULL AND role IS NULL AND content IS NULL AND function_name IS NULL AND function_arguments IS NULL)",
            name="chk_conversation_messages_function_output_type",
        ),
        CheckConstraint("feedback_score BETWEEN 0 AND 1", name="check_feedback_score"),
        Index("idx_conversation_messages_session_id", "session_id"),
        Index("idx_conversation_messages_customer_id", "customer_id"),
        Index("idx_conversation_messages_created_at", "created_at"),
        # Composite indexes for common query patterns
        Index("idx_conversation_messages_customer_created", "customer_id", "created_at"),
        Index("idx_conversation_messages_session_created", "session_id", "created_at"),
        # Unique index for messages only
        Index(
            "idx_conversation_messages_msg_unique",
            "session_id",
            "message_id",
            unique=True,
            postgresql_where="item_type = 'message'",
        ),
    )

    def __repr__(self) -> str:
        """String representation of the conversation message."""
        return (
            f"<ConversationMessage(id={self.id}, session_id='{self.session_id}', "
            f"role='{self.role}', created_at='{self.created_at}')>"
        )

    @property
    def content_preview(self) -> str:
        """Get a truncated preview of the message content."""
        if self.content is None:
            return ""
        max_preview_length = 100
        truncated_length = 97
        if len(self.content) <= max_preview_length:
            return str(self.content)
        return str(self.content[:truncated_length]) + "..."

    def to_dict(self) -> dict[str, Any]:
        """Convert the model instance to a dictionary."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "customer_id": self.customer_id,
            "role": self.role,
            "content": self.content,
            "ui_components": self.ui_components,
            "sources": self.sources,
            "guardrails_triggered": self.guardrails_triggered,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "message_id": self.message_id,
            "feedback_score": self.feedback_score,
            "item_type": self.item_type,
            "call_id": self.call_id,
            "function_name": self.function_name,
            "function_arguments": self.function_arguments,
            "function_output": self.function_output,
        }


class Conversation(Base):
    """SQLAlchemy model for conversations table.

    This model represents conversation metadata including state, customer association,
    and conversation-level flags for managing conversation lifecycles.
    """

    __tablename__ = "conversations"

    # Primary key
    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    # Core conversation fields
    customer_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    conversation_state: Mapped[str] = mapped_column(String(20), nullable=False, default="open")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Table constraints and indexes
    __table_args__ = (
        Index("idx_conversations_customer_id", "customer_id"),
        Index("idx_conversations_deleted", "deleted"),
        Index("idx_conversations_pinned", "pinned"),
        Index("idx_conversations_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        """String representation of the conversation."""
        return (
            f"<Conversation(session_id='{self.session_id}', customer_id='{self.customer_id}', "
            f"state='{self.conversation_state}', created_at='{self.created_at}')>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the model instance to a dictionary."""
        return {
            "session_id": self.session_id,
            "customer_id": self.customer_id,
            "pinned": self.pinned,
            "deleted": self.deleted,
            "conversation_state": self.conversation_state,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def is_closed(self) -> bool:
        """Check if the conversation is closed."""
        return bool(self.conversation_state == "closed")

    @property
    def is_open(self) -> bool:
        """Check if the conversation is open."""
        return bool(self.conversation_state == "open")


class CustomerPersonas(Base):
    """SQLAlchemy model for customer_personas table.

    This model represents customer personalisation data including persona summaries
    and related metadata for improving customer interactions.
    """

    __tablename__ = "customer_personas"

    # Primary key - customer_id is the primary key, not an auto-increment id
    customer_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    # Netbank ID for LaunchDarkly feature flag targeting
    netbank_id: Mapped[str | None] = mapped_column(String(255))

    # Personalisation data stored as JSONB
    personalisation_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Version tracking
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Table constraints and indexes
    __table_args__ = (
        Index("idx_customer_personas_customer_id", "customer_id"),
        Index("idx_customer_personas_netbank_id", "netbank_id"),
    )

    def __repr__(self) -> str:
        """String representation of the customer persona."""
        return (
            f"<CustomerPersonas(customer_id='{self.customer_id}', "
            f"version={self.version_number}, updated_at='{self.updated_at}')>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the model instance to a dictionary."""
        return {
            "customer_id": self.customer_id,
            "personalisation_data": self.personalisation_data,
            "version_number": self.version_number,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def persona_summary(self) -> str:
        """Get the persona summary from personalisation data."""
        summary = self.personalisation_data.get("persona_summary", "")
        return str(summary) if summary is not None else ""


class SubAgentContext(Base):
    """SQLAlchemy model for sub_agent_contexts table.

    This model stores sub-agent tool contexts (e.g., PaymentToolContext) to enable
    state persistence across API requests and conversation turns.
    """

    __tablename__ = "sub_agent_contexts"

    # Primary key - session_id is the primary key
    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    # Customer association
    customer_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Sub-agent contexts stored as JSONB
    # Structure: {"agent_name": {context_data}, ...}
    contexts_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        index=True,
    )

    # Table constraints and indexes
    __table_args__ = (
        Index("idx_sub_agent_contexts_customer_id", "customer_id"),
        Index("idx_sub_agent_contexts_updated_at", "updated_at"),
    )

    def __repr__(self) -> str:
        """String representation of the sub-agent context."""
        return (
            f"<SubAgentContext(session_id='{self.session_id}', "
            f"customer_id='{self.customer_id}', updated_at='{self.updated_at}')>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the model instance to a dictionary."""
        return {
            "session_id": self.session_id,
            "customer_id": self.customer_id,
            "contexts_json": self.contexts_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def get_agent_context(self, agent_name: str) -> dict[str, Any] | None:
        """Get the context for a specific agent."""
        if self.contexts_json and agent_name in self.contexts_json:
            context = self.contexts_json[agent_name]
            return dict(context) if isinstance(context, dict) else None
        return None

    @property
    def agent_names(self) -> list[str]:
        """Get list of agent names that have stored contexts."""
        if self.contexts_json:
            return list(self.contexts_json.keys())
        return []


class Feedback(Base):
    """SQLAlchemy model for feedback table.

    This model represents user feedback with support for both inline (message-specific)
    and global (customer-level) feedback. Uses a flattened structure with one row per answer.
    """

    __tablename__ = "feedback"

    # Primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Group ID to link related feedback answers submitted together
    feedback_group_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Feedback type determines which contextual columns are populated
    feedback_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Core identification fields
    customer_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(255), index=True)
    conversation_message_id: Mapped[str | None] = mapped_column(String(255), index=True)

    # Sentiment for inline feedback (thumbs up/down)
    sentiment: Mapped[str | None] = mapped_column(String(20), index=True)

    # Question details
    question_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_options: Mapped[list[str] | None] = mapped_column(JSONB)

    # Answer columns - only one should be populated based on question_type
    answer_multiselect: Mapped[list[str] | None] = mapped_column(JSONB)
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_rating: Mapped[int | None] = mapped_column(Integer)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Table constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "feedback_type IN ('inline', 'global')",
            name="chk_feedback_type",
        ),
        CheckConstraint(
            "sentiment IN ('like', 'dislike') OR sentiment IS NULL",
            name="chk_feedback_sentiment",
        ),
        CheckConstraint(
            "question_type IN ('text', 'nps', 'rating', 'multiselect')",
            name="chk_feedback_question_type",
        ),
        CheckConstraint(
            "(feedback_type = 'inline') = (conversation_message_id IS NOT NULL)",
            name="chk_feedback_inline_requirements",
        ),
        CheckConstraint(
            "(feedback_type = 'global') = (conversation_message_id IS NULL AND sentiment IS NULL)",
            name="chk_feedback_global_requirements",
        ),
        CheckConstraint(
            """
            (question_type = 'text' AND answer_text IS NOT NULL AND answer_rating IS NULL AND answer_multiselect IS NULL) OR
            (question_type IN ('nps', 'rating') AND answer_rating IS NOT NULL AND answer_text IS NULL AND answer_multiselect IS NULL) OR
            (question_type = 'multiselect' AND answer_multiselect IS NOT NULL AND answer_text IS NULL AND answer_rating IS NULL)
            """,
            name="chk_feedback_answer_type",
        ),
        Index("idx_feedback_group_id", "feedback_group_id"),
        Index("idx_feedback_customer_id", "customer_id"),
        Index("idx_feedback_session_id", "session_id"),
        Index("idx_feedback_conversation_message_id", "conversation_message_id"),
        Index("idx_feedback_type", "feedback_type"),
        Index("idx_feedback_sentiment", "sentiment"),
        Index("idx_feedback_question_type", "question_type"),
        Index("idx_feedback_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        """String representation of the feedback."""
        return (
            f"<Feedback(id={self.id}, feedback_group_id='{self.feedback_group_id}', "
            f"feedback_type='{self.feedback_type}', customer_id='{self.customer_id}', "
            f"question_type='{self.question_type}', created_at='{self.created_at}')>"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the model instance to a dictionary."""
        return {
            "id": self.id,
            "feedback_group_id": self.feedback_group_id,
            "feedback_type": self.feedback_type,
            "customer_id": self.customer_id,
            "session_id": self.session_id,
            "conversation_message_id": self.conversation_message_id,
            "sentiment": self.sentiment,
            "question_type": self.question_type,
            "question": self.question,
            "question_options": self.question_options,
            "answer_multiselect": self.answer_multiselect,
            "answer_text": self.answer_text,
            "answer_rating": self.answer_rating,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def is_inline(self) -> bool:
        """Check if this is inline (message-specific) feedback."""
        return bool(self.feedback_type == "inline")

    @property
    def is_global(self) -> bool:
        """Check if this is global (customer-level) feedback."""
        return bool(self.feedback_type == "global")

    @property
    def answer_value(self) -> str | int | list[str] | None:
        """Get the answer value regardless of type."""
        if self.answer_text is not None:
            return str(self.answer_text)
        if self.answer_rating is not None:
            return int(self.answer_rating)
        if self.answer_multiselect is not None:
            # Type cast needed for JSONB field to satisfy mypy strict checking
            return list(self.answer_multiselect)
        return None

    @property
    def question_preview(self) -> str:
        """Get a truncated preview of the question."""
        max_preview_length = 100
        truncated_length = 97
        if len(self.question) <= max_preview_length:
            return str(self.question)
        return str(self.question[:truncated_length]) + "..."
