"""Server-side agent credentials.

API keys are never accepted from the browser — they're read once from the
environment (populated via a local .env file, which is gitignored) and used
only for outbound calls to the model provider. The frontend only ever sees
which model/endpoint is configured, never the key itself.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

AGENTS = {
    "a1": {
        "api_key": os.environ.get("AGENT1_API_KEY", ""),
        "base_url": os.environ.get("AGENT1_BASE_URL", DEFAULT_BASE_URL),
    },
    "a2": {
        "api_key": os.environ.get("AGENT2_API_KEY", ""),
        "base_url": os.environ.get("AGENT2_BASE_URL", DEFAULT_BASE_URL),
    },
}


def is_configured(which: str) -> bool:
    return bool(AGENTS.get(which, {}).get("api_key"))


def get_credentials(which: str) -> tuple[str, str]:
    """Returns (api_key, base_url) for the given agent ('a1' or 'a2')."""
    agent = AGENTS.get(which)
    if agent is None:
        raise ValueError(f"Unknown agent: {which}")
    return agent["api_key"], agent["base_url"]
