from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class ToolResult(BaseModel):
    ok: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# OpenAI function/tool schema
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_lead",
            "description": "Create a lead when the user wants consultation, booking, callback, or shares contact info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Full name of the user"
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address of the user"
                    },
                    "phone": {
                        "type": "string",
                        "description": "Phone number of the user"
                    },
                    "intent": {
                        "type": "string",
                        "description": "Intent such as appointment, callback, pricing, or service inquiry"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Additional notes from the user"
                    },
                },
                "required": ["intent"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_callback",
            "description": "Request a callback when the user wants someone to call them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "preferred_time": {
                        "type": "string",
                        "description": "Preferred callback time"
                    },
                    "phone": {
                        "type": "string",
                        "description": "Phone number for callback"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Additional notes"
                    },
                },
                "required": ["phone"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_via_calendly",
            "description": "Provide a Calendly booking link if available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "notes": {
                        "type": "string",
                        "description": "Optional message or context"
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]