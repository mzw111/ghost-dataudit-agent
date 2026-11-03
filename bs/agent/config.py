
"""Configuration for the Gemini integration."""

import os
from dotenv import load_dotenv

# Load environment variables from the project root.
load_dotenv()


def get_gemini_config():
    """Load and validate Gemini configuration."""

    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is missing. Add it to your project-root .env file."
        )

    return {
        "api_key": api_key,
        "model": model,
    }
