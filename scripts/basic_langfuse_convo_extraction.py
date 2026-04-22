"""This is a simple script to extract conversations (just input and output) from Langfuse and outputs it as an Excel sheet.

Before running, make sure that LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_HOST environment variables are set
in .env.local and source them using:
```
source.env.local
```

To run:
```
python -m scripts.basic_langfuse_convo_extraction
```
"""

import datetime as dt
import os
from zoneinfo import ZoneInfo

import pandas as pd
from langfuse import Langfuse
from langfuse.client import FetchSessionsResponse, FetchTracesResponse, Session, TraceWithDetails

from common.logging.core import logger

# NOTE: Change these parameters
START_TIMESTAMP = "2026/02/25 00:00"
END_TIMESTAMP = "2026/02/25 23:59"
SELECTED_USER_IDS = [
    "12345678",
    "87654321",
]  # Dummy user ids, replace with actual ones or leave empty to include all users

OUTPUT_PATH = "langfuse_conversations.xlsx"


def _parse_timestamp(
    timestamp_str: str, timestamp_format: str = "%Y/%m/%d %H:%M", input_tz_name: str = "Australia/Sydney"
) -> dt.datetime:
    naive = dt.datetime.strptime(timestamp_str, timestamp_format)
    try:
        input_tz = ZoneInfo(input_tz_name)
    except Exception as e:
        raise ValueError(f"Invalid INPUT_TIMEZONE: {input_tz_name}") from e

    aware = naive.replace(tzinfo=input_tz)
    return aware.astimezone(dt.UTC)


start_dt = _parse_timestamp(START_TIMESTAMP)
end_dt = _parse_timestamp(END_TIMESTAMP)

langfuse_client = Langfuse(
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    host=os.getenv("LANGFUSE_HOST"),
)

# Get all sessions
logger.info(f"Fetching sessions from {start_dt} to {end_dt}...")
sessions: FetchSessionsResponse = langfuse_client.fetch_sessions(
    from_timestamp=start_dt,
    to_timestamp=end_dt,
)
total_pages = sessions.meta.total_pages
if total_pages > 1:
    logger.info(f"Total pages of sessions: {total_pages}. Fetching all pages...")
    sessions_data: list[Session] = [
        item
        for page in range(1, total_pages + 1)
        for item in langfuse_client.fetch_sessions(from_timestamp=start_dt, to_timestamp=end_dt, page=page).data
    ]
else:
    sessions_data = sessions.data

# Process all turns
rows = []
for session_data in sessions_data:
    logger.info(f"Processing session {session_data.id} for user {session_data.user_id}...")
    session_id = session_data.id
    traces: FetchTracesResponse = langfuse_client.fetch_traces(session_id=session_id)
    traces_data: list[TraceWithDetails] = traces.data
    traces_data.sort(key=lambda x: x.createdAt)

    for turn_number, trace in enumerate(traces_data, start=1):
        user_id = trace.user_id

        # Skip if it's not in the selected user ids (if the list is not empty)
        if SELECTED_USER_IDS and user_id not in SELECTED_USER_IDS:
            logger.info(f"Skipping trace {trace.id} for user {user_id} as it's not in the selected user ids.")
            continue

        logger.info(f"Processing trace {trace.id} for user {user_id}...")
        trace_id = trace.id

        # Get the timestamp in Sydney timezone and format it as desired
        timestamp: str = trace.createdAt
        # Timestamp is UTC, convert to desired timezone
        # Format of timestamp '2026-02-25T04:49:06.716Z'
        timestamp_dt = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        timestamp_dt = timestamp_dt.astimezone(ZoneInfo("Australia/Sydney"))
        timestamp_str = timestamp_dt.strftime("%Y/%m/%d %H:%M:%S")

        # Get the user message
        user_message = trace.input

        # Get the agent's response message safely
        agent_response = None
        if isinstance(trace.output, dict):
            agent_response = trace.output.get("response_message", [])
            if len(agent_response) != 1:
                logger.warning(f"Trace {trace_id} has unexpected output format: {trace.output}")

            else:
                agent_response = agent_response[0]
                content = agent_response.get("content", None)
                if not content:
                    logger.warning(f"Trace {trace_id} has response_message without content: {agent_response}")

                else:
                    agent_response = content

        rows.append(
            {
                "timestamp": timestamp_str,
                "user_id": user_id,
                "session_id": session_id,
                "trace_id": trace_id,
                "turn_number": turn_number,
                "user_message": user_message,
                "agent_response": agent_response,
            }
        )

output_df = pd.DataFrame(rows)
output_df.to_excel(OUTPUT_PATH, index=False)
logger.info(f"Extracted conversations saved to {OUTPUT_PATH}")
