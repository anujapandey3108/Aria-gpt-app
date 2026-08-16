"""
Core test-drive booking logic.
Shared by both the REST API (for GPT Actions) and the MCP server,
so behavior is identical no matter which client calls it.

Replace the in-memory store with a real DB (Postgres, Salesforce, etc.)
for production use.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel, Field, EmailStr


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class Vehicle(BaseModel):
    model_id: str
    name: str
    variant: str
    available_dealers: list[str]


class BookingRequest(BaseModel):
    customer_name: str = Field(..., description="Full name of the customer")
    email: EmailStr
    phone: str
    model_id: str = Field(..., description="Vehicle model ID, e.g. 'suv-2026'")
    dealer_id: str
    preferred_datetime: datetime = Field(..., description="ISO 8601 datetime")
    notes: Optional[str] = None


class BookingResult(BaseModel):
    booking_id: str
    status: str
    confirmed_datetime: datetime
    dealer_id: str
    model_id: str
    message: str


# ---------------------------------------------------------------------------
# Fake catalog + store (swap for real DB / Salesforce / CRM calls)
# ---------------------------------------------------------------------------

CATALOG: dict[str, Vehicle] = {
    "suv-2026": Vehicle(model_id="suv-2026", name="Aria SUV", variant="2026",
                         available_dealers=["dealer-melbourne-cbd", "dealer-truganina"]),
    "sedan-2026": Vehicle(model_id="sedan-2026", name="Aria Sedan", variant="2026",
                           available_dealers=["dealer-melbourne-cbd"]),
}

BOOKINGS: dict[str, BookingResult] = {}


# ---------------------------------------------------------------------------
# Business logic functions (pure, testable, no framework dependency)
# ---------------------------------------------------------------------------

def list_vehicles() -> list[Vehicle]:
    return list(CATALOG.values())


def _normalize_model_id(model_id: str) -> str:
    key = model_id.strip().lower()
    if key in CATALOG:
        return key
    raise ValueError(
        f"Unknown model_id: {model_id!r}. Valid options: {list(CATALOG.keys())}"
    )


def _normalize_dealer_id(dealer_id: str, model_id: str) -> str:
    key = dealer_id.strip().lower()
    valid = CATALOG[model_id].available_dealers
    if key in valid:
        return key
    # Allow callers to omit the "dealer-" prefix, e.g. "melbourne-cbd" -> "dealer-melbourne-cbd"
    prefixed = key if key.startswith("dealer-") else f"dealer-{key}"
    if prefixed in valid:
        return prefixed
    raise ValueError(
        f"Dealer {dealer_id!r} does not stock {model_id}. Valid dealers: {valid}"
    )


def check_availability(model_id: str, dealer_id: str, requested: datetime) -> bool:
    model_id = _normalize_model_id(model_id)
    dealer_id = _normalize_dealer_id(dealer_id, model_id)
    # Simplified slot rule: allow any weekday time between 9am-5pm,
    # not already booked at that dealer within +/- 30 min.
    if requested.weekday() >= 5:
        return False
    if not (9 <= requested.hour < 17):
        return False
    for b in BOOKINGS.values():
        if b.dealer_id == dealer_id and abs((b.confirmed_datetime - requested).total_seconds()) < 1800:
            return False
    return True


def create_booking(req: BookingRequest) -> BookingResult:
    model_id = _normalize_model_id(req.model_id)
    dealer_id = _normalize_dealer_id(req.dealer_id, model_id)
    if not check_availability(model_id, dealer_id, req.preferred_datetime):
        raise ValueError(
            "Requested slot is unavailable. Try a weekday between 9am-5pm, "
            "at least 30 minutes from another booking."
        )
    booking_id = f"TD-{uuid.uuid4().hex[:8].upper()}"
    result = BookingResult(
        booking_id=booking_id,
        status="confirmed",
        confirmed_datetime=req.preferred_datetime,
        dealer_id=dealer_id,
        model_id=model_id,
        message=f"Test drive confirmed for {CATALOG[model_id].name} at {dealer_id}.",
    )
    BOOKINGS[booking_id] = result
    return result


def get_booking(booking_id: str) -> BookingResult:
    if booking_id not in BOOKINGS:
        raise ValueError(f"No booking found with id {booking_id}")
    return BOOKINGS[booking_id]


def cancel_booking(booking_id: str) -> BookingResult:
    b = get_booking(booking_id)
    b.status = "cancelled"
    return b
