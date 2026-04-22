"""A2A server lifecycle manager that dynamically starts servers from registry."""

import logging
from typing import Any

from psycopg_pool import AsyncConnectionPool

from common.a2a.registry.local_registry import LocalAgentRegistry
from common.a2a.server.a2a_server import A2AServer, start_agent_server_background
from common.configs.agent_config_settings import AgentConfig

logger = logging.getLogger(__name__)


class A2AServerManager:
    """Manages A2A server lifecycle based on agent card registry."""

    def __init__(self, port_start: int = 8001) -> None:
        """Initialize the server manager.

        Args:
            port_start: Starting port for auto-assigning internal A2A servers
        """
        self._port_counter = port_start

    async def start_internal_servers(
        self,
        registry: LocalAgentRegistry,
        agent_pool: Any,
        connection_pool: AsyncConnectionPool[Any],
    ) -> list[A2AServer]:
        """Start A2A servers for all internal agents found in the registry.

        Args:
            registry: LocalAgentRegistry containing agent card definitions
            agent_pool: AgentPool instance with agent instances as attributes
            connection_pool: PostgreSQL connection pool for database operations

        Returns:
            List of successfully started A2A server instances
        """
        servers: list[A2AServer] = []

        for card in registry.get_internal_agent_cards():
            # Look up agent instance from pool by convention: card domain -> pool attribute
            attr_name = card.inferred_pool_attribute()
            agent = getattr(agent_pool, attr_name, None)
            if not agent:
                logger.warning(
                    f"Agent instance not found in pool as '{attr_name}' for card '{card.name}' — skipping A2A server"
                )
                continue

            port = card.port or self._auto_assign_port()
            try:
                server = await start_agent_server_background(
                    card=card,
                    agent=agent,
                    connection_pool=connection_pool,
                    host=AgentConfig.A2A_SERVER_HOST,
                    port=port,
                )
                servers.append(server)
                logger.info(f"Started {card.name} A2A server on port {port}")
            except Exception:
                logger.exception(f"Failed to start {card.name} A2A server")

        return servers

    def _auto_assign_port(self) -> int:
        """Auto-assign the next available port.

        Returns:
            The next port number in sequence
        """
        port = self._port_counter
        self._port_counter += 1
        return port
