"""
MCP server for test drive booking, using the official Python MCP SDK.

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

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app import booking_logic as logic

from mcp.server.fastmcp import FastMCP

from mcp.types import ToolAnnotations
from mcp.server.transport_security import TransportSecuritySettings

# By default the MCP SDK's DNS-rebinding protection only trusts requests whose
# Host header is localhost/127.0.0.1, correct for local dev, but it will
# reject every request once deployed publicly (seen as an HTTP 421 from
# Render/Cloudflare). Explicitly allow the real public hostname(s) here.
PUBLIC_HOST = os.environ.get("PUBLIC_HOSTNAME", "aria-gpt-mcp.onrender.com")

mcp = FastMCP(
    "testdrive-booking",
    instructions=(
        "Wrenfield Motors is a Melbourne dealership selling the Wrenfield SUV and "
        "Wrenfield Sedan, both electric family vehicles with 5-star ANCAP safety "
        "ratings. Use search_vehicles for browsing or discovery intents, including "
        "phrasing that doesn't name the brand, such as 'family sedan under $50000', "
        "'electric SUV for a family of five', or 'newborn friendly car under 50k', as "
        "well as direct queries like 'show me Wrenfield cars'. Use get_vehicle once a "
        "specific model is identified. Use list_dealers to find where to see a model "
        "in person. Use check_test_drive_availability once a model, dealer, and "
        "candidate time are known. Use book_test_drive only after availability has "
        "been confirmed and the customer has agreed to the details. Model and dealer "
        "names can be passed exactly as the user says them (e.g. 'Wrenfield Sedan', "
        "'Melbourne CBD'), no need to convert to internal IDs."
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[PUBLIC_HOST, "localhost", "127.0.0.1", f"localhost:{os.environ.get('PORT', 8001)}"],
        allowed_origins=[f"https://{PUBLIC_HOST}", "http://localhost", "http://127.0.0.1"],
    ),
)


WIDGET_URI = "ui://widget/booking-confirmation.html"


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


@mcp.tool(
    annotations=ToolAnnotations(
        title="Search Wrenfield vehicles",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def search_vehicles(body_style: str = "", max_price: int = 0, min_seats: int = 0) -> list[dict]:
    """Search Wrenfield Motors vehicles by body style, price, and seating.

    Use this tool when the user asks to browse, find, compare, or discover
    Wrenfield vehicles, including phrasing that doesn't name the brand directly,
    such as 'family sedan under $50000', 'electric SUV for a family of five',
    or 'newborn friendly car under 50k'. Also use it for direct brand queries
    like 'show me Wrenfield cars' or 'what does Wrenfield sell'.

    Args:
        body_style: Optional filter, e.g. 'sedan' or 'suv'. Leave empty to match any.
        max_price: Optional maximum drive-away price in AUD. Leave 0 to match any.
        min_seats: Optional minimum seat count. Leave 0 to match any.
    """
    results = logic.search_vehicles(
        body_style=body_style or None,
        max_price=max_price or None,
        min_seats=min_seats or None,
    )
    return [v.model_dump() for v in results]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get vehicle details",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def get_vehicle(model_id: str) -> dict:
    """Get full specifications, pricing, and safety features for one Wrenfield
    vehicle. Use this after search_vehicles has narrowed to a specific model,
    or when the user names a model directly, e.g. 'tell me more about the
    Wrenfield Sedan'.

    Args:
        model_id: Vehicle name, natural language works, e.g. 'Wrenfield Sedan' or 'SUV'
    """
    return logic.get_vehicle(model_id).model_dump()


@mcp.tool(
    annotations=ToolAnnotations(
        title="List Wrenfield dealers",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def list_dealers(model_id: str = "") -> list[dict]:
    """List Wrenfield Motors dealer locations in Melbourne, optionally filtered
    to dealers that stock a specific model. Use this after a vehicle has been
    chosen and before checking test drive availability, or when the user asks
    where they can see a car in person.

    Args:
        model_id: Optional vehicle name to filter by, e.g. 'Wrenfield Sedan'.
                  Leave empty to list all dealers.
    """
    return logic.list_dealers(model_id or None)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check test drive availability",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def check_test_drive_availability(model_id: str, dealer_id: str, datetime_iso: str) -> dict:
    """Check whether a specific model/dealer/time slot is open for a test drive.
    Use this after a vehicle and dealer have been selected and the user proposes
    a date or time, e.g. 'can I test drive it Wednesday afternoon'.

    Args:
        model_id: Vehicle name, natural language works, e.g. 'Wrenfield Sedan' or 'SUV'
        dealer_id: Dealer name, natural language works, e.g. 'Melbourne CBD' or 'Truganina'
        datetime_iso: Requested datetime in ISO 8601, e.g. '2026-08-03T10:00:00'
    """
    dt = datetime.fromisoformat(datetime_iso)
    return {"available": logic.check_availability(model_id, dealer_id, dt)}


@mcp.tool(
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
    notes: str = "",
) -> dict:
    """Book a test drive for a Wrenfield Motors vehicle. Use this only after a
    vehicle, dealer, and an available time slot have been confirmed (typically
    after search_vehicles, list_dealers, and check_test_drive_availability).
    Creates a real, confirmed booking and returns a Wrenfield booking ID.
    Always read the chosen details back to the user before calling this tool.

    Args:
        customer_name: Full name of the customer
        email: Customer email address
        phone: Customer phone number
        model_id: Vehicle name, natural language works, e.g. 'Wrenfield Sedan' or 'SUV'
        dealer_id: Dealer name, natural language works, e.g. 'Melbourne CBD' or 'Truganina'
        preferred_datetime_iso: Confirmed datetime in ISO 8601
        notes: Optional notes
    """
    req = logic.BookingRequest(
        customer_name=customer_name,
        email=email,
        phone=phone,
        model_id=model_id,
        dealer_id=dealer_id,
        preferred_datetime=datetime.fromisoformat(preferred_datetime_iso),
        notes=notes or None,
    )
    result = logic.create_booking(req)
    return result.model_dump()


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get booking details",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def get_booking(booking_id: str) -> dict:
    """Retrieve details of an existing booking by ID."""
    return logic.get_booking(booking_id).model_dump()


@mcp.tool(
    annotations=ToolAnnotations(
        title="Cancel a booking",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def cancel_booking(booking_id: str) -> dict:
    """Cancel an existing booking by ID. This is a destructive action, confirm with
    the user before calling."""
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