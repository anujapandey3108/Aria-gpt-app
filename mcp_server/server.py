"""
MCP server for Wrenfield Motors test drive booking, using the official
Python MCP SDK.

Powers ChatGPT Apps and Claude Connectors for the site at
https://wrenfield.aiaccelerate.com.au/

Install:
    pip install mcp --break-system-packages

Run (stdio, for local MCP hosts like Claude Desktop / Claude Code):
    python mcp_server/server.py

Run (HTTP/SSE, for hosted/remote MCP use):
    python mcp_server/server.py --http --port 8001
"""

import sys
import os
import argparse
from datetime import datetime
from typing import Optional, TypedDict

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app import booking_logic as logic

from mcp.server.fastmcp import FastMCP

from mcp.types import ToolAnnotations
from mcp.server.transport_security import TransportSecuritySettings

# The live Wrenfield Motors website. Included in tool outputs so ChatGPT and
# Claude have an absolute, user-openable URL to cite back to the customer.
WEBSITE_URL = "https://wrenfield.aiaccelerate.com.au/"

# By default the MCP SDK's DNS-rebinding protection only trusts requests whose
# Host header is localhost/127.0.0.1, correct for local dev, but it will
# reject every request once deployed publicly (seen as an HTTP 421 from
# Render/Cloudflare). Explicitly allow the real public hostname(s) here.
PUBLIC_HOST = os.environ.get("PUBLIC_HOSTNAME", "aria-gpt-mcp.onrender.com")

mcp = FastMCP(
    "wrenfield-motors",
    instructions=(
        "Wrenfield Motors is a Melbourne dealership selling the Wrenfield SUV "
        "and Wrenfield Sedan, both electric family vehicles, at "
        f"{WEBSITE_URL}. Before booking, confirm a vehicle, dealer, and "
        "available time slot in that order. Model and dealer names may be "
        "passed exactly as the user says them (e.g. 'Wrenfield Sedan', "
        "'Melbourne CBD'); do not convert to internal IDs yourself."
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[PUBLIC_HOST, "localhost", "127.0.0.1", f"localhost:{os.environ.get('PORT', 8001)}"],
        allowed_origins=[f"https://{PUBLIC_HOST}", "http://localhost", "http://127.0.0.1"],
    ),
)


WIDGET_URI = "ui://widget/booking-confirmation.html"


# Explicit return shape for book_test_drive. Without this, FastMCP can't
# build a schema from a bare `dict` return type, so no structuredContent is
# attached to the tool result and window.openai.toolOutput is undefined in
# the widget (every field renders blank except the hardcoded "Confirmed").
class BookingWidgetData(TypedDict):
    booking_id: str
    status: str
    confirmed_datetime: str
    dealer_id: str
    model_id: str
    message: str
    vehicle_name: str
    dealer_name: str


def _load_widget_html() -> str:
    path = os.path.join(os.path.dirname(__file__), "widgets", "booking_confirmation.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# Register the widget as an MCP resource. mime_type must be text/html+skybridge
# for ChatGPT's Apps SDK to inject its bridge script; the ui:// scheme is what
# the broader MCP Apps standard (_meta.ui.resourceUri) expects too.
@mcp.resource(
    WIDGET_URI,
    name="booking-confirmation-widget",
    mime_type="text/html+skybridge",
)
def booking_confirmation_widget() -> str:
    return _load_widget_html()


# OpenAI plugin submission domain verification. When the submission portal
# shows a "Domain not verified" challenge, it gives a token; set that value
# as the OPENAI_APPS_CHALLENGE_TOKEN env var on this Render service (do not
# commit the real token to source control). This route must return only the
# bare token string, no JSON wrapper, per OpenAI's submission requirements.
from starlette.responses import PlainTextResponse
from starlette.requests import Request

OPENAI_APPS_CHALLENGE_TOKEN = os.environ.get("OPENAI_APPS_CHALLENGE_TOKEN", "")


@mcp.custom_route("/.well-known/openai-apps-challenge", methods=["GET"])
async def openai_apps_challenge(request: Request) -> PlainTextResponse:
    if not OPENAI_APPS_CHALLENGE_TOKEN:
        return PlainTextResponse("Not configured", status_code=404)
    return PlainTextResponse(OPENAI_APPS_CHALLENGE_TOKEN)


@mcp.tool(
    name="wrenfield.search_vehicles",
    annotations=ToolAnnotations(
        title="Search Wrenfield vehicles",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def search_vehicles(
    body_style: Optional[str] = None,
    max_price: Optional[int] = None,
    min_seats: Optional[int] = None,
) -> list[dict]:
    """Use this when the user wants to browse, find, compare, or discover
    Wrenfield Motors vehicles. This includes indirect phrasing that never
    names the brand, such as 'family sedan under $50000', 'electric SUV for
    a family of five', or 'newborn friendly car under 50k', as well as direct
    queries like 'show me Wrenfield cars'.

    Do not use this for a single already-identified model (use
    wrenfield.get_vehicle instead), and do not use it for booking or
    availability questions.

    Args:
        body_style: Optional filter, e.g. 'sedan' or 'suv'. Omit to match any.
        max_price: Optional maximum drive-away price in AUD. Omit to match any.
        min_seats: Optional minimum seat count. Omit to match any.
    """
    results = logic.search_vehicles(
        body_style=body_style,
        max_price=max_price,
        min_seats=min_seats,
    )
    return [{**v.model_dump(), "website_url": WEBSITE_URL} for v in results]


@mcp.tool(
    name="wrenfield.get_vehicle",
    annotations=ToolAnnotations(
        title="Get vehicle details",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def get_vehicle(model_id: str) -> dict:
    """Use this once a specific Wrenfield model has been identified, either
    from wrenfield.search_vehicles results or because the user named it
    directly, e.g. 'tell me more about the Wrenfield Sedan'. Returns full
    specifications, pricing, and safety features.

    Do not use this for browsing multiple vehicles (use
    wrenfield.search_vehicles instead).

    Args:
        model_id: Vehicle name, natural language works, e.g. 'Wrenfield Sedan' or 'SUV'
    """
    return {**logic.get_vehicle(model_id).model_dump(), "website_url": WEBSITE_URL}


@mcp.tool(
    name="wrenfield.list_dealers",
    annotations=ToolAnnotations(
        title="List Wrenfield dealers",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def list_dealers(model_id: Optional[str] = None) -> list[dict]:
    """Use this after a vehicle has been chosen and before checking test
    drive availability, or when the user asks where they can see a car in
    person. Lists Wrenfield Motors dealer locations in Melbourne, optionally
    filtered to dealers that stock a specific model.

    Do not use this for checking a specific appointment time (use
    wrenfield.check_test_drive_availability instead).

    Args:
        model_id: Optional vehicle name to filter by, e.g. 'Wrenfield Sedan'.
                  Omit to list all dealers.
    """
    return logic.list_dealers(model_id)


@mcp.tool(
    name="wrenfield.check_test_drive_availability",
    annotations=ToolAnnotations(
        title="Check test drive availability",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def check_test_drive_availability(model_id: str, dealer_id: str, datetime_iso: str) -> dict:
    """Use this once a vehicle and dealer have been selected and the user
    proposes a date or time, e.g. 'can I test drive it Wednesday afternoon'.
    Checks whether that specific model/dealer/time slot is open.

    Do not use this to make the booking itself (use wrenfield.book_test_drive
    only after this confirms availability).

    Args:
        model_id: Vehicle name, natural language works, e.g. 'Wrenfield Sedan' or 'SUV'
        dealer_id: Dealer name, natural language works, e.g. 'Melbourne CBD' or 'Truganina'
        datetime_iso: Requested datetime in ISO 8601, e.g. '2026-08-03T10:00:00'
    """
    dt = datetime.fromisoformat(datetime_iso)
    return {"available": logic.check_availability(model_id, dealer_id, dt)}


@mcp.tool(
    name="wrenfield.book_test_drive",
    annotations=ToolAnnotations(
        title="Book a test drive",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
    meta={
        "openai/outputTemplate": WIDGET_URI,
        "openai/toolInvocation/invoking": "Booking your test drive…",
        "openai/toolInvocation/invoked": "Test drive booked",
        "openai/widgetPrefersBorder": True,
        "ui": {"resourceUri": WIDGET_URI},
    }
)
def book_test_drive(
    customer_name: str,
    email: str,
    phone: str,
    model_id: str,
    dealer_id: str,
    preferred_datetime_iso: str,
    notes: Optional[str] = None,
) -> BookingWidgetData:
    """Use this only after a vehicle, dealer, and an available time slot have
    been confirmed, typically after wrenfield.search_vehicles,
    wrenfield.list_dealers, and wrenfield.check_test_drive_availability.
    Creates a real, confirmed booking and returns a Wrenfield booking ID.
    Always read the chosen details back to the user before calling this tool.

    Do not use this before availability has been checked, and do not guess a
    time slot without confirming it first.

    Args:
        customer_name: Full name of the customer
        email: Customer email address
        phone: Customer phone number
        model_id: Vehicle name, natural language works, e.g. 'Wrenfield Sedan' or 'SUV'
        dealer_id: Dealer name, natural language works, e.g. 'Melbourne CBD' or 'Truganina'
        preferred_datetime_iso: Confirmed datetime in ISO 8601
        notes: Optional notes from the customer
    """
    req = logic.BookingRequest(
        customer_name=customer_name,
        email=email,
        phone=phone,
        model_id=model_id,
        dealer_id=dealer_id,
        preferred_datetime=datetime.fromisoformat(preferred_datetime_iso),
        notes=notes,
    )
    result = logic.create_booking(req)
    data = result.model_dump(mode="json")
    # The confirmation widget displays these directly (raw ids like
    # "sedan-2026" aren't customer-facing), the chat reply itself can
    # already phrase things naturally from context.
    data["vehicle_name"] = logic.CATALOG[result.model_id].name
    data["dealer_name"] = logic._dealer_display_name(result.dealer_id)
    return data


@mcp.tool(
    name="wrenfield.get_booking",
    annotations=ToolAnnotations(
        title="Get booking details",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def get_booking(booking_id: str) -> dict:
    """Use this to retrieve details of an existing Wrenfield test drive
    booking by its booking ID, e.g. when a customer asks about a booking
    they already made.

    Do not use this to check a new time slot's availability (use
    wrenfield.check_test_drive_availability instead).
    """
    return logic.get_booking(booking_id).model_dump()


@mcp.tool(
    name="wrenfield.cancel_booking",
    annotations=ToolAnnotations(
        title="Cancel a booking",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def cancel_booking(booking_id: str) -> dict:
    """Use this to cancel an existing Wrenfield test drive booking by its
    booking ID. This is a destructive action; confirm with the user before
    calling."""
    return logic.cancel_booking(booking_id).model_dump()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdio", action="store_true",
                         help="Run over stdio instead (for local Claude Desktop/Code use only)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8001)))
    args = parser.parse_args()

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        mcp.settings.port = args.port
        mcp.settings.host = "0.0.0.0"
        # Streamable HTTP is what ChatGPT's Apps SDK / MCP client expects for remote servers
        mcp.run(transport="streamable-http")
