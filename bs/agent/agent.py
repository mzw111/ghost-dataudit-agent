"""Orchestrates Gemini responses and backend tool execution."""

from google.genai import types

from .client import GeminiClient
from .executor import execute_tool
from .function_calling import get_search_evidence_tool


class GhostTraceAgent:
    """Gemini-powered agent with controlled evidence search."""

    def __init__(self, state):
        self.state = state
        self.gemini = GeminiClient()
        self.tool = get_search_evidence_tool()

    def investigate(self, prompt):
        """Ask Gemini to investigate a case using available tools."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Prompt must be a non-empty string.")

        contents = [
            types.UserContent(
                parts=[types.Part.from_text(text=prompt)]
            )
        ]
        config = types.GenerateContentConfig(tools=[self.tool])

        response = self.gemini.client.models.generate_content(
            model=self.gemini.model,
            contents=contents,
            config=config,
        )

        function_calls = response.function_calls
        if not function_calls:
            return response.text

        function_call = function_calls[0]
        function_name = function_call.name
        arguments = dict(function_call.args or {})
        result = execute_tool(function_name, arguments, self.state)

        contents.append(response.candidates[0].content)
        contents.append(
            types.Content(
                role="tool",
                parts=[
                    types.Part.from_function_response(
                        name=function_name,
                        response=result,
                    )
                ],
            )
        )

        final_response = self.gemini.client.models.generate_content(
            model=self.gemini.model,
            contents=contents,
            config=config,
        )
        return final_response.text
