"""This module defines types and enums used for managing conversations.

It includes payload structures, role mappings, message types, and other
utilities for processing conversation data.
"""

# pylint: disable=pointless-string-statement

import datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel


class CMInputPayload(BaseModel):
    """Represents the input payload for a conversation manager.

    Attributes:
        agent_name (Optional[str]): The name of the agent.
        conversation_id (str): The ID of the conversation.
        message_id (str): The ID of the message.
    """

    conversation_id: str
    message_id: str


"""
Represents the possible actions in a conversation.

Attributes:
    EJECT (str): Eject the conversation.
    TRANSFER (str): Transfer the conversation.
    CLOSE (str): Close the conversation.
    OPEN (str): Open the conversation.
    COMPLETE (str): Happy path of conversation completed.
"""
ActionsEnum = Literal["EJECT", "TRANSFER", "CLOSE", "OPEN", "COMPLETE"]


"""
Represents the roles in a conversation.

Attributes:
    CUSTOMER (str): The customer role.
    STAFF (str): The staff role.
    REVIEWER (str): The reviewer role.
    EXPERT_AI (str): The expert AI role.
"""
RoleType = Literal["Customer", "Staff", "Reviewer", "ExpertAI"]


# Mapping from CM participant "roles" to AI-compatible "types"
mapping_roles: dict[str, RoleType] = {
    "customer": "Customer",
    "ai": "ExpertAI",
    "staff": "Staff",
    "staff-reviewer": "Reviewer",
}


MessageMetadata = TypedDict("MessageMetadata", {"for": str | None, "type": str | None})


class Message(TypedDict):
    """Represents a message in a conversation.

    Attributes:
        content (str): The content of the message.
        type (str): The type of the message.
        recipientId (str): The ID of the recipient.
        senderId (str): The ID of the sender.
        createdAt (str): The creation timestamp of the message.
        metadata (MessageMetadata | None): Metadata associated with the message.
        extras (dict): Additional information about the message.
    """

    # pylint: disable=invalid-name
    content: str
    type: str
    recipientId: str
    senderId: str
    createdAt: str
    metadata: MessageMetadata | None
    extras: dict[str, Any]


class ResponseMessage(TypedDict):
    """Represents a response message in a conversation.

    Attributes:
        recipient (RoleType): The recipient of the message.
        content (str): The content of the message.
        metadata (MessageMetadata | None): Metadata associated with the message.
    """

    recipient: RoleType
    content: str
    metadata: MessageMetadata | None


class ExternalLinks(TypedDict):
    """Represents external links associated with a participant.

    Attributes:
        externalId (str | None): The external ID.
        externalType (str | None): The type of the external link.
    """

    # pylint: disable=invalid-name
    externalId: str | None
    externalType: str | None


class LatestMessage(TypedDict, total=False):
    """Represents the latest message in a conversation.

    Attributes:
        id (str): The ID of the message.
        content (str): The content of the message.
        type (str): The type of the message (e.g., "interactive").
        senderId (str): The ID of the sender.
        recipientId (str): The ID of the recipient.
        metadata (str): Metadata associated with the message.
        extras (str): Additional extras for the message.
        createdAt (str): The creation timestamp of the message.
        linkedMessageId (str): The ID of the linked message, if any.
    """

    # pylint: disable=invalid-name
    id: str
    content: str
    type: str
    senderId: str
    recipientId: str
    metadata: str
    extras: str
    createdAt: str
    linkedMessageId: str


class ConversationParticipant(TypedDict, total=False):
    """Represents a participant in a conversation response.

    Attributes:
        id (str): The ID of the participant.
        displayName (str): The display name of the participant.
        role (str): The role of the participant.
        joinedAt (str): The timestamp when the participant joined.
        permission (str): The permissions of the participant.
        externalLinks (list[ExternalLinks]): External links associated with the participant.
    """

    # pylint: disable=invalid-name
    id: str
    displayName: str
    role: str
    joinedAt: str
    permission: str
    externalLinks: list[ExternalLinks]


class Conversation(TypedDict, total=False):
    """Represents a conversation in the response.

    Attributes:
        id (str): The ID of the conversation.
        externalLinks (list[ExternalLinks]): External links associated with the conversation.
        status (str): The status of the conversation (e.g., "opened").
        createdAt (str): The creation timestamp of the conversation.
        lastMessageAt (str): The timestamp of the last message.
        latestIntent (str): The latest intent of the conversation.
        participants (list[ConversationParticipant]): The participants in the conversation.
        latestMessage (LatestMessage): The latest message in the conversation.
    """

    # pylint: disable=invalid-name
    id: str
    externalLinks: list[ExternalLinks]
    status: str
    createdAt: str
    lastMessageAt: str
    latestIntent: str
    participants: list[ConversationParticipant]
    latestMessage: LatestMessage


class GetConversationsResponse(TypedDict, total=False):
    """Represents the response from the get_conversations API call.

    Attributes:
        conversations (list[Conversation]): The list of conversations.
        count (int): The total count of conversations.
        nextCursor (str): The cursor for pagination to get the next set of results.
    """

    # pylint: disable=invalid-name
    conversations: list[Conversation]
    count: int
    nextCursor: str


class Participant(TypedDict):
    """Represents a participant in a conversation.

    Attributes:
        id (str): The ID of the participant.
        external_links (list[ExternalLinks] | None): External links associated
            with the participant.
        display_name (str): The display name of the participant.
        role (RoleType): The role of the participant.
        joined_at (datetime.datetime): The timestamp when
            the participant joined.
        permission (str | None): The permissions of the participant.
    """

    # pylint: disable=invalid-name
    id: str | None
    externalLinks: list[ExternalLinks] | None
    displayName: str | None
    role: RoleType | None
    joinedAt: datetime.datetime | None
    permission: str | None
    # pylint: enable=invalid-name


class UniqueParticipants(TypedDict):
    """Represents a dictionary of unique participants.

    Attributes:
        id (Participant): The participant associated with the ID.
    """

    __root__: dict[str, list[Participant]]  # where str is the participant ID


class TransformedParticipant(Participant):
    """Represents a transformed participant with additional attributes.

    Attributes:
        type (str | None): The type of the participant.
        external_links (dict): External links reformatted as a dictionary.
    """

    type: str | None
    transformed_external_links: dict[
        Literal["netbank-id", "cif-code"] | str,
        str,
    ]


class ParticipantsByRole(TypedDict):
    """Represents participants grouped by their roles.

    Attributes:
        __root__ (dict[str, List[TransformedParticipant]]):
            A dictionary where the key is the role type.
    """

    __root__: dict[str, list[TransformedParticipant]]


class AgenticInputs(TypedDict):
    """Represents inputs for an agent.

    Attributes:
        user_query (str): The user's query.
        message_history (list[Any]): The history of messages in the conversation.
    """

    user_query: str
    message_history: list[Any]


class HandleResponse(TypedDict):
    """Represents the response from an agent.

    Attributes:
        instruction (dict[Literal["action"], ActionsEnum]): The action to be performed.
        messages (List[Message]): The messages to be sent.
    """

    instruction: dict[Literal["action"], ActionsEnum]
    messages: list[Message]


class PrepareConversationData(TypedDict):
    """Represents prepared conversation data for an agent.

    Attributes:
        correlation_id (str): The correlation ID for the conversation.
        agentic_inputs (AgenticInputs): The inputs for the agent.
        participants_by_role (ParticipantsByRole): The participants grouped by
            their roles.
    """

    correlation_id: str
    agentic_inputs: AgenticInputs
    participants_by_role: ParticipantsByRole


class CMExceptionWithStatus(Exception):  # noqa: N818
    """Custom exception class for handling errors during interaction with CM.

    Contains the HTTP status code and detail for returning to the user.
    Will be handled in handlers.
    """

    def __init__(self, status: int, detail: str) -> None:
        """Initialize the exception with status and detail."""
        self.status = status
        self.detail = detail
        super().__init__(f"{status} error: {detail}")
