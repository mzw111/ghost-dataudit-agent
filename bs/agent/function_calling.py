"""Gemini function declarations for GhostTrace."""

from google.genai import types


def get_search_evidence_tool():
    """Declare the evidence search tool for Gemini."""
    search_declaration = types.FunctionDeclaration(
        name="search_evidence",
        description=(
            "Search parsed evidence associated with a personal data "
            "deletion request. Use this to investigate resource states, "
            "deletion records, and system evidence."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "case_id": {
                    "type": "string",
                    "description": "The deletion request case ID.",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "A keyword or phrase to search for in the evidence, "
                        "such as deleted, retained, or archived."
                    ),
                },
            },
            "required": ["case_id", "query"],
        },
    )
    return types.Tool(function_declarations=[search_declaration])
