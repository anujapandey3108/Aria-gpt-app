"""
Core test-drive booking logic.
Shared by both the REST API (for GPT Actions) and the MCP server,
so behavior is identical no matter which client calls it.

Replace the in-memory store with a real DB (Postgres, Salesforce, etc.)
for production use.
"""

from __future__ import annotations
import re
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
    body_type: str
    price_aud: int
    seats: int
    range_km: int
    drivetrain: str
    safety_features: list[str]
    family_features: list[str]
    description: str


class BookingRequest(BaseModel):
    customer_name: str = Field(..., description="Full name of the customer")
    email: EmailStr
    phone: str
    model_id: str = Field(
        ...,
        description=(
            "Vehicle model, accepts natural names like 'Wrenfield Sedan', 'sedan', "
            "'Wrenfield SUV', or the exact ID 'suv-2026'/'sedan-2026'."
        ),
    )
    dealer_id: str = Field(
        ...,
        description=(
            "Dealer, accepts natural names like 'Melbourne CBD', 'Truganina', "
            "or the exact ID 'dealer-melbourne-cbd'."
        ),
    )
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
    "suv-2026": Vehicle(
        model_id="suv-2026", name="Wrenfield SUV", variant="2026",
        available_dealers=["dealer-melbourne-cbd", "dealer-truganina"],
        body_type="SUV", price_aud=58000, seats=5, range_km=480, drivetrain="AWD",
        safety_features=[
            "8 airbags including rear side-curtain coverage",
            "ISOFIX and top-tether child seat anchors on all rear seats",
            "Rear cross-traffic and blind-spot alert",
            "Autonomous emergency braking with pedestrian and cyclist detection",
            "360-degree parking camera",
            "5-star ANCAP safety rating",
        ],
        family_features=[
            "Rear seat sunshades and dual-zone rear climate control",
            "Low, wide door opening for easier baby seat access",
            "Hands-free power tailgate for stroller loading",
            "Rear seat reminder alert to prevent leaving a child in the car",
        ],
        description=(
            "The Wrenfield SUV is built for growing families who want space, "
            "visibility, and a strong active-safety package without stepping "
            "outside a mid-size budget."
        ),
    ),
    "sedan-2026": Vehicle(
        model_id="sedan-2026", name="Wrenfield Sedan", variant="2026",
        available_dealers=["dealer-melbourne-cbd"],
        body_type="Sedan", price_aud=46000, seats=5, range_km=520, drivetrain="RWD",
        safety_features=[
            "8 airbags including rear side-curtain coverage",
            "ISOFIX and top-tether child seat anchors on all rear seats",
            "Autonomous emergency braking with pedestrian and cyclist detection",
            "Lane-keep assist and driver attention monitoring",
            "Rear-view camera with parking sensors",
            "5-star ANCAP safety rating",
        ],
        family_features=[
            "Rear seat reminder alert to prevent leaving a child in the car",
            "Extra-long rear door aperture for easier newborn capsule access",
            "Quiet electric drivetrain reduces cabin noise for a sleeping baby",
        ],
        description=(
            "The Wrenfield Sedan is a family-friendly sedan with newborn-ready rear "
            "seat access, a full suite of active safety features, and an "
            "on-road price under $50,000, a strong fit for a first family car."
        ),
    ),
}

BOOKINGS: dict[str, BookingResult] = {}

# Natural-language aliases so agents/customers never need to know internal IDs.
# "aria" variants kept as legacy synonyms during the brand transition.
_MODEL_ALIASES: dict[str, str] = {
    "suv": "suv-2026", "wrenfield suv": "suv-2026", "the wrenfield suv": "suv-2026",
    "suv-2026": "suv-2026", "wrenfield suv 2026": "suv-2026",
    "aria suv": "suv-2026", "the aria suv": "suv-2026", "aria suv 2026": "suv-2026",
    "sedan": "sedan-2026", "wrenfield sedan": "sedan-2026", "the wrenfield sedan": "sedan-2026",
    "sedan-2026": "sedan-2026", "wrenfield sedan 2026": "sedan-2026",
    "aria sedan": "sedan-2026", "the aria sedan": "sedan-2026", "aria sedan 2026": "sedan-2026",
}

_DEALER_ALIASES: dict[str, str] = {
    "melbourne cbd": "dealer-melbourne-cbd", "melbourne": "dealer-melbourne-cbd",
    "cbd": "dealer-melbourne-cbd", "melbourne-cbd": "dealer-melbourne-cbd",
    "dealer-melbourne-cbd": "dealer-melbourne-cbd",
    "truganina": "dealer-truganina", "dealer-truganina": "dealer-truganina",
}


# ---------------------------------------------------------------------------
# Business logic functions (pure, testable, no framework dependency)
# ---------------------------------------------------------------------------

def list_vehicles() -> list[Vehicle]:
    return list(CATALOG.values())


def _normalize_model_id(model_id: str) -> str:
    key = re.sub(r"\s+", " ", model_id.strip().lower())
    if key in _MODEL_ALIASES:
        return _MODEL_ALIASES[key]
    # loose contains-match as a final fallback, e.g. "book the sedan please"
    for alias, resolved in _MODEL_ALIASES.items():
        if alias in key:
            return resolved
    raise ValueError(
        f"Unknown model: {model_id!r}. Try 'Wrenfield SUV' or 'Wrenfield Sedan'."
    )


def _normalize_dealer_id(dealer_id: str, model_id: str) -> str:
    key = re.sub(r"\s+", " ", dealer_id.strip().lower())
    valid = CATALOG[model_id].available_dealers
    resolved = _DEALER_ALIASES.get(key)
    if resolved is None:
        for alias, candidate in _DEALER_ALIASES.items():
            if alias in key:
                resolved = candidate
                break
    if resolved is None:
        raise ValueError(
            f"Unknown dealer: {dealer_id!r}. Try 'Melbourne CBD' or 'Truganina'."
        )
    if resolved not in valid:
        dealer_names = ", ".join(d.replace("dealer-", "").replace("-", " ").title() for d in valid)
        raise ValueError(
            f"{CATALOG[model_id].name} isn't available at that dealer. "
            f"Available at: {dealer_names}."
        )
    return resolved


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