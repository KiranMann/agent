"""Local agent registry for discovering A2A agents from JSON agent card files."""

import asyncio
import json
import logging
from pathlib import Path

import httpx
from a2a.types import AgentCard

from common.a2a.registry.card_definition import AgentCardDefinition

logger = logging.getLogger(__name__)


class LocalAgentRegistry:
    """Registry that discovers A2A agents from local JSON agent card files."""

    def __init__(self) -> None:
        """Initialize the registry with an empty agent cards dictionary."""
        self._agent_cards: dict[str, AgentCard] = {}
        self._agent_card_definitions: dict[str, AgentCardDefinition] = {}

    def _register_card_internal(self, card_definition: AgentCardDefinition) -> None:
        """Register a card definition internally (DRY helper).

        Args:
            card_definition: The agent card definition to register
        """
        agent_card = card_definition.to_transport_card()
        self._agent_cards[agent_card.name] = agent_card
        self._agent_card_definitions[card_definition.name] = card_definition

    def load(self, cards_dir: str, filter_names: set[str] | None = None) -> None:
        """Load all agent cards from the cards directory.

        Reads all *.json files from the top-level cards directory
        (excludes schema/ subdirectory). Parses each into an AgentCard.

        Args:
            cards_dir: Path to directory containing agent card JSON files
            filter_names: Optional set of card names to load. If provided, only
                cards with names in this set are loaded. If None, all cards are loaded.
        """
        cards_path = Path(cards_dir)
        if not cards_path.exists():
            logger.warning(f"Agent cards directory does not exist: {cards_path}")
            return

        # Only look at top-level JSON files, skip schema/ subdirectory
        json_files = [f for f in cards_path.glob("*.json") if f.is_file()]

        loaded_count = 0
        for json_file in json_files:
            try:
                with json_file.open("r", encoding="utf-8") as f:
                    card_data = json.load(f)

                card_definition = AgentCardDefinition.model_validate(card_data)

                # Skip if filtering is enabled and this card is not in the filter set
                if filter_names is not None and card_definition.name not in filter_names:
                    logger.debug(f"Skipping agent card: {card_definition.name} (not in filter set)")
                    continue

                self._register_card_internal(card_definition)
                loaded_count += 1

                logger.debug(f"Loaded agent card: {card_definition.name} from {json_file}")

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON in {json_file}: {e}")
                continue
            except Exception as e:
                logger.warning(f"Failed to load agent card from {json_file}: {e}")
                continue

        logger.info(f"Loaded {loaded_count} agent cards from {cards_path}")

    def get_agent_card(self, agent_name: str) -> AgentCard | None:
        """Get a specific agent's card by name.

        Args:
            agent_name: The name of the agent to retrieve

        Returns:
            The agent card if found, None otherwise
        """
        return self._agent_cards.get(agent_name)

    def get_agent_card_definition(self, agent_name: str) -> AgentCardDefinition | None:
        """Get a specific enriched agent card definition by name.

        Args:
            agent_name: The name of the agent to retrieve

        Returns:
            The enriched agent card definition if found, None otherwise
        """
        return self._agent_card_definitions.get(agent_name)

    def list_all_agents(self) -> list[AgentCard]:
        """List all registered agents.

        Returns:
            List of all registered agent cards
        """
        return list(self._agent_cards.values())

    def list_all_agent_definitions(self) -> list[AgentCardDefinition]:
        """List all enriched agent card definitions.

        Returns:
            List of all enriched local card definitions
        """
        return list(self._agent_card_definitions.values())

    def load_from_url_sync(self, base_url: str, timeout_seconds: int = 10) -> bool:
        """Fetch and register an agent card from a remote agent's well-known endpoint (synchronous).

        ⚠️ DEPRECATED: This method blocks the event loop and should only be used during
        application initialization where async context is not available. Use the async
        `load_from_url()` method instead for all runtime operations.

        Performs a synchronous GET request to ``{base_url}.well-known/agent.json``
        and registers the card if the request succeeds. This follows the A2A
        specification for agent-card discovery.

        Args:
            base_url: Base URL of the remote agent, e.g. ``http://weather-agent:9000/``.
                      A trailing slash is added automatically if absent.
            timeout_seconds: HTTP request timeout in seconds.

        Returns:
            True if the card was successfully fetched and registered, False otherwise.
        """
        if not base_url.endswith("/"):
            base_url = base_url + "/"
        discovery_url = f"{base_url}.well-known/agent.json"

        try:
            response = httpx.get(discovery_url, timeout=timeout_seconds)
            response.raise_for_status()
            card_data = response.json()

            card_definition = AgentCardDefinition.model_validate(card_data)
            self._register_card_internal(card_definition)

            logger.info(f"Fetched agent card '{card_definition.name}' from {discovery_url}")
            return True

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error fetching agent card from {discovery_url}: {e}")
        except Exception as e:
            logger.warning(f"Failed to load agent card from {discovery_url}: {e}")

        return False

    def load_from_urls_sync(self, base_urls: list[str], timeout_seconds: int = 10) -> int:
        """Fetch and register agent cards from multiple remote agents (synchronous).

        ⚠️ DEPRECATED: This method blocks the event loop and should only be used during
        application initialization where async context is not available. Use the async
        `load_from_urls()` method instead for all runtime operations.

        Iterates over ``base_urls`` and calls :meth:`load_from_url_sync` for each.
        Failures for individual URLs are logged and skipped so that one
        unavailable agent does not prevent others from registering.

        Args:
            base_urls: List of base URLs for remote agents.
            timeout_seconds: HTTP request timeout per URL in seconds.

        Returns:
            Number of cards successfully fetched and registered.
        """
        if not base_urls:
            return 0

        success_count = sum(self.load_from_url_sync(url, timeout_seconds=timeout_seconds) for url in base_urls)
        logger.info(f"Fetched {success_count}/{len(base_urls)} remote agent cards from configured URLs.")
        return success_count

    async def load_from_url(self, base_url: str, timeout_seconds: int = 10) -> bool:
        """Fetch and register an agent card from a remote agent's well-known endpoint.

        Performs an asynchronous GET request to ``{base_url}.well-known/agent.json``
        and registers the card if the request succeeds. This follows the A2A
        specification for agent-card discovery.

        Args:
            base_url: Base URL of the remote agent, e.g. ``http://weather-agent:9000/``.
                      A trailing slash is added automatically if absent.
            timeout_seconds: HTTP request timeout in seconds.

        Returns:
            True if the card was successfully fetched and registered, False otherwise.
        """
        if not base_url.endswith("/"):
            base_url = base_url + "/"
        discovery_url = f"{base_url}.well-known/agent.json"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(discovery_url, timeout=timeout_seconds)
                response.raise_for_status()
                card_data = response.json()

            card_definition = AgentCardDefinition.model_validate(card_data)
            self._register_card_internal(card_definition)

            logger.info(f"Fetched agent card '{card_definition.name}' from {discovery_url}")
            return True

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error fetching agent card from {discovery_url}: {e}")
        except Exception as e:
            logger.warning(f"Failed to load agent card from {discovery_url}: {e}")

        return False

    async def load_from_urls(self, base_urls: list[str], timeout_seconds: int = 10) -> int:
        """Fetch and register agent cards from multiple remote agents.

        Iterates over ``base_urls`` and calls :meth:`load_from_url` for each.
        Failures for individual URLs are logged and skipped so that one
        unavailable agent does not prevent others from registering.

        Args:
            base_urls: List of base URLs for remote agents.
            timeout_seconds: HTTP request timeout per URL in seconds.

        Returns:
            Number of cards successfully fetched and registered.
        """
        if not base_urls:
            return 0

        # Use asyncio.gather for concurrent HTTP requests
        tasks = [self.load_from_url(url, timeout_seconds=timeout_seconds) for url in base_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successes (True results, ignoring exceptions)
        success_count = sum(1 for result in results if result is True)

        logger.info(f"Fetched {success_count}/{len(base_urls)} remote agent cards from configured URLs.")
        return success_count

    @property
    def domain_to_agent_type(self) -> dict[str, str]:
        """Auto-generate domain -> AgentType mapping from all registered cards.

        Returns:
            Dictionary mapping agent domain names to AgentType enum values.
            Example: {"products": "ProductsAgent", "weather": "WeatherAgent"}
        """
        return {
            card.inferred_agent_domain(): card.inferred_agent_type() for card in self._agent_card_definitions.values()
        }

    @property
    def agent_name_mapping(self) -> dict[str, str]:
        """Auto-generate AgentType -> agent_name mapping from cards.

        Returns:
            Dictionary mapping AgentType enum values to pool attribute names.
            Example: {"ProductsAgent": "products_agent", "WeatherAgent": "weather_agent"}
        """
        return {
            card.inferred_agent_type(): card.inferred_pool_attribute() for card in self._agent_card_definitions.values()
        }

    @property
    def a2a_eligible_domains(self) -> set[str]:
        """All registered domains are A2A eligible by definition.

        Returns:
            Set of all agent domain names that have registered cards.
        """
        return {card.inferred_agent_domain() for card in self._agent_card_definitions.values()}

    @property
    def card_domain_map(self) -> dict[str, str]:
        """Auto-generate card_name -> domain mapping for IntentClassifier.

        Since domain names are now the canonical identifier and A2A card names
        follow the convention '{domain}-agent', this mapping is trivially derived
        and never needs manual maintenance.

        Returns:
            Dictionary mapping card names to domain names.
            Example: {"products-agent": "products", "weather-agent": "weather"}
        """
        return {card.name: card.inferred_agent_domain() for card in self._agent_card_definitions.values()}

    def get_internal_agent_cards(self) -> list[AgentCardDefinition]:
        """Get cards flagged as internal (need A2A server startup).

        Returns:
            List of agent card definitions where deployment is "internal".
        """
        return [card for card in self._agent_card_definitions.values() if card.deployment == "internal"]

    def get_domain_description(self, domain: str) -> str | None:
        """Get routing description from card for a domain.

        Args:
            domain: The agent domain name to look up.

        Returns:
            The routing short description if the card has routing metadata, None otherwise.
        """
        for card in self._agent_card_definitions.values():
            if card.inferred_agent_domain() == domain and card.routing:
                return card.routing.short_description
        return None

    def register_card(self, card_definition: AgentCardDefinition) -> None:
        """Register an agent card definition programmatically.

        Intended primarily for testing purposes where agent cards need to be
        registered without loading from files or URLs.

        Args:
            card_definition: The agent card definition to register
        """
        self._register_card_internal(card_definition)
        logger.debug(f"Registered agent card: {card_definition.name} programmatically")
