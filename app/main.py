"""
REST API for the Test Drive Booking GPT app.

This is what you point a Custom GPT's "Actions" at.
FastAPI auto-generates an OpenAPI 3.1 schema at /openapi.json,
which you paste (or import via URL) into the GPT Builder's
Actions -> "Import from URL" field.

Run locally:
    uvicorn app.main:app --reload --port 8000

Then deploy (Render/Fly.io/Cloud Run/Azure App Service/etc.) so it has
a public HTTPS URL, GPT Actions require HTTPS with a valid cert.
"""

from fastapi import FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import os
import time
from collections import defaultdict

from . import booking_logic as logic

API_KEY = os.environ.get("GPT_ACTION_API_KEY", "changeme-set-a-real-secret")
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

app = FastAPI(
    title="Test Drive Booking API",
    description="Book, check, and manage vehicle test drives.",
    version="1.0.0",
    servers=[{"url": "https://aria-gpt-app.onrender.com"}],
)

# Public site (any origin, since this serves real end customers directly in
# their browser). Tighten allow_origins to your real domain once you have one.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def verify_key(auth_header: str = Security(api_key_header)):
    # GPT Actions sends "Authorization: Bearer <key>" if you configure API Key auth
    expected = f"Bearer {API_KEY}"
    if auth_header != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True


@app.get("/vehicles", response_model=List[logic.Vehicle], operation_id="listVehicles")
def list_vehicles(_auth: bool = Security(verify_key)):
    """List all vehicle models available for test drives."""
    return logic.list_vehicles()


@app.get("/availability", operation_id="checkAvailability")
def check_availability(model_id: str, dealer_id: str, datetime_iso: str,
                        _auth: bool = Security(verify_key)):
    """Check whether a given model/dealer/time slot is available."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(datetime_iso)
        available = logic.check_availability(model_id, dealer_id, dt)
        return {"available": available}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/bookings", response_model=logic.BookingResult, operation_id="createBooking")
def create_booking(req: logic.BookingRequest, _auth: bool = Security(verify_key)):
    """Create a new test drive booking."""
    try:
        return logic.create_booking(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/bookings/{booking_id}", response_model=logic.BookingResult, operation_id="getBooking")
def get_booking(booking_id: str, _auth: bool = Security(verify_key)):
    """Retrieve details of an existing booking."""
    try:
        return logic.get_booking(booking_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/bookings/{booking_id}", response_model=logic.BookingResult, operation_id="cancelBooking")
def cancel_booking(booking_id: str, _auth: bool = Security(verify_key)):
    """Cancel an existing booking."""
    try:
        return logic.cancel_booking(booking_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Public website endpoints, no API key required.
# These serve real end customers directly (public site, no ChatGPT/Claude
# involved), so they're open by design. A lightweight IP-based rate limit
# guards against booking spam since there's no per-user auth here.
# ---------------------------------------------------------------------------

_booking_attempts: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW_SECONDS = 300
RATE_LIMIT_MAX_ATTEMPTS = 5


def _check_rate_limit(client_ip: str):
    now = time.time()
    attempts = _booking_attempts[client_ip]
    attempts[:] = [t for t in attempts if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(attempts) >= RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many booking attempts. Please try again in a few minutes.",
        )
    attempts.append(now)


@app.get("/public/vehicles", response_model=List[logic.Vehicle])
def public_list_vehicles():
    """List all vehicle models available for test drives (public, no auth)."""
    return logic.list_vehicles()


@app.get("/public/availability")
def public_check_availability(model_id: str, dealer_id: str, datetime_iso: str):
    """Check slot availability (public, no auth)."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(datetime_iso)
        return {"available": logic.check_availability(model_id, dealer_id, dt)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


from fastapi import Request


@app.post("/public/bookings", response_model=logic.BookingResult)
def public_create_booking(req: logic.BookingRequest, request: Request):
    """Create a booking from the public website (public, no auth, rate-limited)."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)
    try:
        return logic.create_booking(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))