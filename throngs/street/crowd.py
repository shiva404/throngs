"""Time-based crowd simulation — arrival rates vary by hour and shop type."""
from __future__ import annotations

import math
import random

# Foot-traffic multiplier by hour-of-day (0-23).  1.0 = average rate.
FOOT_TRAFFIC_BY_HOUR: dict[int, float] = {
    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0,
    6: 0.05, 7: 0.2, 8: 0.6, 9: 1.0,
    10: 1.1, 11: 1.4, 12: 1.6, 13: 1.3,
    14: 0.9, 15: 1.1, 16: 1.4, 17: 1.0,
    18: 0.5, 19: 0.2, 20: 0.1, 21: 0.0, 22: 0.0, 23: 0.0,
}

# Base customer arrivals per simulated hour (at 1.0 multiplier).
# Set so expected arrivals per 30 min ≈ 2; hard cap of 2 per 30 min in simulation limits to 1–2.
BASE_ARRIVALS_PER_HOUR: dict[str, float] = {
    "bakery":     4.0,
    "bookstore":  4.0,
    "cafe":       4.0,
    "florist":    4.0,
    "cpa":        2.0,   # mostly appointment-based
    "accounting": 2.0,
    "retail":     4.0,
    "default":    4.0,
}

# Probability a purchase requires delivery (0-1).
DELIVERY_PROBABILITY: dict[str, float] = {
    "bakery":     0.10,   # catering orders
    "bookstore":  0.15,   # online / mail orders
    "florist":    0.30,   # event/funeral delivery
    "cafe":       0.05,
    "cpa":        0.00,
    "accounting": 0.00,
    "retail":     0.12,
    "default":    0.08,
}

# Payment method distribution per shop type: [cash%, card%, invoice%]
PAYMENT_MIX: dict[str, tuple[float, float, float]] = {
    "bakery":     (0.40, 0.55, 0.05),
    "bookstore":  (0.20, 0.70, 0.10),
    "cafe":       (0.30, 0.70, 0.00),
    "florist":    (0.25, 0.60, 0.15),
    "cpa":        (0.05, 0.30, 0.65),
    "accounting": (0.05, 0.30, 0.65),
    "retail":     (0.25, 0.65, 0.10),
    "default":    (0.25, 0.65, 0.10),
}


def arrivals_in_window(
    shop_type: str,
    sim_hour: int,
    sim_minutes_elapsed: float,
    rng: random.Random,
) -> int:
    """Return random customer arrivals for a sim-minute window (Poisson draw)."""
    multiplier = FOOT_TRAFFIC_BY_HOUR.get(sim_hour, 0.0)
    base = BASE_ARRIVALS_PER_HOUR.get(shop_type, BASE_ARRIVALS_PER_HOUR["default"])
    rate_per_minute = (base * multiplier) / 60.0
    lam = rate_per_minute * sim_minutes_elapsed
    return _poisson(lam, rng)


def pick_payment_method(shop_type: str, rng: random.Random) -> str:
    cash_p, card_p, inv_p = PAYMENT_MIX.get(shop_type, PAYMENT_MIX["default"])
    r = rng.random()
    if r < cash_p:
        return "cash"
    if r < cash_p + card_p:
        return "card"
    return "invoice"


def delivery_required(shop_type: str, rng: random.Random) -> bool:
    p = DELIVERY_PROBABILITY.get(shop_type, DELIVERY_PROBABILITY["default"])
    return rng.random() < p


def _poisson(lam: float, rng: random.Random) -> int:
    if lam <= 0:
        return 0
    l_val = math.exp(-lam)
    k, p = 0, 1.0
    while p > l_val:
        k += 1
        p *= rng.random()
    return k - 1


# ===================================================================
# Service business models — phone calls & email inquiries
# ===================================================================

# Phone calls per hour by business type (at 1.0 multiplier)
PHONE_CALL_RATE: dict[str, float] = {
    "plumber": 2.5,           # emergencies + scheduled
    "event_organizer": 1.5,   # inquiries, follow-ups
    "cpa": 1.0,               # mostly scheduled
    "default": 1.5,
}

# Email inquiries per hour by business type (at 1.0 multiplier)
EMAIL_INQUIRY_RATE: dict[str, float] = {
    "plumber": 1.5,
    "event_organizer": 3.0,   # lots of email inquiries
    "cpa": 2.0,               # client communications
    "default": 2.0,
}

# Phone call time-of-day multiplier (different pattern from foot traffic).
# Emergency plumbing calls can come early/late; scheduled calls cluster morning.
PHONE_TRAFFIC_BY_HOUR: dict[int, float] = {
    0: 0.05, 1: 0.02, 2: 0.02, 3: 0.02, 4: 0.02, 5: 0.1,
    6: 0.3, 7: 0.6, 8: 1.2, 9: 1.5, 10: 1.3, 11: 1.0,
    12: 0.7, 13: 0.8, 14: 0.9, 15: 0.8, 16: 0.6, 17: 0.3,
    18: 0.2, 19: 0.1, 20: 0.05, 21: 0.02, 22: 0.02, 23: 0.02,
}

# Email time-of-day multiplier — people send emails during work hours mostly.
EMAIL_TRAFFIC_BY_HOUR: dict[int, float] = {
    0: 0.02, 1: 0.01, 2: 0.01, 3: 0.01, 4: 0.01, 5: 0.05,
    6: 0.2, 7: 0.5, 8: 1.0, 9: 1.4, 10: 1.3, 11: 1.2,
    12: 0.8, 13: 1.0, 14: 1.1, 15: 1.0, 16: 0.8, 17: 0.5,
    18: 0.3, 19: 0.2, 20: 0.1, 21: 0.05, 22: 0.02, 23: 0.02,
}

# Urgency distribution for phone calls: [urgent%, normal%, low%]
PHONE_URGENCY_MIX: dict[str, tuple[float, float, float]] = {
    "plumber": (0.40, 0.45, 0.15),       # plumbers get lots of emergencies
    "event_organizer": (0.10, 0.60, 0.30),
    "cpa": (0.15, 0.55, 0.30),           # IRS deadline = urgent
    "default": (0.20, 0.50, 0.30),
}


def phone_calls_in_window(
    business_type: str,
    sim_hour: int,
    sim_minutes_elapsed: float,
    rng: random.Random,
) -> int:
    """Return random phone calls for a sim-minute window (Poisson draw)."""
    multiplier = PHONE_TRAFFIC_BY_HOUR.get(sim_hour, 0.0)
    base = PHONE_CALL_RATE.get(business_type, PHONE_CALL_RATE["default"])
    rate_per_minute = (base * multiplier) / 60.0
    lam = rate_per_minute * sim_minutes_elapsed
    return _poisson(lam, rng)


def email_inquiries_in_window(
    business_type: str,
    sim_hour: int,
    sim_minutes_elapsed: float,
    rng: random.Random,
) -> int:
    """Return random email inquiries for a sim-minute window (Poisson draw)."""
    multiplier = EMAIL_TRAFFIC_BY_HOUR.get(sim_hour, 0.0)
    base = EMAIL_INQUIRY_RATE.get(business_type, EMAIL_INQUIRY_RATE["default"])
    rate_per_minute = (base * multiplier) / 60.0
    lam = rate_per_minute * sim_minutes_elapsed
    return _poisson(lam, rng)


def pick_phone_urgency(business_type: str, rng: random.Random) -> str:
    """Pick urgency level for a phone call based on business type."""
    urgent_p, normal_p, _ = PHONE_URGENCY_MIX.get(
        business_type, PHONE_URGENCY_MIX["default"]
    )
    r = rng.random()
    if r < urgent_p:
        return "urgent"
    if r < urgent_p + normal_p:
        return "normal"
    return "low"
