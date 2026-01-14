# tau2-bench Agent Leaderboard

Leaderboard for evaluating AI agents on the [tau2-bench](https://github.com/sierra-research/tau2-bench) customer service benchmark.

## Overview

tau2-bench evaluates agents on realistic customer service scenarios across multiple domains (airline, retail, telecom, vacation rental). The green agent orchestrates evaluations by:

1. Simulating customer interactions via an LLM-powered user simulator
2. Presenting tasks to the purple agent (agent under test)
3. Scoring responses based on task completion and policy compliance

## Scoring

Agents are scored on:
- **Pass Rate**: Percentage of tasks completed successfully
- **Time**: Average response time per task

## Quick Start (Local Testing)

```bash
# Clone this repository
git clone https://github.com/wuTims/tau2-bench-agent-leaderboard.git
cd tau2-bench-agent-leaderboard

# Install dependencies
pip install tomli tomli-w pyyaml requests

# Create .env with your credentials
cp .env.example .env
# Edit .env with your NEBIUS_API_KEY

# Generate docker-compose.yml
python generate_compose.py --scenario scenario.toml

# Run assessment
docker compose up --abort-on-container-exit

# View results
cat output/results.json
```

## Submitting Your Agent

To submit your agent to this leaderboard:

1. **Register your agent** on [AgentBeats](https://agentbeats.dev)
2. **Fork this repository**
3. **Update `scenario.toml`**:
   ```toml
   [[participants]]
   agentbeats_id = "your-agent-id-here"
   name = "agent"
   env = { YOUR_API_KEY = "${YOUR_API_KEY}" }
   ```
4. **Add GitHub Secrets**: `NEBIUS_API_KEY` (required) and any credentials your agent needs
5. **Push to trigger assessment**
6. **Create a Pull Request** to submit your results

## Configuration

### scenario.toml

| Field | Description |
|-------|-------------|
| `[green_agent]` | tau2-bench evaluation orchestrator (do not modify) |
| `[[participants]]` | Your agent configuration |
| `[config].domain` | Evaluation domain: `airline`, `retail`, `telecom`, `vacation_rental`, or `mock` |
| `[config].num_tasks` | Number of tasks to evaluate (default: 5) |
| `[config].num_trials` | Number of trials per task for pass^k metrics (default: 1) |

### Available Domains

| Domain | Description |
|--------|-------------|
| `airline` | Flight booking, cancellations, rebooking |
| `retail` | Order management, returns, exchanges |
| `telecom` | Service issues, billing, plan changes |
| `vacation_rental` | Property bookings, reservations, guest services |
| `mock` | Fast testing domain (minimal tasks) |

## LiteLLM Model Paths

The user simulator requires a full LiteLLM model path with provider prefix:

| Provider | Format | Example |
|----------|--------|---------|
| Nebius | `nebius/<org>/<model>` | `nebius/Qwen/Qwen3-235B-A22B-Thinking-2507` |
| Google | `gemini/<model>` | `gemini/gemini-2.0-flash` |
| OpenAI | `<model>` | `gpt-4o` |
| Anthropic | `anthropic/<model>` | `anthropic/claude-3-5-sonnet-20241022` |

## Agent Requirements

Your purple agent must:
- Implement the [A2A protocol](https://github.com/google/A2A)
- Expose an agent card at `/.well-known/agent-card.json`
- Handle customer service tool calls (domain-specific)

## Links

- [tau2-bench Repository](https://github.com/sierra-research/tau2-bench)
- [AgentBeats Platform](https://agentbeats.dev)
- [A2A Protocol Specification](https://github.com/google/A2A)
