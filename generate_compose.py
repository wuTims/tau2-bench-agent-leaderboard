"""Generate Docker Compose configuration from scenario.toml

Supports Google ADK agents that serve at /a2a/<agent_name>/ paths.
Add 'agent_name' field to scenario.toml for proper A2A endpoint discovery.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib as tomli
except ImportError:
    try:
        import tomli
    except ImportError:
        print("Error: tomli required. Install with: pip install tomli")
        sys.exit(1)

try:
    import tomli_w
except ImportError:
    print("Error: tomli_w required. Install with: pip install tomli-w")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Error: requests required. Install with: pip install requests")
    sys.exit(1)


AGENTBEATS_API_URL = "https://agentbeats.dev/api/agents"


def fetch_agent_info(agentbeats_id: str) -> dict:
    """Fetch agent info from agentbeats.dev API."""
    url = f"{AGENTBEATS_API_URL}/{agentbeats_id}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"Error: Failed to fetch agent {agentbeats_id}: {e}")
        sys.exit(1)
    except requests.exceptions.JSONDecodeError:
        print(f"Error: Invalid JSON response for agent {agentbeats_id}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error: Request failed for agent {agentbeats_id}: {e}")
        sys.exit(1)


COMPOSE_PATH = "docker-compose.yml"
A2A_SCENARIO_PATH = "a2a-scenario.toml"
ENV_PATH = ".env.example"

DEFAULT_PORT = 9009
DEFAULT_ENV_VARS = {"PYTHONUNBUFFERED": "1"}

# Template with ADK-style health check path support
COMPOSE_TEMPLATE = """# Auto-generated from scenario.toml

services:
  green-agent:
    image: {green_image}
{green_pull_policy}    container_name: green-agent
    command: ["--host", "0.0.0.0", "--port", "{green_port}"]
    env_file:
      - .env
    environment:{green_env}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:{green_port}{green_health_path}"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 30s
    depends_on:{green_depends}
    networks:
      - agent-network

{participant_services}
  agentbeats-client:
    image: ghcr.io/agentbeats/agentbeats-client:v1.0.0
    platform: linux/amd64
    container_name: agentbeats-client
    configs:
      - source: scenario
        target: /app/scenario.toml
    volumes:
      - ./output:/app/output
    command: ["scenario.toml", "output/results.json"]
    depends_on:{client_depends}
    networks:
      - agent-network

configs:
  scenario:
    file: ./a2a-scenario.toml

networks:
  agent-network:
    driver: bridge
"""

# Participant template with ADK-style health check path support
PARTICIPANT_TEMPLATE = """  {name}:
    image: {image}
{pull_policy}    container_name: {name}
    command: ["--host", "0.0.0.0", "--port", "{port}"]
    environment:{env}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:{port}{health_path}"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 30s
    networks:
      - agent-network
"""

# A2A scenario template with ADK-style endpoint paths
A2A_SCENARIO_TEMPLATE = """[green_agent]
endpoint = "http://green-agent:{green_port}{green_a2a_path}"

{participants}
{config}"""


def get_agent_base_path(agent_name: str | None = None, env: dict[str, str] | None = None) -> str:
    """Get base A2A path for an agent.

    Priority:
    1. agent_name field (explicit): /a2a/<agent_name>
    2. CARD_URL env var (extracted path from URL)
    3. Default: empty string (root-based A2A)

    Args:
        agent_name: Optional explicit agent name for ADK-style path.
        env: Optional environment variables dict to extract CARD_URL from.

    Returns:
        Base path for agent (e.g., "/a2a/tau2_agent" or "").
    """
    if agent_name:
        return f"/a2a/{agent_name}"

    if env:
        card_url = env.get("CARD_URL", "")
        if card_url and not card_url.startswith("${"):
            from urllib.parse import urlparse
            path = urlparse(card_url).path.rstrip("/")
            if path:
                return path

    return ""


def get_health_check_path(agent_name: str | None = None, env: dict[str, str] | None = None) -> str:
    """Get health check path for an agent's agent-card endpoint.

    Returns base path + /.well-known/agent-card.json
    """
    base_path = get_agent_base_path(agent_name, env)
    return f"{base_path}/.well-known/agent-card.json"


def get_pull_policy(image: str) -> str:
    """Get the appropriate pull policy/platform for an image.

    Local images (ending with :local) use pull_policy: never to prevent
    Docker from trying to pull from a registry. Remote images use
    platform: linux/amd64 for cross-platform compatibility.

    Args:
        image: Docker image name (e.g., "myimage:local" or "ghcr.io/org/image:v1").

    Returns:
        YAML-formatted line with 4-space indentation and trailing newline.
    """
    if image.endswith(":local"):
        return "    pull_policy: never\n"
    return "    platform: linux/amd64\n"


def resolve_image(agent: dict, name: str) -> None:
    """Resolve docker image for an agent, either from 'image' field or agentbeats API.

    Updates the agent dict in-place by fetching image from agentbeats API if needed.
    Validates that exactly one of 'image' or 'agentbeats_id' is provided.

    Args:
        agent: Agent configuration dict (modified in-place).
        name: Agent name for error messages (e.g., "green_agent", "participant 'foo'").

    Raises:
        SystemExit: If both fields, neither field, or image resolution fails.
    """
    has_image = "image" in agent
    has_id = "agentbeats_id" in agent

    if has_image and has_id:
        print(f"Error: {name} has both 'image' and 'agentbeats_id' - use one or the other")
        sys.exit(1)

    if not has_image and not has_id:
        print(f"Error: {name} must have either 'image' or 'agentbeats_id' field")
        sys.exit(1)

    if has_image:
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"Error: {name} requires 'agentbeats_id' for GitHub Actions (use 'image' for local testing only)")
            sys.exit(1)
        print(f"Using {name} image: {agent['image']}")
        return

    info = fetch_agent_info(agent["agentbeats_id"])
    agent["image"] = info["docker_image"]
    print(f"Resolved {name} image: {agent['image']}")


def parse_scenario(scenario_path: Path) -> dict[str, Any]:
    """Parse and validate scenario.toml file.

    Resolves agent images from either direct 'image' field or agentbeats API,
    and validates that all participants have unique names.

    Args:
        scenario_path: Path to scenario.toml file.

    Returns:
        Parsed scenario dict with resolved image fields.

    Raises:
        SystemExit: If validation fails or image resolution fails.
    """
    data = tomli.loads(scenario_path.read_text())

    green = data.get("green_agent", {})
    resolve_image(green, "green_agent")

    participants = data.get("participants", [])

    # Check for duplicate participant names
    names = [p.get("name") for p in participants]
    duplicates = [name for name in set(names) if names.count(name) > 1]
    if duplicates:
        print(f"Error: Duplicate participant names found: {', '.join(duplicates)}")
        print("Each participant must have a unique name.")
        sys.exit(1)

    for participant in participants:
        name = participant.get("name", "unknown")
        resolve_image(participant, f"participant '{name}'")

    return data


def format_env_vars(env_dict: dict[str, Any]) -> str:
    """Format environment variables for docker-compose YAML.

    Uses dictionary format which handles complex values better than list format.
    Values are properly quoted to prevent YAML parsing issues.
    """
    env_vars = {**DEFAULT_ENV_VARS, **env_dict}
    lines = []
    for key, value in env_vars.items():
        str_value = str(value)
        # Always quote values in dictionary format for safety
        # Escape backslashes and double quotes
        str_value = str_value.replace('\\', '\\\\').replace('"', '\\"')
        lines.append(f'      {key}: "{str_value}"')
    return "\n" + "\n".join(lines)


def format_depends_on(services: list) -> str:
    """Format service dependencies for docker-compose healthcheck conditions.

    Args:
        services: List of service names.

    Returns:
        YAML-formatted depends_on block with service_healthy conditions, or empty string.
    """
    if not services:
        return ""
    lines = [f"      {service}:\n        condition: service_healthy" for service in services]
    return "\n" + "\n".join(lines)


def generate_docker_compose(scenario: dict[str, Any]) -> str:
    """Generate docker-compose.yml configuration from scenario.

    Creates service definitions for green agent, participants, and agentbeats client.
    Automatically sets CARD_URL environment variable for A2A protocol endpoint discovery.

    Args:
        scenario: Parsed scenario dict with green_agent and participants.

    Returns:
        YAML-formatted docker-compose configuration as string.
    """
    green = scenario["green_agent"]
    participants = scenario.get("participants", [])
    participant_names = [p["name"] for p in participants]

    # Add CARD_URL for A2A protocol: agent card URL field must use container hostname
    green_env = {**green.get("env", {}), "CARD_URL": f"http://green-agent:{DEFAULT_PORT}"}
    green_health_path = get_health_check_path(green.get("agent_name"), green_env)

    participant_services = "\n".join([
        PARTICIPANT_TEMPLATE.format(
            name=p["name"],
            image=p["image"],
            port=DEFAULT_PORT,
            env=format_env_vars({**p.get("env", {}), "CARD_URL": f"http://{p['name']}:{DEFAULT_PORT}"}),
            health_path=get_health_check_path(p.get("agent_name"), p.get("env", {})),
            pull_policy=get_pull_policy(p["image"])
        )
        for p in participants
    ])

    return COMPOSE_TEMPLATE.format(
        green_image=green["image"],
        green_port=DEFAULT_PORT,
        green_env=format_env_vars(green_env),
        green_health_path=green_health_path,
        green_depends=format_depends_on(participant_names),
        participant_services=participant_services,
        client_depends=format_depends_on(["green-agent"] + participant_names),
        green_pull_policy=get_pull_policy(green["image"])
    )


def generate_a2a_scenario(scenario: dict[str, Any]) -> str:
    """Generate a2a-scenario.toml from scenario configuration.

    Builds agent endpoints using container hostnames and A2A base paths.
    Includes config section (domain, num_tasks, etc.) from original scenario.

    Args:
        scenario: Parsed scenario dict with green_agent, participants, and config.

    Returns:
        TOML-formatted A2A scenario configuration as string.
    """
    green = scenario["green_agent"]
    participants = scenario.get("participants", [])

    green_a2a_path = get_agent_base_path(green.get("agent_name"), green.get("env", {}))

    participant_lines = []
    for p in participants:
        participant_a2a_path = get_agent_base_path(p.get("agent_name"), p.get("env", {}))
        lines = [
            "[[participants]]",
            f"role = \"{p['name']}\"",
            f"endpoint = \"http://{p['name']}:{DEFAULT_PORT}{participant_a2a_path}\"",
        ]
        if "agentbeats_id" in p:
            lines.append(f"agentbeats_id = \"{p['agentbeats_id']}\"")
        participant_lines.append("\n".join(lines) + "\n")

    config_toml = tomli_w.dumps({"config": scenario.get("config", {})})

    return A2A_SCENARIO_TEMPLATE.format(
        green_port=DEFAULT_PORT,
        green_a2a_path=green_a2a_path,
        participants="\n".join(participant_lines),
        config=config_toml
    )


def generate_env_file(scenario: dict[str, Any]) -> str:
    """Generate .env.example file with placeholder secrets from scenario.

    Extracts all ${VAR_NAME} placeholders from environment variables in scenario.
    Used to document required secrets for the docker-compose environment.

    Args:
        scenario: Parsed scenario dict with green_agent and participants.

    Returns:
        Newline-separated list of "VAR_NAME=" entries, or empty string if no placeholders.
    """
    env_var_pattern = re.compile(r'\$\{([^}]+)\}')
    secrets = set()

    all_agents = [scenario["green_agent"]] + scenario.get("participants", [])
    for agent in all_agents:
        for value in agent.get("env", {}).values():
            secrets.update(env_var_pattern.findall(str(value)))

    if not secrets:
        return ""

    return "\n".join(f"{secret}=" for secret in sorted(secrets)) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Generate Docker Compose from scenario.toml")
    parser.add_argument("--scenario", type=Path)
    args = parser.parse_args()

    if not args.scenario.exists():
        print(f"Error: {args.scenario} not found")
        sys.exit(1)

    scenario = parse_scenario(args.scenario)

    with open(COMPOSE_PATH, "w") as f:
        f.write(generate_docker_compose(scenario))

    with open(A2A_SCENARIO_PATH, "w") as f:
        f.write(generate_a2a_scenario(scenario))

    env_content = generate_env_file(scenario)
    if env_content:
        with open(ENV_PATH, "w") as f:
            f.write(env_content)
        print(f"Generated {ENV_PATH}")

    print(f"Generated {COMPOSE_PATH} and {A2A_SCENARIO_PATH}")

if __name__ == "__main__":
    main()
