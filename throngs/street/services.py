"""Service catalogs for service-based businesses (plumber, event organizer, CPA).

Replaces the product catalogs used by retail businesses.  Each business type
has a default set of services with rates.
"""
from __future__ import annotations

from throngs.street.models import ServiceLineItem

# ---------------------------------------------------------------------------
# Default service catalogs by business type
# ---------------------------------------------------------------------------

DEFAULT_SERVICES: dict[str, list[ServiceLineItem]] = {
    "plumber": [
        ServiceLineItem(service_name="Drain Clearing", rate=175.0, rate_type="flat"),
        ServiceLineItem(service_name="Pipe Repair", rate=95.0, quantity=2.0, rate_type="hourly"),
        ServiceLineItem(service_name="Water Heater Install", rate=1200.0, rate_type="flat"),
        ServiceLineItem(service_name="Faucet Replacement", rate=250.0, rate_type="flat"),
        ServiceLineItem(service_name="Emergency Call-out Fee", rate=150.0, rate_type="flat"),
        ServiceLineItem(service_name="Toilet Repair", rate=185.0, rate_type="flat"),
        ServiceLineItem(service_name="Sewer Line Inspection", rate=300.0, rate_type="flat"),
        ServiceLineItem(service_name="Garbage Disposal Install", rate=275.0, rate_type="flat"),
    ],
    "event_organizer": [
        ServiceLineItem(service_name="Wedding Reception Planning", rate=5000.0, rate_type="flat"),
        ServiceLineItem(service_name="Corporate Event", rate=3000.0, rate_type="flat"),
        ServiceLineItem(service_name="Birthday Party Package", rate=800.0, rate_type="flat"),
        ServiceLineItem(service_name="Event Consultation", rate=150.0, quantity=2.0, rate_type="hourly"),
        ServiceLineItem(service_name="Venue Coordination", rate=500.0, rate_type="flat"),
        ServiceLineItem(service_name="Catering Arrangement", rate=1200.0, rate_type="flat"),
        ServiceLineItem(service_name="Day-of Coordination", rate=1500.0, rate_type="flat"),
    ],
    "cpa": [
        ServiceLineItem(service_name="Tax Return (Individual)", rate=350.0, rate_type="flat"),
        ServiceLineItem(service_name="Tax Return (Business)", rate=750.0, rate_type="flat"),
        ServiceLineItem(service_name="Bookkeeping (monthly)", rate=200.0, rate_type="flat"),
        ServiceLineItem(service_name="Consultation", rate=175.0, quantity=1.0, rate_type="hourly"),
        ServiceLineItem(service_name="Audit Preparation", rate=150.0, quantity=4.0, rate_type="hourly"),
        ServiceLineItem(service_name="Payroll Processing", rate=125.0, rate_type="flat"),
        ServiceLineItem(service_name="QuickBooks Setup", rate=400.0, rate_type="flat"),
    ],
}


# ---------------------------------------------------------------------------
# Request type descriptions (used by arrival generator for realistic narratives)
# ---------------------------------------------------------------------------

REQUEST_TYPES: dict[str, list[dict[str, str]]] = {
    "plumber": [
        {"type": "emergency_repair", "description": "Kitchen sink won't drain, water backing up"},
        {"type": "emergency_repair", "description": "Burst pipe in the basement, water everywhere"},
        {"type": "emergency_repair", "description": "Toilet overflowing, can't shut the water off"},
        {"type": "scheduled_repair", "description": "Slow draining bathtub, been getting worse"},
        {"type": "scheduled_repair", "description": "Leaky faucet in the kitchen, dripping all day"},
        {"type": "installation", "description": "Need a new water heater installed, current one is 15 years old"},
        {"type": "installation", "description": "Want to replace all faucets in the master bath renovation"},
        {"type": "inspection", "description": "Buying a house, need a plumbing inspection"},
        {"type": "maintenance", "description": "Annual checkup on the water heater and pipes"},
    ],
    "event_organizer": [
        {"type": "wedding", "description": "Planning a wedding reception for 120 guests in October"},
        {"type": "wedding", "description": "Need help with a small intimate wedding for 30 people"},
        {"type": "corporate", "description": "Annual company holiday party for 200 employees"},
        {"type": "corporate", "description": "Product launch event, need AV and catering for 80"},
        {"type": "birthday", "description": "50th birthday party, want something special for 40 guests"},
        {"type": "birthday", "description": "Kids birthday party at the community center, 25 children"},
        {"type": "consultation", "description": "Not sure what we need yet, want to discuss options and budget"},
        {"type": "fundraiser", "description": "Charity gala fundraiser, 150 guests, silent auction"},
    ],
    "cpa": [
        {"type": "tax_individual", "description": "Need to file my personal taxes, have W-2 and some investments"},
        {"type": "tax_individual", "description": "Haven't filed in two years, need help catching up"},
        {"type": "tax_business", "description": "Small LLC needs annual tax return, first year in business"},
        {"type": "tax_business", "description": "S-Corp tax filing, about $500K revenue"},
        {"type": "bookkeeping", "description": "Behind on bookkeeping by 3 months, need to get caught up"},
        {"type": "bookkeeping", "description": "Looking for monthly bookkeeping services for my bakery"},
        {"type": "consultation", "description": "Thinking about incorporating, want tax advice"},
        {"type": "audit", "description": "Got a notice from the IRS, need help responding"},
        {"type": "payroll", "description": "Have 5 employees, need someone to handle payroll"},
    ],
}
