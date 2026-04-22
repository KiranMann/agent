"""
Integration tests for Financial Companion API endpoints.
1. Get DP Token
2. Send Message
3. Get Conversations
4. Get a Conversation

Requirements:
1. Get DP Token is called ONCE and token is shared with all following tests
2. Send Message is driven by test data in YAML file (all queries are sent in the same 1 session)
3. Get Conversations runs ONLY ONCE
4. Get a Conversation runs ONLY ONCE

Test data is driven by YAML configuration files.
"""

import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import requests
import urllib3
import yaml


def _ensure_repo_root_on_sys_path() -> None:
    """Ensure repository root is on sys.path so local packages can be imported.

    This script is sometimes invoked in environments where the repo isn't automatically added
    to `sys.path` (e.g., different runners / packaging layouts). We insert the repo root
    (two levels above `tests/`) as a best-effort fallback.

    Note:
        We also evict any already-imported `all_agents` / `common` modules if they were imported
        before `sys.path` was corrected, because that can leave Python with a partially-initialised
        package state and subsequent imports may fail.
    """

    repo_root = Path(__file__).resolve().parents[2]
    repo_root_str = str(repo_root)

    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)

    # Ensure we import from repo checkout, not from a globally-installed package.
    for module_name in list(sys.modules):
        if module_name == "all_agents" or module_name.startswith("all_agents."):
            sys.modules.pop(module_name, None)
        if module_name == "common" or module_name.startswith("common."):
            sys.modules.pop(module_name, None)

    try:
        all_agents_path = (repo_root / "all_agents").resolve()
        common_path = (repo_root / "common").resolve()

        all_agents_module = sys.modules.get("all_agents")
        if all_agents_module is not None:
            module_file = getattr(all_agents_module, "__file__", None)
            if isinstance(module_file, str) and module_file:
                module_path = Path(module_file).resolve()
                if all_agents_path not in module_path.parents:
                    sys.modules.pop("all_agents", None)

        common_module = sys.modules.get("common")
        if common_module is not None:
            module_file = getattr(common_module, "__file__", None)
            if isinstance(module_file, str) and module_file:
                module_path = Path(module_file).resolve()
                if common_path not in module_path.parents:
                    sys.modules.pop("common", None)
    except Exception:
        # Best-effort only: failure here should not break the integration run.
        logger.debug("Failed to validate module origin for all_agents/common", exc_info=True)


_ensure_repo_root_on_sys_path()


# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class FinancialCompanionAPITester:
    """Test class for Financial Companion API integration tests."""

    def __init__(
        self,
        config_path: str = "tests/test_data/api_test_config.yaml",
        environment: str = "test2",
    ):
        """Initialize the API tester with configuration."""
        self.config = self._load_config(config_path)
        self.session = self._create_session()
        self.dp_token: str | None = None
        self.environment = environment

        # Session IDs are driven by the YAML test data
        self.send_message_session_id: str | None = None

        # Set service host based on environment
        service_hosts = self.config["test_data"].get("service_hosts", {})
        if environment in service_hosts:
            self.service_host = service_hosts[environment]
        else:
            # Default to test2
            self.service_host = service_hosts.get("test2", "retail.group.api.test.commbank.com.au")

        # Initialize question_tool_map for the test run
        self.results_dir = Path("evals/financial_companion_eval/results")
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Load unique tools
        unique_tools_file = self.results_dir / "unique_tools.json"
        try:
            with open(unique_tools_file, encoding="utf-8") as f:
                loaded_tools = json.load(f)

            if not isinstance(loaded_tools, list) or not all(isinstance(t, str) for t in loaded_tools):
                raise ValueError("unique_tools.json must be a JSON list of strings")

            self.all_tools = loaded_tools
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            logger.exception("Failed to load unique_tools.json")
            self.all_tools = []

        # Generate filename with current date and time
        current_datetime = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.question_tool_map_file = self.results_dir / f"question_tool_map_{current_datetime}.json"

        # Initialize fresh map structure for each run
        self.question_tool_map = {
            "tool_question_map": {},  # Maps tools to the questions that use them
            "unused_tools": self.all_tools.copy(),  # Start with all tools as unused
            "unknown_tools": [],  # List of unrecognized tools if any appear
            "unknown_tool_question_map": {},  # Maps unknown tools to the questions that emitted them
            "run_datetime": current_datetime,  # Add timestamp information to the map
        }

        # Thread lock for concurrent access to shared state (tool recording)
        self._tool_map_lock = threading.Lock()

    def _load_config(self, config_path: str) -> dict[str, Any]:
        """Load test configuration from YAML file.

        Note:
            To avoid reusing conversation IDs across repeated runs, this loader regenerates a fresh
            `session_id` for each active message while preserving the last 12 hex characters.

            - The last 12 hex characters are treated as a stable "group key".
            - Messages that share the same original suffix will share the same regenerated session_id
              (e.g., question + "Yes" follow-up).

            This allows grouping related turns while still avoiding cross-run session reuse.
        """
        try:
            with open(config_path, encoding="utf-8") as file:
                config = yaml.safe_load(file)

            messages = config.get("test_data", {}).get("messages", [])
            suffix_map: dict[str, str] = {}

            if isinstance(messages, list):
                for message in messages:
                    if not isinstance(message, dict):
                        continue

                    old_session_id = message.get("session_id")
                    if not isinstance(old_session_id, str):
                        continue

                    # YAML stores session_id as a 12-hex suffix only.
                    suffix = old_session_id.upper()

                    if suffix not in suffix_map:
                        # Build a fresh UUID-like value while preserving the stable 12-hex suffix.
                        # UUID format (32 hex): 8-4-4-4-12
                        raw32 = uuid.uuid4().hex.upper()[:20] + suffix
                        suffix_map[suffix] = f"{raw32[0:8]}-{raw32[8:12]}-{raw32[12:16]}-{raw32[16:20]}-{raw32[20:32]}"

                    message["session_id"] = suffix_map[suffix]

            logger.info(
                "Loaded configuration from %s (regenerated %s message session_ids across %s groups)",
                config_path,
                len(messages) if isinstance(messages, list) else 0,
                len(suffix_map),
            )
            return config  # type: ignore[no-any-return]
        except (FileNotFoundError, yaml.YAMLError):
            logger.exception("Failed to load configuration from %s", config_path)
            raise

    def _create_session(self) -> requests.Session:
        """Create a requests session with SSL verification disabled."""
        session = requests.Session()
        session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return session

    def _validate_response(self, response: requests.Response, endpoint_name: str) -> None:
        """Validate response status and expected content."""
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        expected_content = self.config["endpoints"][endpoint_name].get("expectedContentInResponse")
        if expected_content and expected_content not in response.text:
            raise AssertionError(f"Expected '{expected_content}' in response, but not found")

    def _record_tool_usage(self, tool_name: str, user_query: str) -> None:
        """Record a tool usage against a user query in the tool map.

        Thread-safe: Uses lock to protect concurrent access during parallel test execution.
        """
        with self._tool_map_lock:
            tool_question_map = cast("dict[str, list[str]]", self.question_tool_map["tool_question_map"])
            unused_tools = cast("list[str]", self.question_tool_map["unused_tools"])
            unknown_tools = cast("list[str]", self.question_tool_map["unknown_tools"])

            if tool_name in self.all_tools:
                if tool_name not in tool_question_map:
                    tool_question_map[tool_name] = []

                if user_query not in tool_question_map[tool_name]:
                    tool_question_map[tool_name].append(user_query)

                if tool_name in unused_tools:
                    unused_tools.remove(tool_name)
            else:
                if tool_name not in unknown_tools:
                    unknown_tools.append(tool_name)

                unknown_map = self.question_tool_map.get("unknown_tool_question_map")
                if not isinstance(unknown_map, dict):
                    unknown_map = {}
                    self.question_tool_map["unknown_tool_question_map"] = unknown_map

                questions = unknown_map.get(tool_name)
                if not isinstance(questions, list):
                    questions = []
                    unknown_map[tool_name] = questions

                if user_query not in questions:
                    questions.append(user_query)

            try:
                with open(self.question_tool_map_file, "w", encoding="utf-8") as f:
                    json.dump(self.question_tool_map, f, indent=2)
            except Exception:
                logger.exception("Failed to write %s", self.question_tool_map_file.name)

    def _capture_tools_from_conversation(self, conversation: dict[str, Any], user_query: str) -> None:
        """Infer tool usage from the final conversation payload (ui_components/widget_type).

        This is a fallback for cases where progress events do not surface all tool calls
        because progress storage only retains the latest progress update per session.

        Implementation note:
            We avoid importing `all_agents.*` (and its third-party deps) here.
            Instead we statically infer a mapping from per-agent `create_ui_components.py` files.
        """
        try:
            repo_root = Path(__file__).resolve().parents[2]

            messages = conversation.get("messages")
            if not isinstance(messages, list):
                return

            # Find the last agent message
            agent_messages = [m for m in messages if isinstance(m, dict) and m.get("role") == "Agent"]
            if not agent_messages:
                return

            ui_components = agent_messages[-1].get("ui_components")
            if not isinstance(ui_components, list):
                return

            widget_types = {
                comp.get("widget_type")
                for comp in ui_components
                if isinstance(comp, dict) and isinstance(comp.get("widget_type"), str)
            }
            if not widget_types:
                return

            widget_type_to_tool_name = self._build_widget_type_to_tool_name_map(repo_root)
            for widget_type in widget_types:
                tool_name = widget_type_to_tool_name.get(str(widget_type))
                if not tool_name:
                    continue

                logger.info("Inferred tool %s from widget_type %s", tool_name, widget_type)
                self._record_tool_usage(tool_name, user_query)
        except Exception as exc:
            logger.exception(
                "Failed to infer tools from conversation structure",
                exc_info=exc,
                extra={"cwd": os.getcwd(), "sys_path_head": sys.path[:10]},
            )

    @staticmethod
    def _build_widget_type_to_tool_name_map(repo_root: Path) -> dict[str, str]:
        """Build a widget_type -> tool_name map by parsing per-agent create_ui_components modules.

        This relies on a simple convention used across agents:
        - tool name is the Python function name, e.g. `build_savings_goals_widget`
        - widget type is set as a string literal in the function body: `widget_type = "goal_tracker"`

        Args:
            repo_root: Repository root directory.

        Returns:
            Mapping of widget_type to tool_name.
        """
        mapping: dict[str, str] = {}

        create_ui_components_files = repo_root.glob(
            "all_agents/task_agents/*/tools/gen_ui_schema_tools/create_ui_components.py"
        )

        current_tool_name: str | None = None
        current_widget_type: str | None = None

        for file_path in create_ui_components_files:
            try:
                content = file_path.read_text(encoding="utf-8")
            except OSError:
                continue

            # Reset per file.
            current_tool_name = None
            current_widget_type = None

            for line in content.splitlines():
                tool_match = re.match(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
                if tool_match:
                    if current_tool_name and current_widget_type and current_widget_type not in mapping:
                        mapping[current_widget_type] = current_tool_name

                    current_tool_name = tool_match.group(1)
                    current_widget_type = None
                    continue

                if current_tool_name is None:
                    continue

                widget_match = re.match(r"^\s*widget_type\s*=\s*\"([^\"]+)\"\s*$", line)
                if widget_match:
                    current_widget_type = widget_match.group(1)
                    continue

            if current_tool_name and current_widget_type and current_widget_type not in mapping:
                mapping[current_widget_type] = current_tool_name

        return mapping

    def _build_url(self, endpoint_name: str, **kwargs: str) -> str:
        """Build URL for an endpoint with dynamic parameters."""
        url_template: str = self.config["endpoints"][endpoint_name]["url"]
        format_params = {"serviceHost": self.service_host, **kwargs}
        return url_template.format(**format_params)

    def _get_auth_headers(self) -> dict[str, str]:
        """Get authorization headers with DP token."""
        if not self.dp_token:
            raise ValueError("DP Token is required. Call get_dp_token() first.")
        return {
            "Authorization": f"Bearer {self.dp_token}",
            "Content-Type": "application/json",
        }

    def _validate_dp_token(self) -> None:
        """Validate that DP token is available."""
        if not self.dp_token:
            raise ValueError("DP Token is required. Call get_dp_token() first.")

    def _log_streaming_failure(self, expected_content: str, streaming_response: str, error_type: str) -> None:
        """Log streaming failure details for debugging."""
        failure_msg = f"❌ {error_type} without finding expected content '{expected_content}'"
        response_info = [
            f"{error_type}. Received response body:",
            f"Response length: {len(streaming_response)} characters",
            f"Response content: {streaming_response}",
            f"Expected: '{expected_content}'",
            f"Received: '{streaming_response}'",
        ]

        # Print for GitHub Actions visibility
        print(failure_msg)
        for info in response_info:
            print(info)

        # Standard logging
        logger.info(failure_msg)
        for info in response_info:
            logger.info(info)

    def get_dp_token(self) -> str:
        """
        Test API 1: Get DP Token

        Returns:
            str: The DP token for authentication

        Raises:
            requests.RequestException: If the API call fails
            ValueError: If the response doesn't contain a valid token
        """
        logger.info("Testing API 1: Get DP Token")

        url = self.config["endpoints"]["get_dp_token"]["url"]
        payload = {
            "Environment": self.config["test_data"]["token_env"],
            "NetbankId": self.config["test_data"]["netbank_id"],
            "IsLocal": "false",
            "RegisterInCAAS": False,
        }

        try:
            logger.info(f"DP Token API Request URL: {url}")
            logger.info(f"DP Token API Request Body: {json.dumps(payload, indent=2)}")

            response = self.session.post(url, json=payload, headers={"Content-Type": "application/json"})

            logger.info(f"DP Token API Response Status: {response.status_code}")
            logger.info(f"DP Token API Response Body: {response.text}")

            # Validate status code
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"

            # Parse response
            response_data = response.json()

            # Validate response contains DpTok
            if "DpTok" not in response_data:
                raise ValueError("Response does not contain 'DpTok' field")

            if "error" in response_data.get("DpTok", ""):
                raise ValueError(f"Error in DpTok: {response_data['DpTok']}")

            self.dp_token = response_data["DpTok"]
            logger.info("Successfully obtained DP Token")

            return self.dp_token if self.dp_token is not None else ""

        except requests.RequestException:
            logger.exception("Failed to get DP Token")
            raise
        except (json.JSONDecodeError, ValueError):
            logger.exception("Invalid response format")
            raise

    def get_conversations(self) -> dict[str, Any]:
        """Test API 2: Get Conversations"""
        return self._api_call_with_logging("GET", "Get Conversations", self._build_url("get_conversations"))

    def get_conversation(self, session_id: str) -> dict[str, Any]:
        """Test API 3: Get a Conversation"""
        return self._api_call_with_logging(
            "GET",
            "Get Conversation",
            self._build_url("get_conversation", session_id=session_id),
        )

    def send_message(self, user_query: str, session_id: str) -> dict[str, Any]:
        """Send message with streaming response handling."""
        logger.info("Testing API 4: Send Message (Streaming) - '%s' to session %s", user_query, session_id)

        headers = {**self._get_auth_headers(), "Accept": "text/event-stream"}
        payload = {
            "context": {"sessionId": session_id},
            "data": {
                "version": "1.0",
                "type": "sendQuery",
                "payload": {"query": user_query},
            },
            "version": "1.0",
        }

        logger.info("Send Message API Request URL: %s", self._build_url("send_message"))
        logger.info("Send Message API Request Body: %s", json.dumps(payload, indent=2))
        logger.info("Send Message API Request Headers: %s", json.dumps(headers, indent=2))

        response = self.session.post(
            self._build_url("send_message"),
            json=payload,
            headers=headers,
            stream=True,
            timeout=120,
        )
        logger.info("Send Message API Response Status: %s", response.status_code)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        # Stream progress/tool events first...
        stream_result = self._handle_streaming_response(response, user_query)

        # ...then deterministically infer UI widget tools from the final conversation payload.
        # This is necessary because ProgressStore only retains the *latest* progress update per session, so
        # tool progress events like build_savings_goals_widget can be overwritten by later tool/agent events
        # before polling yields them.
        try:
            conversation = self.get_conversation(session_id)
            self._capture_tools_from_conversation(conversation, user_query)
        except Exception:
            logger.exception("Failed to infer tools from conversation payload")

        return stream_result

    def _handle_streaming_response(self, response: requests.Response, user_query: str) -> dict[str, Any]:
        """Handle streaming response with content validation."""
        expected_content = self.config["endpoints"]["send_message"].get("expectedContentInResponse")

        if not expected_content:
            # No content validation needed
            streaming_response = self._read_stream(response)
            logger.info(f"Send Message API Response Body: {streaming_response}")
            logger.info(f"Successfully sent message: '{user_query}'")
            return {"streaming_response": streaming_response, "content_found": None}

        logger.info(f"Waiting up to 60 seconds for expected content: '{expected_content}'")

        start_time = time.time()
        streaming_response = ""
        content_found = False

        try:
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    streaming_response += line + "\n"
                    logger.info("line%s", line)
                    if "data:" in line:
                        try:
                            # Extract the JSON part of the line
                            json_start = line.index("{")  # Find the starting point of the JSON string
                            json_data = line[json_start:]  # Extract everything from '{' onwards

                            # Parse the JSON data
                            parsed_data = json.loads(json_data)

                            # Capture tool usage from TWO places:
                            # 1) Progress events (event:thinking) for tools, emitted by EnhancedAgentHooks.
                            # 2) Final response payload (event:response / Get Conversation) that contains ui_components.
                            #    UI widgets are created by tools like build_savings_goals_widget but may not always
                            #    show up as progress events (ProgressStore only keeps the latest update per session).

                            # (1) Progress tool events
                            step_type = parsed_data.get("step_type")
                            tool_name = parsed_data.get("tool_name")

                            if tool_name and step_type in {"tool_start", "tool_end"}:
                                logger.info("Captured tool event %s: %s", step_type, tool_name)
                                self._record_tool_usage(tool_name, user_query)
                                logger.info(
                                    "Updated %s with tool: %s (%s)",
                                    self.question_tool_map_file.name,
                                    tool_name,
                                    step_type,
                                )
                        except (ValueError, json.JSONDecodeError):
                            # Handle cases of invalid JSON parsing
                            logger.exception("Error parsing SSE line JSON")

                # Check for expected content and timeout
                if not content_found and expected_content in streaming_response:
                    logger.info(f"✅ Expected content '{expected_content}' found in streaming response")
                    content_found = True
                    streaming_response += self._read_remaining_stream(response)
                    break

                if time.time() - start_time > 60:
                    raise AssertionError(f"Expected content '{expected_content}' not found within 60 seconds")

        except (
            requests.exceptions.ChunkedEncodingError,
            urllib3.exceptions.ProtocolError,
        ) as e:
            self._log_streaming_failure(expected_content, streaming_response, "Stream connection closed")

            if expected_content in streaming_response:
                content_found = True
                logger.info("✅ Expected content found before connection closed")
                print("✅ Expected content found before connection closed")
            else:
                logger.exception("❌ Stream connection closed before finding expected content")
                raise AssertionError(
                    f"Stream connection closed before finding expected content '{expected_content}'"
                ) from e

        if content_found:
            logger.info(f"Send Message API Response Body: {streaming_response}")
            logger.info(f"Successfully sent message: '{user_query}'")
            return {"streaming_response": streaming_response, "content_found": True}
        else:
            self._log_streaming_failure(expected_content, streaming_response, "Stream ended normally")
            raise AssertionError(f"Expected content '{expected_content}' not found in streaming response")

    def _read_stream(self, response: requests.Response) -> str:
        """Read entire stream without content validation."""
        streaming_response = ""
        try:
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    streaming_response += line + "\n"
        except (
            requests.exceptions.ChunkedEncodingError,
            urllib3.exceptions.ProtocolError,
        ):
            logger.debug("Stream connection closed (no expected content check)")
        return streaming_response

    def _read_remaining_stream(self, response: requests.Response) -> str:
        """Read remaining stream after finding expected content."""
        remaining_response = ""
        try:
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    remaining_response += line + "\n"
        except (
            requests.exceptions.ChunkedEncodingError,
            urllib3.exceptions.ProtocolError,
        ):
            logger.debug("Stream connection closed after finding expected content")
        return remaining_response

    def run_full_test_suite(self) -> dict[str, Any]:
        """
        Run the complete test suite with error isolation.

        Flow:
        1. get_dp_token() - try up to 3 times, if all fail then stop
        2. get_conversations(), get_conversation(), send_message() x N - continue on errors

        Returns:
            Dict[str, Any]: Test results summary
        """
        suite_start_time = time.time()
        logger.info("🚀 Starting API Integration Test Suite")

        test_results: dict[str, Any] = {
            "dp_token_test": {
                "status": "pending",
                "data": None,
                "error": None,
                "duration": 0,
            },
            "conversations_test": {
                "status": "pending",
                "data": None,
                "error": None,
                "duration": 0,
            },
            "conversation_test": {
                "status": "pending",
                "data": None,
                "error": None,
                "duration": 0,
            },
            "send_message_tests": [],
            "total_duration": 0,
        }

        # Step 1: Get DP Token with retry (CRITICAL)
        logger.info("=" * 60)
        logger.info("🔑 STEP 1: Getting DP Token (required for all tests)")
        logger.info("=" * 60)

        dp_token_success = False
        dp_token_start_time = time.time()
        for attempt in range(1, 4):  # 3 attempts
            try:
                logger.info(f"DP Token attempt {attempt}/3")
                self.get_dp_token()
                dp_token_duration = time.time() - dp_token_start_time
                test_results["dp_token_test"] = {
                    "status": "success",
                    "data": {"attempts": attempt},
                    "error": None,
                    "duration": dp_token_duration,
                }
                logger.info(f"✅ DP Token obtained successfully on attempt {attempt}")
                dp_token_success = True
                break
            except Exception as e:
                logger.exception("❌ DP Token attempt %s/3 failed", attempt)
                if attempt == 3:
                    dp_token_duration = time.time() - dp_token_start_time
                    test_results["dp_token_test"] = {
                        "status": "failed",
                        "data": {"attempts": 3},
                        "error": str(e),
                        "duration": dp_token_duration,
                    }

        if not dp_token_success:
            logger.exception("🛑 DP Token failed after 3 attempts - skipping all other tests")
            test_results["conversations_test"]["status"] = "skipped"
            test_results["conversation_test"]["status"] = "skipped"
            return test_results

        # Step 2: Run remaining tests with error isolation
        messages = self.config["test_data"]["messages"]
        total_remaining_tests = 2 + len(messages)  # conversations + conversation + messages

        # Group messages by session_id for concurrent execution
        session_groups = self._group_messages_by_session(messages)
        num_sessions = len(session_groups)

        logger.info("=" * 60)
        logger.info(
            f"📋 STEP 2: Running {len(messages)} message tests across {num_sessions} sessions "
            f"(concurrent sessions, sequential within session)"
        )
        logger.info("=" * 60)

        # Tests: Send Messages (run session groups concurrently)
        send_messages_start_time = time.time()
        all_results: list[dict[str, Any]] = []

        # Use ThreadPoolExecutor to run session groups concurrently
        # Each session group runs its messages sequentially to maintain conversation order
        max_workers = min(num_sessions, 10)  # Cap at 10 concurrent sessions to avoid overwhelming the API
        logger.info(f"🚀 Starting concurrent execution with {max_workers} workers for {num_sessions} session groups")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit each session group as a separate task
            future_to_session = {
                executor.submit(self._run_session_group, session_id, group_messages): session_id
                for session_id, group_messages in session_groups.items()
            }

            # Collect results as they complete
            for future in as_completed(future_to_session):
                session_id = future_to_session[future]
                try:
                    session_results = future.result()
                    all_results.extend(session_results)
                    logger.info(f"✅ Session {session_id[:8]}... completed with {len(session_results)} messages")
                except Exception:
                    logger.exception(f"❌ Session {session_id[:8]}... failed with error.")
                    # Add failed result for the session
                    all_results.append(
                        {
                            "status": "failed",
                            "session_id": session_id,
                            "test_name": f"Session {session_id[:8]}...",
                        }
                    )

        # Sort results to maintain original message order for reporting
        test_results["send_message_tests"] = all_results

        # Calculate total send messages duration
        send_messages_duration = time.time() - send_messages_start_time
        logger.info(f"⏱️ All {len(messages)} messages completed in {send_messages_duration:.1f}s (was sequential)")

        # Test: Get Conversations
        logger.info("Running get_conversations test")
        test_results["conversations_test"] = self._run_isolated_test(
            "get_conversations",
            lambda: self._api_call_with_logging(
                "GET",
                "Get Conversations",
                self._build_url("get_conversations"),
            ),
        )

        # Test: Get Conversation (use last message session_id from config)
        last_session_id = messages[-1]["session_id"]
        logger.info(f"Running get_conversation test for session {last_session_id}")
        test_results["conversation_test"] = self._run_isolated_test(
            "get_conversation",
            lambda: self._api_call_with_logging(
                "GET",
                "Get Conversation",
                self._build_url("get_conversation", session_id=last_session_id),
            ),
        )

        # Summary
        successful_tests = sum(
            1
            for r in [
                test_results["conversations_test"],
                test_results["conversation_test"],
            ]
            + test_results["send_message_tests"]
            if r["status"] == "success"
        )

        # Calculate total suite duration
        test_results["total_duration"] = time.time() - suite_start_time
        test_results["send_messages_total_duration"] = send_messages_duration

        logger.info("=" * 60)
        logger.info(f"🏁 Test suite completed: {successful_tests}/{total_remaining_tests} tests successful")
        logger.info(f"Here is the final question tool map:{self.question_tool_map}")

        return test_results

    def _run_isolated_test(
        self,
        test_name: str,
        test_func: Callable[[], dict[str, Any]],
        message_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a single test with error isolation."""
        start_time = time.time()
        try:
            data = test_func()
            duration = time.time() - start_time
            logger.info(f"✅ {test_name} passed")

            result = {
                "status": "success",
                "data": data,
                "error": None,
                "duration": duration,
            }
            if message_config:
                result.update(
                    {
                        "test_name": f"{message_config['agent']} - {message_config['query'][:50]}...",
                        "agent": message_config["agent"],
                        "query": message_config["query"],
                        "session_id": message_config["session_id"],
                        "response": data,
                    }
                )
            return result

        except Exception as e:
            duration = time.time() - start_time
            logger.exception("❌ %s failed", test_name)

            result = {
                "status": "failed",
                "data": None,
                "error": str(e),
                "duration": duration,
            }
            if message_config:
                result.update(
                    {
                        "test_name": f"{message_config['agent']} - {message_config['query'][:50]}...",
                        "agent": message_config["agent"],
                        "query": message_config["query"],
                        "session_id": message_config["session_id"],
                        "response": None,
                    }
                )
            return result

    def _create_send_message_test(self, message_config: dict[str, Any]) -> Callable[[], dict[str, Any]]:
        """Create a test function for sending a message with the given configuration."""

        def test_func() -> dict[str, Any]:
            # Use the original send_message method for streaming support
            return self.send_message(message_config["query"], message_config["session_id"])

        return test_func

    def _group_messages_by_session(self, messages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Group messages by session_id while preserving order within each group.

        Messages with the same session_id are part of a multi-turn conversation
        and must be executed sequentially. Different sessions can run concurrently.

        Args:
            messages: List of message configurations from the test config.

        Returns:
            Dictionary mapping session_id to ordered list of messages for that session.
        """
        session_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for message in messages:
            session_id = message["session_id"]
            session_groups[session_id].append(message)

        # Log grouping summary
        multi_turn_sessions = {sid: msgs for sid, msgs in session_groups.items() if len(msgs) > 1}
        if multi_turn_sessions:
            logger.info(
                f"📊 Session grouping: {len(session_groups)} total sessions, "
                f"{len(multi_turn_sessions)} multi-turn conversations"
            )
            for sid, msgs in multi_turn_sessions.items():
                logger.info(f"   Session {sid[:8]}...: {len(msgs)} messages (sequential)")

        return dict(session_groups)

    def _run_session_group(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Run all messages in a session group sequentially.

        This method is designed to be called from a thread pool executor.
        Messages within the same session must run sequentially to maintain
        conversation context and order.

        Args:
            session_id: The session ID for this group.
            messages: Ordered list of messages to send in this session.

        Returns:
            List of test results for each message in the session.
        """
        results: list[dict[str, Any]] = []
        thread_name = threading.current_thread().name

        logger.info(f"[{thread_name}] Starting session {session_id[:8]}... with {len(messages)} messages")

        for i, message_config in enumerate(messages, 1):
            logger.info(
                f"[{thread_name}] Session {session_id[:8]}... message {i}/{len(messages)}: "
                f"{message_config['query'][:50]}..."
            )

            result = self._run_isolated_test(
                f"send_message_{session_id[:8]}_{i}",
                self._create_send_message_test(message_config),
                message_config,
            )
            results.append(result)

            # If a message in a multi-turn conversation fails, log but continue
            # (the conversation may still be salvageable for subsequent messages)
            if result["status"] == "failed":
                logger.warning(
                    f"[{thread_name}] Session {session_id[:8]}... message {i} failed, "
                    f"continuing with remaining messages"
                )

        logger.info(
            f"[{thread_name}] Completed session {session_id[:8]}... "
            f"({sum(1 for r in results if r['status'] == 'success')}/{len(results)} successful)"
        )

        return results

    def _api_call_with_logging(
        self,
        method: str,
        api_name: str,
        url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make API call with full request/response logging."""
        logger.info("-" * 50)
        logger.info(f"Testing API: {api_name}")

        headers = self._get_auth_headers()

        # Log request details
        logger.info(f"{api_name} API Request URL: {url}")
        if payload:
            logger.info(f"{api_name} API Request Body: {json.dumps(payload, indent=2)}")
        logger.info(f"{api_name} API Request Headers: {json.dumps(headers, indent=2)}")

        # Make request
        response = (
            self.session.get(url, headers=headers)
            if method == "GET"
            else self.session.post(url, json=payload, headers=headers)
        )

        # Log response details
        logger.info(f"{api_name} API Response Status: {response.status_code}")
        logger.info(f"{api_name} API Response Body: {response.text}")

        if response.status_code == 200:
            logger.info(f"Successfully completed {api_name}")
        else:
            logger.warning(f"{api_name} returned non-200 status: {response.status_code}")

        # Parse JSON response
        try:
            return response.json()  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            return {"raw_response": response.text, "status_code": response.status_code}


if __name__ == "__main__":
    try:
        # Create tester instance
        tester = FinancialCompanionAPITester()

        # Run full test suite
        results = tester.run_full_test_suite()

        # Print results summary
        print("\n" + "=" * 60)
        print("TEST RESULTS SUMMARY")
        print("=" * 60)

        print(f"DP Token Test: {results['dp_token_test']['status']}")
        print(f"Conversations Test: {results['conversations_test']['status']}")
        print(f"Conversation Test: {results['conversation_test']['status']}")

        successful_messages = sum(1 for test in results["send_message_tests"] if test["status"] == "success")
        total_messages = len(results["send_message_tests"])
        print(f"Message Tests: {successful_messages}/{total_messages} successful")

        # Print any errors
        for result_key, result in results.items():
            if (
                result_key
                not in [
                    "send_message_tests",
                    "total_duration",
                    "send_messages_total_duration",
                ]
                and result["error"]
            ):
                print(f"ERROR in {result_key}: {result['error']}")

        for test in results["send_message_tests"]:
            if test["error"]:
                print(f"ERROR in {test['agent']} - {test['query'][:50]}...: {test['error']}")

        print("=" * 60)

    except (ImportError, RuntimeError):
        logger.exception("Failed to run test suite")
        sys.exit(1)
