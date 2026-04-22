# API Services

This directory houses implementations that enable agents to communicate with external services through gateway + IDP authentication. The services are designed in a flexible way to be consumed by any agent that needs them.

## Available Services

- **CardAddressService**: Interacts with the Card Address Service API for operations such as updating card addresses, managing card delivery settings, and configuring delivery preferences for credit cards.
- **CardDeviceService**: Interacts with the Card Device Service API to retrieve device IDs associated with credit cards and obtain detailed card information based on device IDs. Supports batch processing for efficient API usage.
- **ConversationManagerService**: Interacts with the Conversation Manager API (SpacePort) for handling conversation operations, retrieving messages and conversation details for specific conversations.
- **CreditCardAccountsService**: Interacts with the Credit Card Accounts Service API for operations such as retrieving account IDs from account numbers and obtaining detailed account information.
- **CreditCardService**: Interacts with the Credit Card Service API for operations such as renewing, replacing, and updating credit cards with support for address management and delivery options.
- **CustomerDataService**: Interacts with the Customer Product and Service Directory API to retrieve product information associated with customer party IDs with support for filtering and pagination.
- **GuardrailsService**: Interacts with the Guardrails Service API for comprehensive content validation including PII detection and masking, competitor mention detection, financial advice content detection, security vulnerability detection, profanity detection, harmful content detection, inappropriate language detection, jailbreak attempt detection, and factual accuracy checking.
- **LocationDataService**: Interacts with the Location Data Management API for operations such as verifying addresses and validating address information for domestic Australian addresses.
- **MSOutlookService**: Interacts with Microsoft Graph API for accessing Outlook email services, including retrieving mailbox contents, reading email messages, and handling attachments with optional AWS S3 integration.
- **PartyDataService**: Interacts with the Party Reference Data Directory API to retrieve party IDs from Customer Information File (CIF) IDs.
- **PartySearchService**: Interacts with the Party Reference Data Directory API for comprehensive party search functionality using name, contact details (phone/email), and business identifiers (ABN/ACN) with pagination support.
- **PegaDocumentCaptureService**: Interacts with PEGA's document capture API for document submission and retrieval of document analysis results, supporting document processing workflows such as bankruptcy document analysis.
- **PropertyInsightService**: Interacts with multiple property-related APIs including Location Data Management, Property Data Service (PDaaS), and Property Valuation APIs for comprehensive property insights with address matching, property data retrieval, and automated valuations.

## Architecture

Each service inherits from the `ServiceAPIBase` class, which provides common functionality for making API calls and handling authentication. The services use the Group IDP client for authentication and make asynchronous HTTP requests to their respective APIs.

## Usage

Services are instantiated as singletons at the module level and can be imported directly:

```python
from api_services import credit_card_service

# Use the service
result = await credit_card_service.renew_card(device_id, address, party_id)
```

Or you can create your own instance with custom parameters:

```python
from api_services import CreditCardService

# Create a custom instance
my_service = CreditCardService(name="custom-name", base_url="https://custom-url.example.com")

# Use the custom instance
result = await my_service.renew_card(device_id, address, party_id)
```
