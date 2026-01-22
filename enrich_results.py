"""Enrich results JSON with display-friendly fields and corrected avg_difficulty.

This script post-processes the output/results.json file to:
1. Add display-friendly computed fields for clearer leaderboard presentation
2. Recompute avg_difficulty using predefined task difficulty scores

Usage:
    python enrich_results.py output/results.json
    python enrich_results.py output/results.json --difficulty-file custom_difficulty.json
"""

import argparse
import json
import sys
from pathlib import Path


DEFAULT_DIFFICULTY_FILE = Path(__file__).parent / "task_difficulty.json"


def load_task_difficulty(difficulty_file: Path) -> dict[str, dict[str, float]]:
    """Load task difficulty scores from JSON file.

    Args:
        difficulty_file: Path to task_difficulty.json.

    Returns:
        Dict mapping domain -> task_id -> difficulty score.
    """
    data = json.loads(difficulty_file.read_text())
    # Filter out _meta key if present
    return {k: v for k, v in data.items() if not k.startswith("_")}


def compute_avg_difficulty(
    task_results: list[dict],
    task_difficulty_map: dict[str, float],
    default_difficulty: float = 0.5,
) -> float:
    """Compute weighted average difficulty of passed tasks.

    Args:
        task_results: List of task result dicts with 'task_id' and 'reward' fields.
        task_difficulty_map: Dict mapping task_id (str) to difficulty score (0.0-1.0).
        default_difficulty: Default difficulty for tasks not in the map.

    Returns:
        Average difficulty score of successful tasks (reward > 0).
    """
    total_weight = 0.0
    weighted_sum = 0.0

    for result in task_results:
        # Check if task was successful (reward > 0)
        reward = result.get("reward", 0)
        if reward > 0:
            task_id = str(result.get("task_id", ""))
            difficulty = task_difficulty_map.get(task_id, default_difficulty)
            weighted_sum += difficulty
            total_weight += 1.0

    return weighted_sum / total_weight if total_weight > 0 else 0.0


def enrich_summary(
    summary: dict,
    task_results: list[dict],
    task_difficulty_map: dict[str, float],
) -> dict:
    """Add display-friendly fields to summary.

    Args:
        summary: Original summary dict from results JSON.
        task_results: List of task result dicts.
        task_difficulty_map: Dict mapping task_id to difficulty score.

    Returns:
        Enriched summary dict with display fields and corrected avg_difficulty.
    """
    total_tasks = summary.get("total_tasks", 0)
    num_trials = summary.get("num_trials", 1)
    total_simulations = summary.get("total_simulations", total_tasks * num_trials)
    successful_simulations = summary.get("successful_simulations", 0)
    avg_reward = summary.get("avg_reward", 0)
    pass_hat_k = summary.get("pass_hat_k", {})

    # Recompute avg_difficulty using task difficulty scores
    corrected_avg_difficulty = compute_avg_difficulty(task_results, task_difficulty_map)

    # Calculate display percentages
    pass_rate_pct = round((successful_simulations / total_simulations * 100), 1) if total_simulations > 0 else 0
    pass_at_1_pct = round(pass_hat_k.get("1", 0) * 100, 1) if pass_hat_k else round(avg_reward * 100, 1)
    pass_at_2_pct = round(pass_hat_k.get("2", 0) * 100, 1) if pass_hat_k else 0

    # Create enriched summary
    enriched = dict(summary)

    # Update avg_difficulty with corrected value
    enriched["avg_difficulty"] = round(corrected_avg_difficulty, 4)

    # Store original buggy avg_difficulty for reference
    if "avg_difficulty" in summary and summary["avg_difficulty"] != corrected_avg_difficulty:
        enriched["avg_difficulty_original"] = summary["avg_difficulty"]

    # Add display-friendly computed fields
    enriched["display"] = {
        "tasks_label": f"{total_tasks} tasks x {num_trials} trials",
        "simulations_label": f"{successful_simulations}/{total_simulations} passed",
        "pass_rate_pct": pass_rate_pct,
        "pass_at_1_pct": pass_at_1_pct,
        "pass_at_2_pct": pass_at_2_pct,
        "avg_difficulty_pct": round(corrected_avg_difficulty * 100, 1),
    }

    return enriched


def enrich_results(results_data: dict, difficulty_map: dict[str, dict[str, float]]) -> dict:
    """Enrich entire results JSON with display fields and corrected metrics.

    Args:
        results_data: Parsed results JSON data.
        difficulty_map: Dict mapping domain -> task_id -> difficulty score.

    Returns:
        Enriched results data.
    """
    # Handle different result formats
    # Format 1: List of result entries
    if isinstance(results_data, list):
        enriched = []
        for entry in results_data:
            enriched.append(enrich_single_result(entry, difficulty_map))
        return enriched

    # Format 2: Single result object with 'results' key containing list
    if "results" in results_data and isinstance(results_data["results"], list):
        enriched = dict(results_data)
        enriched["results"] = [
            enrich_single_result(entry, difficulty_map)
            for entry in results_data["results"]
        ]
        return enriched

    # Format 3: Single result object
    return enrich_single_result(results_data, difficulty_map)


def enrich_single_result(entry: dict, difficulty_map: dict[str, dict[str, float]]) -> dict:
    """Enrich a single result entry.

    Args:
        entry: Single result entry dict with 'summary' and optionally 'task_results'.
        difficulty_map: Dict mapping domain -> task_id -> difficulty score.

    Returns:
        Enriched entry.
    """
    enriched = dict(entry)

    summary = entry.get("summary", {})
    domain = summary.get("domain", "")
    task_results = entry.get("task_results", [])

    # Get difficulty map for this domain, default to empty
    domain_difficulty = difficulty_map.get(domain, {})

    # Enrich the summary
    enriched["summary"] = enrich_summary(summary, task_results, domain_difficulty)

    return enriched


def main():
    parser = argparse.ArgumentParser(
        description="Enrich results JSON with display metrics and corrected avg_difficulty"
    )
    parser.add_argument("results_file", type=Path, help="Path to results JSON file")
    parser.add_argument(
        "--difficulty-file",
        type=Path,
        default=DEFAULT_DIFFICULTY_FILE,
        help="Path to task difficulty JSON file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file path (default: overwrite input file)",
    )
    args = parser.parse_args()

    if not args.results_file.exists():
        print(f"Error: {args.results_file} not found")
        sys.exit(1)

    if not args.difficulty_file.exists():
        print(f"Error: {args.difficulty_file} not found")
        sys.exit(1)

    # Load files
    results_data = json.loads(args.results_file.read_text())
    difficulty_map = load_task_difficulty(args.difficulty_file)

    # Enrich results
    enriched_data = enrich_results(results_data, difficulty_map)

    # Write output
    output_file = args.output or args.results_file
    with open(output_file, "w") as f:
        json.dump(enriched_data, f, indent=2)

    print(f"Enriched results written to {output_file}")


if __name__ == "__main__":
    main()
