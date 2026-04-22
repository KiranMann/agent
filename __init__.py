"""Shared utilities for orchestration and the financial companion agents.

This package contains utilities shared across all layers:
- Conversation management (history loading/saving)
- Session management (context, state)
- Memory management (truncation)

Components:
    - ConversationManager: Handles conversation history and persistence
    - SessionManager: Manages session context and state
    - Constants: Shared constants like AgentType for consistent agent identification

Usage:
    from common import ConversationManager, SessionManager

    conversation_mgr = ConversationManager(connection_pool)
    history = await conversation_mgr.load_history(thread_id)
"""
