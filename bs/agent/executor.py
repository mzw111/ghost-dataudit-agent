"""Controlled executor for Gemini-requested tools."""

from .tools import search_evidence


# Only explicitly registered functions can be executed.
AVAILABLE_TOOLS = {
    "search_evidence": search_evidence,
}


def execute_tool(function_name, arguments, state):
    """Execute an approved tool using backend-controlled state."""
    if function_name not in AVAILABLE_TOOLS:
        return {
            "ok": False,
            "error": {
                "code": "UNKNOWN_TOOL",
                "message": f"Tool '{function_name}' is not available.",
            },
        }

    if not isinstance(arguments, dict):
        return {
            "ok": False,
            "error": {
                "code": "INVALID_ARGUMENTS",
                "message": "Tool arguments must be a dictionary.",
            },
        }

    allowed_arguments = {"case_id", "query"}
    unexpected_arguments = set(arguments) - allowed_arguments
    if unexpected_arguments:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_ARGUMENTS",
                "message": "Tool arguments contain unsupported fields.",
            },
        }

    missing_arguments = allowed_arguments - set(arguments)
    if missing_arguments:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_ARGUMENTS",
                "message": "Tool arguments are missing required fields.",
            },
        }

    return AVAILABLE_TOOLS[function_name](
        case_id=arguments["case_id"],
        query=arguments["query"],
        state=state,
    )
