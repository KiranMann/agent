"""Session management utilities.

This module provides helper functions for managing
PostgreSQL-backed session storage for agent handlers.
All session persistence and retrieval is handled via the PostgreSQL connection pool.
"""

# pylint: disable=unused-argument,broad-exception-caught

import json
from typing import Any

from psycopg_pool import AsyncConnectionPool

from apps.companion.all_agents.services import guardrails_service
from common.agent_base import AgentSessionContext
from common.base_rest_handler import BaseRestHandler
from common.configs.agent_config_settings import AgentConfig
from common.configs.app_config_settings import AppConfig
from common.logging.core import logger
from common.models.non_conversation_manager_types import SimpleInputPayload

memory_cache: dict[str, AgentSessionContext] = {}  # fallback in-memory session store


def get_handler_session_msgs(handler: BaseRestHandler, payload: SimpleInputPayload) -> list[Any]:
    """Retrieve or initialize the message list for a session.

    in the handler's knowledge store.

    Args:
        handler: The agent handler instance containing the knowledge dictionary.
        payload: The payload object containing a session_id and uid.

    Returns:
        list: The list of messages associated with the session.
    """
    if payload.session_id not in handler.knowledge:
        handler.knowledge[payload.session_id] = {
            "messages": [],
            "uid": payload.uid,
        }
    return handler.knowledge[payload.session_id]["messages"]  # type: ignore[no-any-return]


async def get_db_session(session_id: str, connection_pool: AsyncConnectionPool | None) -> AgentSessionContext | None:
    """Retrieve the session context from the database for a given session ID.

    Falls back to in-memory cache if no connection pool is provided.

    Args:
        session_id (str): The session identifier.
        connection_pool (AsyncConnectionPool | None): The async
            database connection pool.

    Returns:
        AgentSessionContext | None: The session context dictionary for
            the agent SDK, or None if not found or error.
    """
    if connection_pool is None:
        logger.info("No PostgreSQL connection pool provided to get_db_session. Using in-memory fallback.")
        session = memory_cache.get(session_id)
        if session is not None:
            return session
        return None
    try:
        async with connection_pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT session_json FROM agent_sessions WHERE session_id = %s",
                (session_id,),
            )
            row = await cur.fetchone()
            if row is not None and row[0] is not None:
                value = row[0]
                if isinstance(value, dict):
                    return value  # type: ignore[return-value]
                else:
                    return json.loads(value)  # type: ignore[no-any-return]
            else:
                logger.info(f"Session ID {session_id} not found in database.")
                return None
    except Exception as e:
        logger.error(f"Error retrieving session {session_id} from DB: {e}")
        return None


async def put_db_session(
    session_id: str,
    session: AgentSessionContext,
    connection_pool: AsyncConnectionPool | None,
) -> None:
    """Store or update the session context in the database for a given session ID.

    Falls back to in-memory cache if no connection pool is provided.

    Args:
        session_id (str): The session identifier.
        connection_pool (AsyncConnectionPool | None): The async
            database connection pool.
        session (dict): The session context to store.

    Returns:
        None
    """
    if AppConfig.ENABLE_MEMORY_PII_GUARDRAIL:
        try:
            masked_session = await guardrails_service.pii_check(
                user_input=json.dumps(session, default=str),
                parameters=AgentConfig.PII_PARAMETERS,
            )
            masked_output = masked_session.get("masked_output", "")
        except Exception as e:
            logger.error(f"Error applying PII guardrail to personalisation data for sessions {session_id}: {e}")
            masked_output = json.dumps(
                {
                    "current_agent": session.get("current_agent", "unknown"),
                    "resume_point": session.get("resume_point", "unknown"),
                    "agent_context": {},
                }
            )
    else:
        masked_output = json.dumps(session, default=str)  # Fallback to JSON string if no PII check

    if connection_pool is None:
        logger.warning("No PostgreSQL connection pool provided to put_db_session. Using in-memory fallback.")
        memory_cache[session_id] = session
        return
    try:
        async with connection_pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    INSERT INTO agent_sessions (session_id, session_json)
                    VALUES (%s, %s)
                    ON CONFLICT (session_id) DO UPDATE SET session_json = EXCLUDED.session_json
                    """,
                (session_id, masked_output),
            )
            await conn.commit()
    except Exception as e:
        logger.error(f"Error storing session {session_id} to DB: {e}")
