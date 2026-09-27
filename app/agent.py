"""
Conversational booking assistant embedded directly on the Wrenfield
website (the "VGA Branded Booking Agent" channel in the architecture
deck) — a chat widget on wrenfield.aiaccelerate.com.au that a customer
can use to find a model and book a test drive end to end, with nothing
to install and no AI platform's plugin/connector approval in the loop.

Uses the same booking_logic module as every other channel (REST Actions
for GPT, the MCP server for Claude/ChatGPT connectors, and the manual
console form), so behavior is identical no matter which surface books
the test drive.

Requires the ANTHROPIC_API_KEY environment variable. Model is
configurable via ANTHROPIC_MODEL (defaults to the current Claude
Sonnet, "claude-sonnet-5"); set it explicitly if Anthropic ships a
newer default before you redeploy.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Optional

from . import booking_logic as logic

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_TOOL_ROUNDS = 6  # hard cap so a runaway tool loop can't hang a request
MAX_STORED_MESSAGES = 20  # per-session history cap for this demo's in-memory store

_client = None


def _get_client():
    """Lazy import + init so the app can still boot (and every other
    channel keep working) if ANTHROPIC_API_KEY isn't set yet."""
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set, the website chat assistant is "
                "unavailable. Every other booking channel (console form, "
                "REST Actions, MCP) is unaffected."
            )
        import anthropic

        _client = anthropic.Anthropic(api_key=api_key)
    return _client


SYSTEM_PROMPT = """You are the Wrenfield Motors test drive booking assistant, \
embedded as a chat widget on the Wrenfield website \
(wrenfield.aiaccelerate.com.au). Wrenfield is a Melbourne dealership selling \
two electric family vehicles: the Wrenfield SUV (from $58,000, at Melbourne \
CBD and Truganina) and the Wrenfield Sedan (under $50,000, at Melbourne CBD \
only), both 5-star ANCAP rated.

Help the customer find the right model, then book a test drive, entirely in \
this chat window. Always:
1. Use search_vehicles to recommend a model based on what the customer \
actually needs (budget, seats, body style), rather than reciting the full \
catalog unprompted.
2. Use list_dealers to confirm a dealer that stocks the chosen model.
3. Use check_availability before proposing a specific slot. Dealers are open \
weekdays, 9am-5pm; slots need to be at least 30 minutes apart.
4. Before calling create_booking, restate the model, dealer, and date/time \
back to the customer, confirm you have their name, email, and phone, and \
ask them to confirm. Only call create_booking after they say yes.
5. Never expose internal IDs like "sedan-2026" or "dealer-melbourne-cbd" to \
the customer, always use the natural name.
6. Keep replies short and conversational, this is a chat bubble, not an \
essay.

Today's date is {today}, use it to resolve relative dates like "next \
Tuesday"."""


def _tool_schemas() -> list[dict]:
    return [
        {
            "name": "search_vehicles",
            "description": (
                "Search the Wrenfield catalog by body style, max price, "
                "and/or minimum seats. All filters are optional; omit ones "
                "the customer hasn't specified."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "body_style": {"type": "string", "description": "e.g. 'SUV' or 'Sedan'"},
                    "max_price": {"type": "integer", "description": "Maximum price in AUD"},
                    "min_seats": {"type": "integer", "description": "Minimum seating capacity"},
                },
            },
        },
        {
            "name": "list_dealers",
            "description": (
                "List Wrenfield dealer locations, optionally filtered to "
                "ones that stock a given model."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "model_id": {
                        "type": "string",
                        "description": "Natural model name, e.g. 'Wrenfield Sedan'",
                    },
                },
            },
        },
        {
            "name": "check_availability",
            "description": (
                "Check whether a specific model/dealer/time slot is "
                "available for a test drive."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "model_id": {"type": "string"},
                    "dealer_id": {"type": "string"},
                    "datetime_iso": {
                        "type": "string",
                        "description": "ISO 8601 datetime, e.g. 2026-10-01T14:00:00",
                    },
                },
                "required": ["model_id", "dealer_id", "datetime_iso"],
            },
        },
        {
            "name": "create_booking",
            "description": (
                "Create a confirmed test drive booking. Only call this "
                "after the customer has explicitly confirmed the model, "
                "dealer, and date/time, and provided their name, email, "
                "and phone."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "model_id": {"type": "string"},
                    "dealer_id": {"type": "string"},
                    "preferred_datetime": {
                        "type": "string",
                        "description": "ISO 8601 datetime",
                    },
                    "notes": {"type": "string"},
                },
                "required": [
                    "customer_name",
                    "email",
                    "phone",
                    "model_id",
                    "dealer_id",
                    "preferred_datetime",
                ],
            },
        },
    ]


def _run_tool(name: str, tool_input: dict) -> dict:
    try:
        if name == "search_vehicles":
            vehicles = logic.search_vehicles(
                body_style=tool_input.get("body_style"),
                max_price=tool_input.get("max_price"),
                min_seats=tool_input.get("min_seats"),
            )
            return {"vehicles": [v.model_dump() for v in vehicles]}

        if name == "list_dealers":
            return {"dealers": logic.list_dealers(model_id=tool_input.get("model_id"))}

        if name == "check_availability":
            dt = datetime.fromisoformat(tool_input["datetime_iso"])
            available = logic.check_availability(
                tool_input["model_id"], tool_input["dealer_id"], dt
            )
            return {"available": available}

        if name == "create_booking":
            req = logic.BookingRequest(
                customer_name=tool_input["customer_name"],
                email=tool_input["email"],
                phone=tool_input["phone"],
                model_id=tool_input["model_id"],
                dealer_id=tool_input["dealer_id"],
                preferred_datetime=datetime.fromisoformat(tool_input["preferred_datetime"]),
                notes=tool_input.get("notes"),
            )
            result = logic.create_booking(req)
            return {"booking": result.model_dump(mode="json")}

        return {"error": f"Unknown tool: {name}"}
    except (ValueError, KeyError) as e:
        # Surfaced back to the model as a tool_result, not raised, so it can
        # explain the problem to the customer and try again (e.g. an
        # unavailable slot) instead of the whole turn failing.
        return {"error": str(e)}


# In-memory per-session conversation store, fine for a demo; swap for
# Redis/DB if this widget goes into production with real concurrent traffic.
_SESSIONS: dict[str, list[dict]] = {}


def handle_chat_message(session_id: Optional[str], user_message: str) -> dict:
    """Run one user turn through the tool-use loop and return the reply.

    Returns {"session_id", "reply", "booking"} where booking is the
    BookingResult dict if create_booking was called this turn, else None.
    """
    sid = session_id or uuid.uuid4().hex
    history = _SESSIONS.setdefault(sid, [])
    history.append({"role": "user", "content": user_message})

    client = _get_client()
    system = SYSTEM_PROMPT.format(today=datetime.now().strftime("%A, %d %B %Y"))

    booking_made: Optional[dict] = None
    response = None

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            tools=_tool_schemas(),
            messages=history,
        )
        history.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _run_tool(block.name, block.input)
                if block.name == "create_booking" and "booking" in result:
                    booking_made = result["booking"]
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )
        history.append({"role": "user", "content": tool_results})

    if len(history) > MAX_STORED_MESSAGES:
        _SESSIONS[sid] = history[-MAX_STORED_MESSAGES:]

    reply_text = ""
    if response is not None:
        reply_text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

    return {
        "session_id": sid,
        "reply": reply_text or "Sorry, I didn't catch that, could you say it again?",
        "booking": booking_made,
    }
