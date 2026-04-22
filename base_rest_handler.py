"""This module defines the BaseRestHandler class.

The BaseRestHandler class is responsible for processing incoming requests
and generating responses for the sample agent.
"""

import traceback
from collections.abc import Callable
from typing import Any

from agents import AgentsException
from fastapi.responses import JSONResponse
from openai import OpenAIError

from common.logging.core import logger
from common.models.conversation_manager_types import CMExceptionWithStatus
from common.utils.runtime_utils import write_http_response


class BaseRestHandler:
    """Sample agent handler for processing incoming requests and generating responses."""

    def __init__(self) -> None:
        """Initialize the BaseRestHandler.

        This constructor initializes an empty knowledge base to store
        session-specific data.
        """
        self.knowledge: dict[str, Any] = {}

    @staticmethod
    async def route_io_wrapper(
        authorised: bool, execute_route: Callable[..., Any], route_kwargs: dict[str, Any]
    ) -> JSONResponse:
        """Wrapper function to handle authorisation & error handling on a route.

        Args:
            authorised (bool): Whether user is authorised to call this route.
            execute_route (Callable): Function to call to run the route logic.
            route_kwargs (dict): Arguments to call the
                execute_route function with.

        Returns:
            JSONResponse: Output of the route
        """
        if not authorised:
            return write_http_response(
                status=401,
                content={
                    "detail": "Unauthorised access to agent API",
                },
            )

        try:
            output = await execute_route(**route_kwargs)
            return write_http_response(status=200, content=output)
        except CMExceptionWithStatus as err:
            logger.error("\n======== Conversation handling error ========")
            logger.error(traceback.format_exc())
            return write_http_response(
                status=err.status,
                content={
                    "detail": f"Error handling conversation: {err.detail}",
                },
            )
        except (ValueError, AgentsException, OpenAIError) as err:
            logger.error("\n======== Agent workflow error ========")
            logger.error(traceback.format_exc())
            status_code = int(getattr(err, "status_code", 500))
            return write_http_response(
                status=status_code,
                content={
                    "detail": f"Agent workflow error: {err!s}",
                },
            )
        except Exception as err:
            logger.error("\n======== Unknown error ========")
            logger.error(traceback.format_exc())
            return write_http_response(
                status=500,
                content={"detail": f"Agent returns: {err!s}"},
            )
