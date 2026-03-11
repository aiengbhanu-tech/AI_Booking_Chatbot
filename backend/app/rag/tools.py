from pydantic import BaseModel


class ToolResult(BaseModel):
    ok: bool
    message: str
    data: dict | None = None


# Tool schema for OpenAI function calling
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_lead",
            "description": "Create a lead when user wants consultation/booking/callback or shares contact info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "intent": {"type": "string", "description": "e.g. appointment, callback, pricing, service inquiry"},
                    "notes": {"type": "string"},
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_callback",
            "description": "Request a callback/call scheduling when the user wants staff to call them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "preferred_time": {"type": "string"},
                    "phone": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_via_calendly",
            "description": "Provide Calendly booking link if tenant has it configured.",
            "parameters": {"type": "object", "properties": {"notes": {"type": "string"}}, "required": []},
        },
    },
]