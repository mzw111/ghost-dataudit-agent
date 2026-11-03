
"""Gemini API client for GhostTrace."""

from google import genai

from .config import get_gemini_config


class GeminiClient:
    """Small wrapper around Google's Gemini API."""

    def __init__(self):
        config = get_gemini_config()

        self.model = config["model"]
        self.client = genai.Client(api_key=config["api_key"])

    def generate(self, prompt):
        """Send a prompt to Gemini and return its text response."""

        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Prompt must be a non-empty string.")

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )

        return response.text
