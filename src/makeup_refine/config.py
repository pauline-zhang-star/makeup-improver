"""Read local credentials without logging or exposing their values."""
import os
from pathlib import Path

from dotenv import dotenv_values

from .models import SpikeError


def get_api_key(env_file: Path = Path(".env")) -> str:
    # Explicit current-directory file only; do not search parent directories.
    key = os.environ.get("OPENAI_API_KEY")
    if not key and env_file.is_file():
        key = dotenv_values(env_file, interpolate=False).get("OPENAI_API_KEY")
    if not key or not key.strip() or key.strip() == "PASTE_YOUR_KEY_HERE":
        raise SpikeError("CONFIGURATION_ERROR",
                         "Add OPENAI_API_KEY to the project's .env file or your environment.")
    return key.strip()
