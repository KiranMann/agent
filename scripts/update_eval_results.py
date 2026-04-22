# pylint: disable=inconsistent-quotes
"""Script to update evaluation results documentation by prepending the most recent results from GHA artifacts."""

import argparse
import json
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger()


def extract_agent_type(result_dir: str) -> str:
    """Extract agent type from result directory name."""
    if "_savings" in result_dir:
        return "savings"
    elif "_products" in result_dir:
        return "products"
    elif "_principal" in result_dir:
        return "principal"
    elif "_homebuying" in result_dir:
        return "homebuying"
    else:
        return "all"


def get_agent_display_name(agent_type: str) -> str:
    """Get display name for agent type."""
    agent_names = {
        "savings": "Savings Agent",
        "products": "Products Agent",
        "principal": "Principal Agent",
        "homebuying": "Home Buying Agent",
    }
    return agent_names.get(agent_type, agent_type.title())


def is_multi_turn_evaluation(result_dir: str) -> bool:
    """Determine if this is a multi-turn evaluation based on directory name.

    Multi-turn evaluations use directory names with '_multi_turn' suffix,
    as created by the _create_run_dir_suffix() function in gha_entrypoints.py.

    Args:
        result_dir: The result directory name (e.g., "run_20251106_073943_products_multi_turn")

    Returns:
        True if this is a multi-turn evaluation, False otherwise
    """
    return "_multi_turn" in result_dir


def is_multi_turn_overall_analysis(overall_analysis: dict[str, Any] | None) -> bool:
    """Determine if the overall analysis contains multi-turn data.

    Multi-turn overall analysis files are named 'overall_analysis_results_multi.json'
    and may contain evaluation_type field set to 'multi_turn'.

    Args:
        overall_analysis: The overall analysis dictionary

    Returns:
        True if this contains multi-turn analysis, False otherwise
    """
    if not overall_analysis:
        return False

    # Check if evaluation_type is explicitly set to multi_turn
    evaluation_type = overall_analysis.get("evaluation_type", "")
    return bool(evaluation_type == "multi_turn")


def format_multi_turn_overall_analysis(overall_analysis: dict[str, Any], run_id: str, formatted_time: str) -> str:
    """Format multi-turn overall analysis results for the All Agents section."""
    # Extract overall metrics from base_analysis
    base_analysis = overall_analysis.get("base_analysis", {})
    overall = base_analysis.get("overall_metrics", {})

    markdown = f"""
<details markdown="1">
<summary>🔄 Multi-Turn Run {run_id} - {formatted_time} ({overall.get("total_conversations", 0)} conversations)</summary>

## 📊 Multi-Turn Performance Metrics

| Metric | Value |
|:-------|------:|
| **Average Score** | {overall.get("average_score", 0):.3f} |
| **Pass Rate** | {(overall.get("pass_rate", 0) * 100):.1f}% |
| **Total Conversations** | {overall.get("total_conversations", 0):,} |
| **Total Evaluations** | {overall.get("total_evaluations", 0):,} ({overall.get("total_conversations", 0):,} conversations x {overall.get("number_of_judges", 0)} judges) |
| **Valid Evaluations** | {overall.get("valid_evaluations", 0):,} ({(overall.get("valid_evaluations", 0) / overall.get("total_evaluations", 1) * 100):.1f}%) |
| **Invalid Evaluations** | {overall.get("invalid_evaluations", 0):,} ({(overall.get("invalid_evaluations", 0) / overall.get("total_evaluations", 1) * 100):.1f}%) |

{format_judge_performance_table_from_json(overall_analysis)}
{create_detailed_judge_analysis_from_json(overall_analysis)}
</details>
"""
    return markdown


def create_multi_turn_result_section(result: dict[str, Any], result_type: str | None = None) -> str:
    """Create a collapsible section for a single multi-turn evaluation result."""
    report = result["report"]
    summary = result["summary"]
    result_dir = result["dir"]

    # Extract key information
    run_id = report.get("run_id", result_dir)
    timestamp = report.get("timestamp", "Unknown")
    total_conversations = report.get("total_conversations", 0)
    overall_metrics = report.get("summary", {}).get("overall_metrics", {})
    guardrail_summary = report.get("guardrail_summary", {})

    # Format timestamp
    formatted_time = format_time_from_timestamp(timestamp)

    # Build section content using unified JSON approach
    type_label = ""
    if result_type == "single-turn":
        type_label = " (Single-turn)"
    elif result_type == "multi-turn":
        type_label = " (Multi-turn)"

    content = f"""<details markdown="1">
<summary>Run {run_id} - {formatted_time} ({total_conversations} conversations){type_label}</summary>

#### Multi-Turn Performance

| Metric | Value |
|:-------|------:|
| Average Score | {overall_metrics.get("average_score", 0):.3f} |
| Pass Rate | {(overall_metrics.get("pass_rate", 0) * 100):.1f}% |
| Pass Threshold | {overall_metrics.get("pass_threshold", 0.7):.1f} |
| Min Score | {overall_metrics.get("min_score", 0):.3f} |
| Max Score | {overall_metrics.get("max_score", 0):.3f} |

{format_judge_performance_table_from_json(report)}
{create_detailed_judge_analysis_from_json(report)}
{format_guardrail_metrics(guardrail_summary)}
{format_summary_and_recommendations(summary)}
</details>

"""

    return content


def extract_date_from_result(result_dir: str, report: dict[str, Any]) -> str:
    """Extract date from result directory or report timestamp, converting UTC to AEDT."""
    if report.get("timestamp"):
        try:
            # Parse UTC timestamp and convert to AEDT
            utc_dt = datetime.fromisoformat(report["timestamp"].replace("Z", "+00:00"))
            aedt_dt = utc_dt.astimezone(ZoneInfo("Australia/Sydney"))
            return aedt_dt.date().isoformat()
        except (ValueError, TypeError):
            pass

    # Extract date from directory name (format: run_YYYYMMDD_HHMMSS)
    date_match = re.search(r"(\d{8})", result_dir)
    if date_match:
        date_str = date_match.group(1)
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return "Unknown"


def format_time_from_timestamp(timestamp: str) -> str:
    """Format time from timestamp string, converting from UTC to AEDT."""
    if not timestamp or timestamp == "Unknown":
        return "Unknown"
    try:
        # Parse UTC timestamp
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        # If the datetime is naive (no timezone), assume it's UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        # Convert to Australia/Sydney timezone
        aedt_dt = dt.astimezone(ZoneInfo("Australia/Sydney"))
        # Format with actual timezone abbreviation
        return aedt_dt.strftime("%H:%M %Z")
    except (ValueError, TypeError):
        return "Unknown"


def find_artifact_results(
    artifacts_dir: Path,
) -> tuple[dict[str, list[dict[str, Any]]] | None, list[Path]]:
    """Find evaluation results from downloaded artifacts."""
    logger.info(f"🔍 Scanning for evaluation results in artifacts at {artifacts_dir}...")

    # Debug: List all files in artifacts directory
    logger.info("Debug: Listing all files in artifacts directory:")
    for file_path in artifacts_dir.rglob("*"):
        if file_path.is_file():
            logger.info(f"  Found file: {file_path.relative_to(artifacts_dir)}")

    if not artifacts_dir.exists():
        logger.info("❌ Artifacts directory not found")
        return None, []

    # Find the eval-results directory structure
    # Pattern: eval-results-*-<date>/evals/financial_companion_eval/results/
    eval_results_dirs = list(artifacts_dir.glob("evals"))

    if not eval_results_dirs:
        logger.info("❌ No eval-results directories found in artifacts")
        return None, []

    logger.info(f"Found {len(eval_results_dirs)} eval-results directories")

    # Look for the results path within each eval-results directory
    all_results = []
    latency_plots = []

    for eval_dir in eval_results_dirs:
        results_path = eval_dir / "financial_companion_eval" / "results"

        if not results_path.exists():
            logger.info(f"⚠️  Results path not found in {eval_dir.name}")
            continue

        # Check for latency.png at the results directory level (generated by combined plots)
        latency_plot = results_path / "latency.png"
        if latency_plot.exists():
            latency_plots.append(latency_plot)
            logger.info(f"📊 Found latency plot: {latency_plot}")
        else:
            logger.info(f"⚠️  No latency plot found at: {latency_plot}")
            # Check if there are any PNG files at this level
            png_files = list(results_path.glob("*.png"))
            if png_files:
                logger.info(f"  Found other PNG files: {[f.name for f in png_files]}")
            else:
                logger.info("  No PNG files found in results directory")

        # Find all run directories
        run_dirs = [d for d in results_path.iterdir() if d.is_dir() and d.name.startswith("run_")]

        if not run_dirs:
            logger.info(f"⚠️  No run directories found in {eval_dir.name}")
            continue

        logger.info(f"Found {len(run_dirs)} run directories in {eval_dir.name}")

        for run_dir in run_dirs:
            report_path = run_dir / "eval_report.json"

            if not report_path.exists():
                logger.info(f"⚠️  No eval_report.json found in {run_dir.name}")
                continue

            try:
                with open(report_path, encoding="utf-8") as f:
                    report = json.load(f)

                # Load summary if available
                summary_path = run_dir / "llm_summary.json"
                summary = None
                if summary_path.exists():
                    try:
                        with open(summary_path, encoding="utf-8") as f:
                            summary = json.load(f)
                    except (OSError, json.JSONDecodeError) as e:
                        logger.info(f"⚠️  Could not parse summary for {run_dir.name}: {e}")

                run_date = extract_date_from_result(run_dir.name, report)

                all_results.append(
                    {
                        "dir": run_dir.name,
                        "report": report,
                        "summary": summary,
                        "date": run_date,
                        "artifact_dir": eval_dir.name,
                    }
                )

                # Note: latency.png is checked at results directory level, not per run

            except (OSError, json.JSONDecodeError) as e:
                logger.info(f"❌ Error processing {run_dir.name}: {e}")

    if not all_results:
        logger.info("❌ No evaluation results found in artifacts")
        return None, latency_plots

    logger.info(f"📊 Summary: Found {len(latency_plots)} latency plots total")
    for plot in latency_plots:
        logger.info(f"  Latency plot: {plot}")

    # Group by date and find the most recent
    results_by_date: dict[str, list[dict[str, Any]]] = {}
    for result in all_results:
        date = result["date"]
        if date not in results_by_date:
            results_by_date[date] = []
        results_by_date[date].append(result)

    # Get the most recent date
    most_recent_date = max(results_by_date.keys())
    most_recent_results = results_by_date[most_recent_date]

    logger.info(f"📊 Returning {len(latency_plots)} latency plots")
    logger.info(f"📊 Found {len(most_recent_results)} results from {most_recent_date}")
    for i in most_recent_results:
        logger.info(f"  Result: {i['dir']}")
    return {most_recent_date: most_recent_results}, latency_plots


def format_judge_performance_table_from_json(report: dict[str, Any]) -> str:
    """Format judge performance data from JSON report (unified approach for both individual and All Agents)."""
    # Get new format data (priority_level_summary and judge_performance_by_priority)
    priority_summary = report.get("priority_level_summary")
    judge_performance_by_priority = report.get("judge_performance_by_priority")

    if priority_summary and judge_performance_by_priority:
        # Use new format data directly from JSON
        return format_priority_data_from_json(priority_summary, judge_performance_by_priority)

    return ""


def format_priority_data_from_json(
    priority_summary: dict[str, Any], judge_performance_by_priority: dict[str, Any]
) -> str:
    """Format priority data directly from JSON (new format)."""
    content = "\n#### 📊 Judge Performance by Priority\n\n"

    # Priority Level Summary
    content += "##### Priority Level Summary\n\n"
    content += "| Priority | Avg Score | Pass Rate | Status |\n"
    content += "|:---------|----------:|----------:|:------:|\n"

    priority_mapping = {
        "high_priority": "HIGH",
        "medium_priority": "MEDIUM",
        "low_priority": "LOW",
    }

    for priority_key, priority_display in priority_mapping.items():
        if priority_key in priority_summary:
            metrics = priority_summary[priority_key]
            avg_score = metrics.get("average_score", 0)
            pass_rate = metrics.get("pass_rate", 0)
            status = metrics.get("status", "UNKNOWN")

            content += f"| **{priority_display}** | {avg_score:.3f} | {(pass_rate * 100):.1f}% | {status} |\n"

    content += "\n"

    # Detailed judge tables by priority
    priority_emojis = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}

    for priority_key, priority_display in priority_mapping.items():
        if priority_key in judge_performance_by_priority:
            judges_data = judge_performance_by_priority[priority_key]
            if judges_data and "judges" in judges_data:
                emoji = priority_emojis.get(priority_display, "")
                content += create_judge_table_from_json(judges_data["judges"], priority_display, emoji)

    return content


def create_judge_table_from_json(judges_data: dict[str, Any], title: str, priority_emoji: str) -> str:
    """Create judge performance table for a priority level from JSON data."""
    if not judges_data:
        return ""

    table = f"\n##### {priority_emoji} {title} PRIORITY JUDGES\n\n"
    table += "| Judge | Avg Score | Pass Rate | Successful Runs | Invalid Runs | Status |\n"
    table += "|:------|----------:|----------:|----------------:|-------------:|:------:|\n"

    for judge_name, judge_data in judges_data.items():
        display_name = judge_name.replace("_", " ").title()
        avg_score = f"{judge_data.get('average_score', 0):.3f}"
        pass_rate = f"{(judge_data.get('pass_rate', 0) * 100):.1f}%"
        successful_runs = judge_data.get("successful_runs", 0)
        invalid_runs = judge_data.get("invalid_runs", 0)
        status = judge_data.get("status", "UNKNOWN")

        table += f"| {display_name} | {avg_score} | {pass_rate} | {successful_runs} | {invalid_runs} | {status} |\n"

    return table + "\n"


def format_guardrail_metrics(guardrail_summary: dict[str, Any]) -> str:
    """Format guardrail metrics as a markdown section."""
    if not guardrail_summary:
        return ""

    total_convs = guardrail_summary.get("total_conversations", 0)
    guardrails_triggered = guardrail_summary.get("guardrails_triggered", 0)
    successful_rewrites = (
        guardrail_summary.get("rewrite_attempt_1", 0)
        + guardrail_summary.get("rewrite_attempt_2", 0)
        + guardrail_summary.get("rewrite_attempt_3", 0)
    )
    fallback_responses = guardrail_summary.get("fallback_responses", 0)

    guardrails_pct = (guardrails_triggered / total_convs * 100) if total_convs > 0 else 0
    rewrites_pct = (successful_rewrites / guardrails_triggered * 100) if guardrails_triggered > 0 else 0
    fallback_pct = (fallback_responses / guardrails_triggered * 100) if guardrails_triggered > 0 else 0

    return f"""
#### Guardrail Metrics

| Metric | Value | Percentage |
|:-------|------:|-----------:|
| Total Conversations | {total_convs} | 100.0% |
| Guardrails Triggered | {guardrails_triggered} | {guardrails_pct:.1f}% |
| Successful Rewrites | {successful_rewrites} | {rewrites_pct:.1f}% |
| Fallback Responses | {fallback_responses} | {fallback_pct:.1f}% |

"""


def format_summary_and_recommendations(summary: dict[str, Any] | None) -> str:
    """Format executive summary and recommendations."""
    if not summary:
        return ""

    content = ""

    if summary.get("summary"):
        content += f"""
#### Executive Summary

{summary["summary"]}
"""

    if summary.get("recommendations"):
        content += """
#### Recommendations

"""
        for i, rec in enumerate(summary["recommendations"], 1):
            content += f"{i}. {rec}\n"

    return content


def format_full_summary_json(summary: dict[str, Any] | None, result_type_label: str | None = None) -> str:
    """Format the complete LLM summary JSON as a collapsible section."""
    if not summary:
        return ""

    # Pretty-print the JSON with proper indentation
    json_content = json.dumps(summary, indent=2, ensure_ascii=False)

    title_suffix = f" ({result_type_label})" if result_type_label else ""

    return f"""
<details markdown="1">
<summary>📋 Key Issues Summary - JSON{title_suffix}</summary>

```json
{json_content}
```

</details>

"""


def create_result_section(result: dict[str, Any], result_type: str | None = None) -> str:
    """Create a collapsible section for a single evaluation result."""
    report = result["report"]
    summary = result["summary"]
    result_dir = result["dir"]

    # Extract key information
    run_id = report.get("run_id", result_dir)
    timestamp = report.get("timestamp", "Unknown")
    total_conversations = report.get("total_conversations", 0)
    overall_metrics = report.get("summary", {}).get("overall_metrics", {})
    guardrail_summary = report.get("guardrail_summary", {})

    # Format timestamp
    formatted_time = format_time_from_timestamp(timestamp)

    # Build section content using unified JSON approach
    type_label = ""
    if result_type == "single-turn":
        type_label = " (Single-turn)"
    elif result_type == "multi-turn":
        type_label = " (Multi-turn)"

    content = f"""<details markdown="1">
<summary>Run {run_id} - {formatted_time} ({total_conversations} conversations){type_label}</summary>

#### Overall Performance

| Metric | Value |
|:-------|------:|
| Average Score | {overall_metrics.get("average_score", 0):.3f} |
| Pass Rate | {(overall_metrics.get("pass_rate", 0) * 100):.1f}% |
| Pass Threshold | {overall_metrics.get("pass_threshold", 0.7):.1f} |
| Min Score | {overall_metrics.get("min_score", 0):.3f} |
| Max Score | {overall_metrics.get("max_score", 0):.3f} |

{format_judge_performance_table_from_json(report)}
{create_detailed_judge_analysis_from_json(report)}
{format_guardrail_metrics(guardrail_summary)}
{format_summary_and_recommendations(summary)}
</details>

"""

    return content


def copy_latency_plots(latency_plots: list[Path], output_file: Path, run_date: str) -> list[str]:
    """Copy latency plots to the docs directory and return relative paths."""
    logger.info(f"📊 Starting copy_latency_plots with {len(latency_plots)} plots")
    if not latency_plots:
        logger.info("⚠️  No latency plots to copy")
        return []

    # Create images directory relative to the output file
    docs_dir = output_file.parent
    images_dir = docs_dir / "images" / "eval-results"
    images_dir.mkdir(parents=True, exist_ok=True)

    copied_plots = []

    for plot_path in latency_plots:
        # Create a unique filename with date and run info
        plot_filename = f"latency-{run_date}-{plot_path.parent.name}.png"
        dest_path = images_dir / plot_filename

        try:
            shutil.copy2(plot_path, dest_path)
            # Return relative path from the markdown file
            relative_path = f"images/eval-results/{plot_filename}"
            copied_plots.append(relative_path)
            logger.info(f"📊 Copied latency plot: {plot_path} -> {dest_path}")
        except Exception:
            logger.exception(f"❌ Failed to copy latency plot {plot_path}")

    return copied_plots


def convert_analysis_results_to_markdown(analysis_results: dict[str, Any], run_id: str, formatted_time: str) -> str:
    """Convert analysis results dict to Confluence-compatible markdown format (unified approach)."""
    # Extract overall metrics from base_analysis
    base_analysis = analysis_results.get("base_analysis", {})
    overall = base_analysis.get("overall_metrics", {})

    markdown = f"""
<details markdown="1">
<summary>Run {run_id} - {formatted_time} ({overall.get("total_conversations", 0)} conversations)</summary>

## 📊 Core Performance Metrics

| Metric | Value |
|:-------|------:|
| **Average Score** | {overall.get("average_score", 0):.3f} |
| **Pass Rate** | {(overall.get("pass_rate", 0) * 100):.1f}% |
| **Total Conversations** | {overall.get("total_conversations", 0):,} |
| **Total Evaluations** | {overall.get("total_evaluations", 0):,} ({overall.get("total_conversations", 0):,} conversations x {overall.get("number_of_judges", 0)} judges) |
| **Valid Evaluations** | {overall.get("valid_evaluations", 0):,} ({(overall.get("valid_evaluations", 0) / overall.get("total_evaluations", 1) * 100):.1f}%) |
| **Invalid Evaluations** | {overall.get("invalid_evaluations", 0):,} ({(overall.get("invalid_evaluations", 0) / overall.get("total_evaluations", 1) * 100):.1f}%) |

{format_judge_performance_table_from_json(analysis_results)}
{create_detailed_judge_analysis_from_json(analysis_results)}
</details>
"""
    return markdown


def create_detailed_judge_analysis_from_json(analysis_results: dict[str, Any]) -> str:
    """Create detailed judge analysis from JSON data (unified approach)."""
    # Try to get new format data first
    judge_performance_by_priority = analysis_results.get("judge_performance_by_priority")

    if judge_performance_by_priority:
        return create_detailed_analysis_from_priority_data(judge_performance_by_priority)
    return ""


def create_detailed_analysis_from_priority_data(
    judge_performance_by_priority: dict[str, Any],
) -> str:
    """Create detailed analysis from new priority format."""
    content = ""
    priority_emojis = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
    priority_mapping = {
        "high_priority": "HIGH",
        "medium_priority": "MEDIUM",
        "low_priority": "LOW",
    }

    for priority_key, priority_display in priority_mapping.items():
        if priority_key in judge_performance_by_priority:
            judges_data = judge_performance_by_priority[priority_key]
            if judges_data and "judges" in judges_data:
                emoji = priority_emojis.get(priority_display, "")
                content += create_detailed_priority_section(judges_data["judges"], priority_display, emoji)

    return content


def create_detailed_priority_section(judges_data: dict[str, Any], priority_name: str, priority_emoji: str) -> str:
    """Create detailed section for a priority level from JSON data."""
    section = f"## {priority_emoji} {priority_name} PRIORITY JUDGES\n\n"
    section += "### Detailed Judge Analysis\n\n"

    for judge_name, judge_data in judges_data.items():
        display_name = judge_name.replace("_", " ").title()
        status = judge_data.get("status", "UNKNOWN")

        section += f"#### {display_name} {status}\n\n"
        section += "**Performance Metrics:**\n"
        section += f"- Average Score: {judge_data.get('average_score', 0):.3f}\n"
        section += f"- Pass Rate: {(judge_data.get('pass_rate', 0) * 100):.1f}% (threshold: {judge_data.get('pass_threshold', 0)})\n"
        section += f"- Runs: {judge_data.get('successful_runs', 0)} successful / {judge_data.get('invalid_runs', 0)} invalid / {judge_data.get('total_runs', 0)} total\n"
        section += f"- Invalid Rate: {(judge_data.get('invalid_rate', 0) * 100):.1f}%\n\n"

        # Route breakdown if available
        if judge_data.get("route_breakdown"):
            section += "**Route Performance Breakdown:**\n\n"
            section += "| Route | Runs | Score | Pass Rate |\n"
            section += "|:------|-----:|------:|----------:|\n"
            for route in judge_data["route_breakdown"]:
                route_score = route.get("average_score", 0)
                route_pass = route.get("pass_rate_pct", 0)

                # Add status indicators
                if route_score >= 0.8:
                    score_status = f"🟢 {route_score:.3f}"
                elif route_score >= 0.6:
                    score_status = f"🟡 {route_score:.3f}"
                else:
                    score_status = f"🔴 {route_score:.3f}"

                if route_pass >= 80:
                    pass_status = f"🟢 {route_pass:.1f}%"
                elif route_pass >= 60:
                    pass_status = f"🟡 {route_pass:.1f}%"
                else:
                    pass_status = f"🔴 {route_pass:.1f}%"

                section += (
                    f"| {route.get('route', 'Unknown')} | {route.get('count', 0)} | {score_status} | {pass_status} |\n"
                )
            section += "\n"

        # Advice breakdown if available
        if judge_data.get("advice_breakdown"):
            section += "**Financial Advice Performance Breakdown:**\n\n"
            section += "| Advice Type | Runs | Score | Pass Rate |\n"
            section += "|:------------|-----:|------:|----------:|\n"
            for advice in judge_data["advice_breakdown"]:
                advice_score = advice.get("average_score", 0)
                advice_pass = advice.get("pass_rate_pct", 0)

                # Add status indicators
                if advice_score >= 0.8:
                    score_status = f"🟢 {advice_score:.3f}"
                elif advice_score >= 0.6:
                    score_status = f"🟡 {advice_score:.3f}"
                else:
                    score_status = f"🔴 {advice_score:.3f}"

                if advice_pass >= 80:
                    pass_status = f"🟢 {advice_pass:.1f}%"
                elif advice_pass >= 60:
                    pass_status = f"🟡 {advice_pass:.1f}%"
                else:
                    pass_status = f"🔴 {advice_pass:.1f}%"

                section += f"| {advice.get('advice_type', 'Unknown')} | {advice.get('count', 0)} | {score_status} | {pass_status} |\n"
            section += "\n"

        # Invalid reasoning breakdown
        if judge_data.get("invalid_runs", 0) > 0:
            section += "**Invalid Run Analysis:**\n\n"
            if judge_data.get("invalid_reasoning_summary"):
                if len(judge_data["invalid_reasoning_summary"]) == 1:
                    reason, percentage = next(iter(judge_data["invalid_reasoning_summary"].items()))
                    section += f"- {reason} ({percentage}%)\n\n"
                else:
                    section += "Multiple failure reasons:\n\n"
                    for (
                        reason,
                        percentage,
                    ) in judge_data["invalid_reasoning_summary"].items():
                        section += f"- {reason}: {percentage}%\n"
                    section += "\n"
            else:
                section += f"- {judge_data.get('invalid_runs', 0)} invalid runs (no reasoning available)\n\n"

    return section


def generate_new_results_section(
    results_by_date: dict[str, list[dict[str, Any]]],
    latency_plot_paths: list[str] | None = None,
    overall_analysis: dict[str, Any] | None = None,
    multi_turn_overall_analysis: dict[str, Any] | None = None,
    result_type: str | None = None,
) -> str:
    """Generate markdown content for the new results section only."""
    if not results_by_date:
        return ""

    content = ""

    # Should only be one date (most recent)
    for run_date, date_results in results_by_date.items():
        content += f"## {run_date} Evaluation Run\n\n"

        # Add latency plots if available
        if latency_plot_paths:
            content += "### 📊 Agent Performance Metrics\n\n"
            content += "The following charts show agent performance metrics including latency, token usage, and error rates:\n\n"
            for plot_path in latency_plot_paths:
                content += f'![Agent Latency Performance - {run_date}]({plot_path} "Agent performance metrics including latency breakdown by agent")\n\n'
            content += "---\n\n"

        # Overall analysis
        formatted_time = format_time_from_timestamp(date_results[0]["report"].get("timestamp", "Unknown"))
        run_id = date_results[0]["report"].get("run_id", "Unknown")

        # Single-turn overall analysis
        if overall_analysis and result_type == "single-turn":
            content += "### All Agents\n\n"
            content += convert_analysis_results_to_markdown(overall_analysis, run_id, formatted_time)
            content += "---\n\n"

        # Multi-turn overall analysis
        if multi_turn_overall_analysis and result_type == "multi-turn":
            content += "### All Agents\n\n"
            content += format_multi_turn_overall_analysis(multi_turn_overall_analysis, run_id, formatted_time)
            content += "---\n\n"

        # Separate single-turn and multi-turn results
        single_turn_results = []
        multi_turn_results = []

        for result in date_results:
            if is_multi_turn_evaluation(result["dir"]):
                multi_turn_results.append(result)
            else:
                single_turn_results.append(result)

        # Group single-turn results by agent type (only if we're processing single-turn or all)
        agent_results: dict[str, list[dict[str, Any]]] = {}
        if result_type == "single-turn":
            for result in single_turn_results:
                agent_type = extract_agent_type(result["dir"])
                if agent_type not in agent_results:
                    agent_results[agent_type] = []
                agent_results[agent_type].append(result)

        # Group multi-turn results by agent type (only if we're processing multi-turn or all)
        multi_turn_agent_results: dict[str, list[dict[str, Any]]] = {}
        if result_type == "multi-turn":
            for result in multi_turn_results:
                agent_type = extract_agent_type(result["dir"])
                if agent_type not in multi_turn_agent_results:
                    multi_turn_agent_results[agent_type] = []
                multi_turn_agent_results[agent_type].append(result)

        # Define the desired order for agent types
        agent_order = ["principal", "homebuying", "products", "savings"]

        # Create sections for each agent type that has results in the specified order
        for agent_type in agent_order:
            if agent_type not in agent_results and agent_type not in multi_turn_agent_results:
                continue

            agent_display_name = get_agent_display_name(agent_type)
            content += f"### {agent_display_name}\n\n"

            # Add single-turn results first (only if we're processing single-turn or all)
            if result_type != "multi-turn" and agent_type in agent_results:
                results = agent_results[agent_type]
                for result in results:
                    content += create_result_section(result, result_type)
                    # Add JSON summary for single-turn immediately after the result
                    if result_type == "single-turn":
                        content += format_full_summary_json(result.get("summary"), "Single-turn")
                    else:
                        content += format_full_summary_json(result.get("summary"))

            # Add multi-turn results underneath (only if we're processing multi-turn or all)
            if result_type != "single-turn" and agent_type in multi_turn_agent_results:
                multi_results = multi_turn_agent_results[agent_type]
                for result in multi_results:
                    content += create_multi_turn_result_section(result, result_type)
                    # Add JSON summary for multi-turn immediately after the result
                    if result_type == "multi-turn":
                        content += format_full_summary_json(result.get("summary"), "Multi-turn")
                    else:
                        content += format_full_summary_json(result.get("summary"))

            content += "---\n\n"

    return content


def update_existing_markdown(
    output_file: Path,
    new_content: str,
    artifacts_dir: str,
    result_type: str | None = None,
) -> str:
    """Update existing markdown file by prepending new results."""
    # Read run info if available
    run_info_path = Path(artifacts_dir) / "run_info.json"
    run_info_text = ""
    if run_info_path.exists():
        try:
            with open(run_info_path, encoding="utf-8") as f:
                run_info = json.load(f)
            run_info_text = f" (from [workflow run {run_info['run_id']}]({run_info['run_url']}))"
        except (OSError, json.JSONDecodeError):
            pass

    # Generate appropriate header based on result type
    if result_type == "single-turn":
        title = "Single Turn Evaluation Results"
        description = "This document contains the latest single-turn evaluation results for the Financial Companion Agent system. Results are automatically updated daily at 7:30 AM UTC (6:30 PM Sydney time) from scheduled single-turn evaluation workflow runs."
        navigation = "**Navigation:** [← Back to Daily Eval Results](eval-results.md) | [Multi Turn Results →](eval-results-multi-turn.md)"
    elif result_type == "multi-turn":
        title = "Multi Turn Evaluation Results"
        description = "This document contains the latest multi-turn evaluation results for the Financial Companion Agent system. Results are automatically updated daily at 8:00 AM UTC (7:00 PM Sydney time) from scheduled multi-turn evaluation workflow runs."
        navigation = "**Navigation:** [← Back to Daily Eval Results](eval-results.md) | [← Single Turn Results](eval-results-single-turn.md)"
    else:
        title = "Financial Companion Agent Evaluation Results"
        description = "This document contains the latest evaluation results for the Financial Companion Agent system. Results are automatically updated daily at 8:00 PM Sydney time from scheduled evaluation workflow runs."
        navigation = ""

    header = f"""---
hide:
  - toc
---
# {title}

{description}

{navigation}

**Last Updated:** {datetime.now().date().isoformat()}{run_info_text}

---

"""

    footer = f"""
## About This Report

This report is automatically generated from evaluation results downloaded from GitHub Actions workflow artifacts. Each evaluation run tests the Financial Companion Agent system against a comprehensive set of test cases using multiple judges to assess performance across various dimensions including:

- **Golden Answer Alignment**: How well responses match expected reference answers
- **Tool Output Faithfulness**: Accuracy of information derived from tool outputs
- **Response Relevancy**: Relevance and appropriateness of responses to user queries
- **Tone & Style**: Professional communication standards and consistency
- **UI Components**: Accuracy and completeness of user interface elements
- **Guardrails**: Compliance with safety and regulatory requirements

For detailed raw results, see the workflow artifacts in the [GitHub Actions runs](https://github.com/repository/actions/workflows/run-evals.yaml).

---
*Last generated: {datetime.now(ZoneInfo("Australia/Sydney")).isoformat()}*
"""

    existing_content = ""
    if output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            existing_content = f.read()

        # Extract existing results (everything between the first --- after header and "## About This Report")
        lines = existing_content.split("\n")
        in_results_section = False
        existing_results = []

        for line in lines:
            if line.strip() == "---" and not in_results_section:
                in_results_section = True
                continue
            elif line.strip().startswith("## About This Report"):
                break
            elif in_results_section:
                existing_results.append(line)

        existing_results_content = "\n".join(existing_results).strip()
        if existing_results_content:
            existing_results_content = existing_results_content + "\n\n"
    else:
        existing_results_content = ""

    # Combine header + new results + existing results + footer
    return header + new_content + existing_results_content + footer


def main() -> int:
    """Main function to update evaluation results documentation."""
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Update evaluation results documentation with most recent results from artifacts"
    )
    parser.add_argument("--artifacts-dir", required=True, help="Path to downloaded artifacts directory")
    parser.add_argument(
        "--output-file",
        default="docs/project-management/eval-results.md",
        help="Path to output markdown file",
    )
    parser.add_argument(
        "--result-type",
        choices=["single-turn", "multi-turn"],
        help="Type of evaluation results to process (single-turn or multi-turn). If not specified, processes all results.",
    )

    args = parser.parse_args()

    # Convert paths to Path objects
    artifacts_dir = Path(args.artifacts_dir)
    output_file = Path(args.output_file)

    # Find evaluation results from artifacts
    recent_results, latency_plots = find_artifact_results(artifacts_dir)

    if not recent_results:
        logger.info("❌ No recent evaluation results found in artifacts")
        return 1

    # Filter results based on result type if specified
    if args.result_type:
        filtered_results = {}
        for date, results in recent_results.items():
            filtered_date_results = []
            for result in results:
                is_multi_turn = is_multi_turn_evaluation(result["dir"])
                if (args.result_type == "multi-turn" and is_multi_turn) or (
                    args.result_type == "single-turn" and not is_multi_turn
                ):
                    filtered_date_results.append(result)

            if filtered_date_results:
                filtered_results[date] = filtered_date_results

        recent_results = filtered_results

        if not recent_results:
            logger.info(f"❌ No {args.result_type} evaluation results found in artifacts")
            return 1

        logger.info(f"📊 Filtered to {args.result_type} results only")

    # Copy latency plots to docs directory
    if args.result_type == "single-turn":
        run_date = next(iter(recent_results.keys()))
        logger.info(f"📊 About to copy {len(latency_plots)} latency plots for date {run_date}")
        latency_plot_paths = copy_latency_plots(latency_plots, output_file, run_date)
        logger.info(f"📊 Successfully copied plots, got {len(latency_plot_paths)} paths")
    else:
        logger.info(f"📊 No latency plots to copy for {args.result_type} results")
        latency_plot_paths = []

    # Look for overall analysis results JSON files (both single-turn and multi-turn)
    logger.info("🎯 Looking for overall analysis results...")
    overall_analysis = None
    multi_turn_overall_analysis = None

    # Look for both single-turn and multi-turn overall analysis files in results/all/
    for eval_dir in artifacts_dir.glob("evals"):
        results_path = eval_dir / "financial_companion_eval" / "results" / "all"

        # Single-turn analysis file
        analysis_file = results_path / "overall_analysis_results.json"
        if analysis_file.exists():
            try:
                with open(analysis_file, encoding="utf-8") as f:
                    overall_analysis = json.load(f)
                logger.info("✅ Single-turn overall analysis results loaded successfully")
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"⚠️  Could not load single-turn overall analysis results: {e}")

        # Multi-turn analysis file
        multi_analysis_file = results_path / "overall_analysis_results_multi.json"
        if multi_analysis_file.exists():
            try:
                with open(multi_analysis_file, encoding="utf-8") as f:
                    multi_turn_overall_analysis = json.load(f)
                logger.info("✅ Multi-turn overall analysis results loaded successfully")
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"⚠️  Could not load multi-turn overall analysis results: {e}")

    if not overall_analysis and not multi_turn_overall_analysis:
        logger.warning("⚠️  No overall analysis results found")
    elif not overall_analysis:
        logger.warning("⚠️  No single-turn overall analysis results found")
    elif not multi_turn_overall_analysis:
        logger.warning("⚠️  No multi-turn overall analysis results found")

    # Generate new results section
    logger.info("📝 Generating new results section...")
    logger.info(f"📊 Including {len(latency_plot_paths)} latency plot paths in content")
    new_results_content = generate_new_results_section(
        recent_results,
        latency_plot_paths,
        overall_analysis,
        multi_turn_overall_analysis,
        args.result_type,
    )

    if not new_results_content.strip():
        logger.info("❌ No content generated from recent results")
        return 1

    # Update existing markdown file
    logger.info("📝 Updating existing markdown file...")
    updated_content = update_existing_markdown(output_file, new_results_content, args.artifacts_dir, args.result_type)

    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write the updated content
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(updated_content)

    total_results = sum(len(results) for results in recent_results.values())
    run_date = next(iter(recent_results.keys()))

    logger.info(f"✅ Prepended {total_results} new evaluation results from {run_date} to {output_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
