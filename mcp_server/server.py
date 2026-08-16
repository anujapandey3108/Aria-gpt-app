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
# Host header is localhost/127.0.0.1 — correct for local dev, but it will
# reject every request once deployed publicly (seen as an HTTP 421 from
# Render/Cloudflare). Explicitly allow the real public hostname(s) here.
PUBLIC_HOST = os.environ.get("PUBLIC_HOSTNAME", "testdrive-mcp.onrender.com")

mcp = FastMCP(
    "testdrive-booking",
    instructions=(
        "Use these tools when a user wants to browse vehicle models, check test drive "
        "availability, or book/manage a test drive appointment for the Aria SUV or Aria "
        "Sedan. Trigger on intents like 'book a test drive', 'test drive an SUV', 'schedule "
        "a car viewing', 'try out the Aria'. Always call list_vehicles or check_availability "
        "before create_booking if the user hasn't specified an exact model_id and dealer_id. "
        "Valid dealer_id values are exactly 'dealer-melbourne-cbd' and 'dealer-truganina'."
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
        title="List vehicle models",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def list_vehicles() -> list[dict]:
    """List all vehicle models available for test drives. Use this when the user wants
    to browse or compare available vehicles (e.g. 'what cars can I test drive', 'show me the SUV')."""
    return [v.model_dump() for v in logic.list_vehicles()]


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check test drive availability",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
def check_availability(model_id: str, dealer_id: str, datetime_iso: str) -> dict:
    """Check whether a model/dealer/time slot is available for a test drive.

    Args:
        model_id: Vehicle model ID, e.g. 'suv-2026'
        dealer_id: Dealer ID, e.g. 'dealer-melbourne-cbd'
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
def create_booking(
    customer_name: str,
    email: str,
    phone: str,
    model_id: str,
    dealer_id: str,
    preferred_datetime_iso: str,
    notes: str = "",
) -> dict:
    """Create a new test drive booking. Use this when the user wants to confirm/book a
    test drive after choosing a model, dealer, and time (e.g. 'book it', 'confirm my
    test drive for Tuesday at 10am'). Always confirm these details back to the user
    before calling this tool.

    Args:
        customer_name: Full name of the customer
        email: Customer email address
        phone: Customer phone number
        model_id: Vehicle model ID, e.g. 'suv-2026'
        dealer_id: Dealer ID, e.g. 'dealer-melbourne-cbd'
        preferred_datetime_iso: Preferred datetime in ISO 8601
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
    """Cancel an existing booking by ID. This is a destructive action — confirm with
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