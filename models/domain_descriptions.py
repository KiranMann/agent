"""Domain descriptions for intent classification.

Domain descriptions drive both the LLM prompt guidance and the structured-output
schema used by the intent classifier. Functions in this module accept an optional
`enabled_agents` set so that disabled agents are excluded from both.
"""

from pydantic import BaseModel


class DomainDescription(BaseModel):
    name: str
    description: str
    keywords: list[str]
    example_queries: list[str]
    negative_examples: list[str]


HOMEBUYING_ROLE_DESCRIPTION = """Handle home loan and property purchase related requests across the entire homebuying journey. This agent focuses on home loan PRODUCTS and NEW applications, NOT existing home loan account management.

Core Functions:

1. BORROWING POWER AND SERVICEABILITY
   - Calculate borrowing capacity based on income, expenses, dependants, and existing debts
   - Assess impact of credit cards, personal loans, HECS/HELP debt, and other liabilities
   - Compare borrowing power for single vs joint applications
   - Model borrowing capacity across different loan types and LVR scenarios
   - Answer "how much can I borrow?" questions in ANY variation

2. LOAN REPAYMENT CALCULATIONS
   - Calculate monthly/weekly/fortnightly repayments for given loan amounts
   - Estimate repayments across different loan terms (15/20/25/30 years)
   - Compare Principal and Interest (P&I) vs Interest-Only (IO) repayments
   - Model impact of extra repayments on interest savings
   - Scenario modelling (e.g., "what if rates rise by 1%?")
   - Calculate repayments for specific CBA home loan products

3. PROPERTY VALUATIONS AND INSIGHTS
   - Provide property valuations for specific addresses
   - Compare values between multiple properties
   - Match location data for given addresses
   - Property details and comparisons

4. UPFRONT COSTS AND DEPOSIT PLANNING
   - Calculate stamp duty (including state-specific exemptions)
   - Estimate conveyancing and legal fees
   - Calculate Lenders Mortgage Insurance (LMI) costs
   - Provide total upfront cost breakdowns
   - Determine deposit requirements (including minimum deposits)
   - Create deposit savings strategies and timelines
   - Explain what LMI is and how to avoid it

5. GOVERNMENT GRANTS AND SCHEMES
   - Provide information on First Home Guarantee (5% deposit scheme)
   - Explain state-specific grants and eligibility criteria
   - Detail First Home Super Saver Scheme
   - Information on professional schemes (e.g., medical professionals)
   - Assess eligibility and benefits for first home buyers
   - Clarify that investment properties typically don't qualify for grants

6. HOME LOAN PRODUCT INFORMATION
   - Explain features of ALL CBA home loan products:
     * Simple Home Loan
     * Digi Home Loan
     * Standard Variable Rate (SVR) loans (with/without package)
     * Fixed Rate loans (1/2/3/5 year terms, with/without package)
   - Provide current interest rates and comparison rates
   - Compare different loan products and recommend suitable options
   - Explain offset accounts, redraw facilities, and product features
   - Clarify loan types: owner-occupied vs investment, P&I vs IO
   - Answer questions about specific product eligibility and features
   - Educate customers about discontinued products, by letting them know that these have been discontinued:
     * Viridian Line of Credit
     * Green Home Loans
     * Extra Home Loan
     * "Economiser/Rate Saver"
     * "No Fee Variable Rate/Interest Only"
     * "Extra Variable Rate"
     * "Extra Variable Interest Only Rate"
     * "Viridian Line of Credit (VLOC)"
     * "Equity Unlock Loan for Seniors"

7. APPLICATION PROCESS AND LENDER SUPPORT
   - Guide users through home loan application process
   - Explain pre-approval and conditional approval processes
   - Direct users to online application forms
   - Help book appointments with home loan specialists/lenders
   - Explain required documentation and paperwork
   - Provide application status information
   - Connect users with human lenders when requested

8. REFINANCING
   - Explain refinancing process to CBA
   - Calculate potential savings from refinancing
   - Compare current loan vs refinanced loan scenarios
   - Guide users through refinancing application

9. EQUITY AND PROPERTY PURCHASE PLANNING
    - Calculate available equity in existing properties for new purchases
    - Explain how to use equity for future property purchases
    - Model scenarios for using equity as deposit for additional properties

10. COMPLEX SCENARIOS AND STRATEGIC ADVICE
    - Explain guarantor arrangements and requirements
    - Advise on whether to pay off debts vs save for deposit
    - Model impact of closing credit cards on borrowing power
    - Compare scenarios (e.g., buying vs renting, renovation costs)
    - Address employment-specific questions (casual workers, non-citizens, age)
    - Explain eligibility criteria for different borrower types

11. HOMEBUYING EDUCATION AND TERMINOLOGY
    - Explain key concepts: LVR (Loan to Value Ratio), LMI, LDP, pre-approval
    - Define stamp duty, conveyancing, comparison rates
    - Guide users through the overall homebuying process
    - Clarify loan terminology and acronyms

CRITICAL ROUTING RULES:

ALWAYS ROUTE TO HOMEBUYING AGENT - EVEN IF QUERY NEEDS CLARIFICATION:
- ANY question containing: "borrow", "borrowing power", "home loan", "mortgage", "property", "house", "home"
- ANY question about property addresses or valuations
- ANY questions about property affordability or purchasing power.
- ANY repayment calculation questions
- ANY question about deposits, stamp duty, LMI, upfront costs
- ANY question about government grants, schemes, or first home buyer benefits
- ANY question about home loan products (Simple, Extra, Digi, SVR, Fixed Rate)
- ANY question about home loan interest rates or comparison rates
- ANY question about applying for a home loan or speaking to a lender
- ANY question about refinancing TO CBA
- ANY question about guarantors in the context of home loans
- ANY question about using equity for new property purchases
- ANY question about investment property loans
- UNCLEAR queries that mention homebuying, home purchasing, or property-related terms
- VAGUE queries about loans when context suggests property/housing

DO NOT ROUTE TO HOMEBUYING AGENT:
- Existing (not hypothetical) home loan account details (balances, rates, repayments, redraw facilities, arrears status) - route to Products agent.

HOMEBUYING AGENT HANDLES OWN CLARIFICATIONS:
This agent can handle unclear, incomplete, or confusing queries within the homebuying domain. Route here even if the query needs clarification, as long as there are ANY indicators of property, housing, borrowing, or mortgage-related intent.

This agent handles the home loan journey from initial research through to application and refinancing, covering both prospective home buyers and existing customers exploring new purchases."""

homebuying_description = DomainDescription(
    name="homebuying",
    description=HOMEBUYING_ROLE_DESCRIPTION,
    keywords=[],
    example_queries=[],
    negative_examples=[],
)

PRODUCTS_ROLE_DESCRIPTION = """A sub-agent that can answer questions about CommBank products, as well as customer personal/consumer and home loan account repayment details.

    This agent has access to data pertaining to:
    - General information about CommBank products (features, fees, rates, eligibility, conditions, etc.) - EXCLUDING ALL home loan products
    - Detailed customer-specific information for:
        • Customer's existing home loan / mortgage accounts (balances, rates, repayments, etc.)
        • Personal loans / Consumer loans
        (includes personalised pricing, balances, interest rates, repayment amounts, repayment schedule, loan term, redraw details, and any customer-specific fees).

    ----------------------------------------------------------------------
    CORE CAPABILITIES
    ----------------------------------------------------------------------
        - Explain any CommBank product EXCEPT home loan products (credit cards, savings accounts, personal loans, term deposits, travel cards etc.)
        - Compare multiple products within a single call (In this case, the full comparison must be handled in one call)
        - Retrieve and explain customer-specific details for personal/consumer loans, and existing home loan accounts

    Note: If the user asks about multiple personal loans, all loan details must be handled within a single call to handle_products_request.

    ----------------------------------------------------------------------
    WHEN TO ROUTE HERE - EVEN IF QUERY NEEDS CLARIFICATION
    ----------------------------------------------------------------------
    Route to this sub-agent when the user asks about:
    - Any CommBank product EXCEPT home loan products - including information about features, fees, interest rates, eligibility, and terms or conditions (e.g., credit cards, savings accounts, personal loans, term deposits, travel cards)
    - This includes **BLOCKED PRODUCT CATEGORIES** such as insurance, SMSF, superannuation, business banking, institutional services
    - Comparing 2 or more non-home-loan products
    - Their OWN/MY personal/consumer, or existing home loan account details
    - UNCLEAR queries mentioning "card", "loan" (non-home), "account" (product features), "rate", "fee", "application"
    - VAGUE product inquiries that can be reasonably inferred as banking product related

    PRODUCTS AGENT HANDLES OWN CLARIFICATIONS:
    This agent can handle unclear, incomplete, or confusing queries within the banking products domain. Route here even if the query needs clarification, as long as there are ANY indicators of banking product intent (excluding home loans).

    DO NOT route here for:
    - ANY question about borrowing for a property or house
    - Generic home loan product queries (features, eligibility, applications)
    - Home loan calculations, borrowing power, or property valuations
    - Route home loan PRODUCT and BORROWING questions to homebuying agent instead

    DO route here for:
    - Customer's existing home loan account details (balances, rates, repayments, account-specific information)

    DO NOT route here for money management questions:
    - Account balances and transaction queries (route to Savings agent)
    - Spending analysis and budgeting (route to Savings agent)
    - Affordability questions based on spending patterns (route to Savings agent) - e.g., "Can I afford a new fridge?" or "Can I afford a car?"
    - Bill and subscription management (route to Savings agent)
    - Debt payoff strategies based on spending analysis (route to Savings agent)
    - Savings goals tracking and progress (route to Savings agent)
    - "What-if" financial simulations (route to Savings agent)

    ----------------------------------------------------------------------
    MULTI-INTENT HANDLING
    ----------------------------------------------------------------------
    If the user has multiple intents, the `request` argument must only contain the product-related part. This tool should process only that part."""

products_description = DomainDescription(
    name="products",
    description=PRODUCTS_ROLE_DESCRIPTION,
    keywords=[],
    example_queries=[],
    negative_examples=[],
)

SAVINGS_ROLE_DESCRIPTION = """A money management agent that helps customers understand their spending, manage budgets, track savings, and plan for financial goals.

CORE CAPABILITIES:

1. TRANSACTION ANALYSIS AND SPENDING INSIGHTS
   - Query and filter transactions by amount, date, merchant, category, or description
   - Analyse spending patterns across categories (groceries, entertainment, transport, etc.)
   - Identify spending trends, unusual cycles, and anomalies
   - Provide spending summaries with historical comparisons
   - Answer "where has my money gone?" type questions

2. FINANCIAL OVERVIEW AND POSITION
   - Provide financial position summaries for planning purposes
   - Track money flow for budgeting and savings analysis

3. AFFORDABILITY AND FINANCIAL PLANNING
   - Assess whether customers can afford purchases (e.g., "Can I afford a new fridge?", "Can I afford a car?")
   - Analyse spending patterns to determine affordability
   - Run "what-if" simulations to model spending changes and savings impact
   - Calculate how long it would take to save for specific goals based on current spending patterns

4. DEBT MANAGEMENT STRATEGIES
   - Help customers understand how to pay off credit card debt
   - Analyse spending to identify savings opportunities for debt repayment
   - Create debt payoff plans based on transaction history and spending behavior

5. BILLS AND SUBSCRIPTIONS MANAGEMENT
   - Retrieve and display all customer bills and subscriptions (including predicted, manual, home loans, personal loans)
   - Set up automatic bill payments and recurring payments
   - Add, edit, and delete manual bills
   - Confirm predicted bills
   - Help customers understand and manage their bill timeline
   - Identify bills that can be modified or cancelled to save money

6. CATEGORY BUDGETS
   - Show how customers are tracking against budget limits for each spending category
   - Update and manage category budget limits
   - Retrieve budget cycle settings (weekly, fortnightly, monthly)
   - Display current cycle spending summaries
   - Get historical spend data for specific categories
   - Show category-specific transactions

7. SAVINGS GOALS TRACKING
   - Retrieve and display customer's Savings Goals (a specific CommBank product)
   - Show progress toward savings goals with timelines and completion percentages
   - Calculate savings timelines for goals (e.g., "How long to save for a home deposit?")
   - Track goal history and performance
   - Help customers create savings strategies to reach their goals
   - IMPORTANT: The agent cannot create savings goals - do not ask it to guide a user through this process. When producing the `request` field just ask "Guide me through creating a savings goal" with no extra information.

8. SCENARIO MODELING AND SIMULATIONS
   - Run financial simulations to answer "what-if" questions
   - Model the impact of spending changes (e.g., "What if I reduce dining out by 20%?")
   - Inject hypothetical transactions to forecast savings
   - Remove or modify spending categories to see potential savings
   - Compare multiple scenarios side-by-side
   - Forecast savings over time based on behavioral changes

10. SAVINGS PERFORMANCE ANALYSIS
    - Analyse historical savings behavior and performance
    - Compare current savings rate to historical averages
    - Show savings trends over time (daily, weekly, monthly)
    - Calculate average savings per cycle
    - Identify periods of strong or weak savings performance

WHEN TO ROUTE TO SAVINGS AGENT - EVEN IF QUERY NEEDS CLARIFICATION:

Route here for ANY questions about:
- Transaction queries and spending analysis ("Where did I spend?", "Show my transactions")
- Spending patterns and insights ("What do I spend on?", "My biggest expenses")
- Affordability questions ("Can I afford X?", "How much can I spend on Y?")
- Savings strategies and timelines ("How long to save $X?", "Help me save for Z")
- Debt payoff planning ("How can I pay off my credit card debt?")
- Bills and subscriptions ("Show my bills", "Set up automatic payments", "Cancel my subscription")
- Budget tracking ("Am I over budget?", "Show my budget", "Update my grocery budget")
- Savings goals ("Show my goals", "How am I tracking?", "Savings goal progress")
- Financial simulations ("What if I reduce spending?", "Model different scenarios")
- Money management questions ("Help me understand my finances", "Where has my money gone?")
- UNCLEAR queries mentioning "money", "savings", "spend", "save", "budget", "balance", "transaction", "bill"
- VAGUE financial management questions that can be reasonably inferred as money-related

SAVINGS AGENT HANDLES OWN CLARIFICATIONS:
This agent can handle unclear, incomplete, or confusing queries within the money management domain. Route here even if the query needs clarification, as long as there are ANY indicators of spending, saving, budgeting, or financial management intent.

DO NOT ROUTE HERE FOR:

- Questions about CommBank PRODUCT features, rates, and eligibility (route to Products agent)
  * Exception: Questions about using existing savings accounts for money management ARE for Savings agent
- Questions about applying for new products like credit cards, personal loans, or opening new savings accounts (route to Products agent)
- Home loan calculations, borrowing power, LVR, or property-related questions (route to Homebuying agent)
  * Exception: "How long to save for a home deposit?" should route to BOTH Savings AND Homebuying agents
- Questions about specific account transactions for HOME LOANS or PERSONAL LOANS (route to Products agent for personal loans, Homebuying for home loans)

IMPORTANT DISTINCTIONS:

- Savings account MANAGEMENT (balances, transactions, budgeting) → Savings agent
- Savings account PRODUCT INFO (rates, features, eligibility) → Products agent
- "Can I afford X?" based on spending analysis → Savings agent
- "Am I eligible for X product?" → Products agent
- "How long to save for a home deposit?" → BOTH Savings AND Homebuying agents
- Bill payment SETUP and MANAGEMENT → Savings agent
- Insurance product modifications → Products agent (unless it's about bill payment management)"""

savings_description = DomainDescription(
    name="savings",
    description=SAVINGS_ROLE_DESCRIPTION,
    keywords=[],
    example_queries=[],
    negative_examples=[],
)

GENERAL_QUERIES_ROLE_DESCRIPTION = """A sub-agent that handles greetings, domain-unclear queries, routing clarifications, basic account information requests, and action-oriented self-service banking tasks when the intent classifier cannot determine which domain should handle the request.

CORE CAPABILITIES:

1. GREETING DETECTION AND RESPONSE
   - Detect various greeting patterns (hi, hello, good morning, hey, etc.)
   - Provide warm, personalised welcome messages
   - Introduce available services and capabilities
   - Set positive tone for the conversation

2. ACCOUNT HOLDINGS AND BALANCES
   - Provide comprehensive account summaries including balances and basic account information
   - Handle queries about account balances across all account types (bank accounts, credit cards, loans, investment accounts)
   - Display account holdings and basic account details
   - Answer "what accounts do I have?" and "show my account balances" type questions

3. ACTION-ORIENTED SELF-SERVICE TASKS
   - Handle action-oriented banking queries that don't fit other domains
   - Process requests for payments, transfers, and general banking actions
   - Provide self-service links and guidance for banking tasks
   - Handle queries like "pay someone", "find my nearest branch", "lock my card", etc.
   - Route users to appropriate self-service options and deep links

4. DOMAIN-UNCLEAR QUERY CLARIFICATION
   - Identify when user queries do not contain ANY reference to to the three domains
   - Generate helpful clarifying questions to understand which domain the user needs
   - Guide users toward the appropriate domain based on their actual needs
   - Provide clear examples to help users articulate domain-specific requests

5. GENERAL CAPABILITY QUESTIONS
   - Handle "what can you do?" type questions
   - Explain available services and areas
   - Provide overview of capabilities
   - Help users understand how to get the most relevant assistance

DOMAIN-UNCLEAR QUERY DEFINITION:

A query is considered domain-unclear (ambiguous) when it does not contain ANY reference to the three domains:

DOMAINS:
- **Savings & Money Management**: Account balances, transactions, spending analysis, budgets, affordability questions, bills, savings goals, debt management
- **Banking Products & Services**: Credit cards, personal loans, savings accounts, term deposits, product features, rates, eligibility, applications
- **Home Loans & Property**: Borrowing power, mortgage calculations, property valuations, home loan applications, refinancing, LVR, stamp duty

EXAMPLES OF DOMAIN-UNCLEAR QUERIES (route to General Queries):
- "I need help" (no domain context)
- "Can you assist me?" (no specific area mentioned)
- "I have a question" (no domain indicators)
- "Help me understand my options" (unclear which domain)
- "I'm not sure what I'm looking for" (needs clarification)

EXAMPLES OF DOMAIN-CLEAR QUERIES (route to agents):
- "What's my account balance?" → Savings agent (clear transaction/balance query)
- "Credit card interest rates?" → Products agent (clear product inquiry)
- "How much can I borrow for a house?" → Homebuying agent (clear mortgage query)
- "Show my spending this month" → Savings agent (clear spending analysis)

WHEN TO ROUTE TO GENERAL QUERIES AGENT (LAST RESORT ONLY):

ONLY route here when:
- User provides a greeting without ANY domain context ("Hi", "Hello", "Good morning")
- Query has ABSOLUTELY NO domain indicators and cannot be reasonably mapped to any domain
- User asks pure capability questions ("What can you help with?", "What do you do?")
- Completely generic requests with zero domain context ("I need help", "Can you assist me?" with no follow-up)
- Basic account balance and holdings queries ("What accounts do I have?", "Show my account balances", "What's my account summary?")
- Simple account overview requests that don't require detailed analysis or management

DO NOT route here for:
- Queries with ANY domain indicators, even if unclear, incomplete, or confusing
- ANY question that mentions financial terms, products, money, property, or banking concepts
- Follow-up questions in ongoing conversations with established domain context
- Queries that can be reasonably inferred to belong to a domain
- Questions that need clarification but have some domain context

CRITICAL: Agents handle their own clarifications. Only route to General Queries if there is truly NO WAY to determine which domain applies.

RESPONSE STRATEGY:
- For greetings: Respond warmly and provide overview of the three areas
- For domain-unclear queries: Ask specific clarifying questions that map to the three domains
- For capability questions: Explain the three areas and their coverage
- Always aim to route users to the most relevant agent after clarification

CLARIFICATION APPROACH:
Present the three domains as clear options:
1. "Managing your money and spending" (Savings agent)
2. "Learning about CommBank products" (Products agent)
3. "Home loans and property advice" (Homebuying agent)"""

general_queries_description = DomainDescription(
    name="general_queries",
    description=GENERAL_QUERIES_ROLE_DESCRIPTION,
    keywords=[],
    example_queries=[],
    negative_examples=[],
)

# Complete list of all domain descriptions for INTERNAL agents only.
# External agents (e.g. weather, disputes) are discovered dynamically
# from A2A agent cards at runtime — no entries needed here.
# For feature-flag-aware filtering use `get_domain_descriptions()`.
DOMAIN_DESCRIPTIONS: list[DomainDescription] = [
    homebuying_description,
    products_description,
    savings_description,
    general_queries_description,
]


def get_domain_descriptions(enabled_agents: set[str] | None = None) -> list[DomainDescription]:
    """Return domain descriptions, optionally filtered to enabled_agents.

    Args:
        enabled_agents: If provided, only descriptions whose `name` is in this
            set are returned.  If `None`, all descriptions are returned
            (backward-compatible default).

    Returns:
        List of `DomainDescription` objects.
    """
    if enabled_agents is None:
        return list(DOMAIN_DESCRIPTIONS)
    return [d for d in DOMAIN_DESCRIPTIONS if d.name in enabled_agents]


def get_domain_description(agent_name: str, enabled_agents: set[str] | None = None) -> str:
    """Get the full description for a specific agent domain.

    Args:
        agent_name: Name of the agent (e.g., "homebuying", "products", "savings", "general_queries").
        enabled_agents: If provided, only descriptions in this set are
            searchable.  If `None`, all descriptions are searched.

    Returns:
        Full description string for the agent domain.

    Raises:
        KeyError: If `agent_name` is not found in the (filtered) descriptions.
    """
    descriptions = get_domain_descriptions(enabled_agents)
    for desc in descriptions:
        if desc.name == agent_name:
            return desc.description

    available_agents = [desc.name for desc in descriptions]
    raise KeyError(f"Agent '{agent_name}' not found. Available agents: {available_agents}")


def get_all_domains(enabled_agents: set[str] | None = None) -> list[str]:
    """Get a list of available agent domain names.

    Args:
        enabled_agents: If provided, only domain names in this set are returned.
            If `None`, all domain names are returned.

    Returns:
        List of agent domain name strings.
    """
    return [desc.name for desc in get_domain_descriptions(enabled_agents)]


def get_keywords(agent_name: str, enabled_agents: set[str] | None = None) -> list[str]:
    """Get the keywords associated with a specific agent domain.

    Args:
        agent_name: Name of the agent.
        enabled_agents: If provided, only descriptions in this set are
            searchable.  If `None`, all descriptions are searched.

    Returns:
        List of keywords for the agent domain.

    Raises:
        KeyError: If `agent_name` is not found in the (filtered) descriptions.
    """
    descriptions = get_domain_descriptions(enabled_agents)
    for desc in descriptions:
        if desc.name == agent_name:
            return desc.keywords

    available_agents = [desc.name for desc in descriptions]
    raise KeyError(f"Agent '{agent_name}' not found. Available agents: {available_agents}")
