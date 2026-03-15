"""Street simulation data models."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, computed_field


_CUSTOMER_FIRST = [
    "Alice", "Brian", "Carol", "David", "Elena", "Frank", "Grace", "Henry",
    "Isabel", "James", "Karen", "Leo", "Maria", "Nathan", "Olivia", "Paul",
    "Quinn", "Rachel", "Steve", "Tina", "Uma", "Victor", "Wendy", "Xavier",
    "Yara", "Zach", "Anne", "Ben", "Clara", "Dan", "Eve", "Fred", "Gina",
    "Hank", "Iris", "Jack", "Kim", "Liam", "Mia", "Ned", "Ora", "Pete",
    "Rita", "Sam", "Tara", "Uri", "Val", "Walt", "Xena", "Yuki",
]
_CUSTOMER_LAST = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
    "White", "Harris", "Martin", "Thompson", "Young", "Allen", "King",
    "Wright", "Scott", "Green", "Baker", "Adams", "Nelson", "Carter",
    "Mitchell", "Roberts",
]


def random_customer_name(rng) -> str:
    return f"{rng.choice(_CUSTOMER_FIRST)} {rng.choice(_CUSTOMER_LAST)}"


class ProductItem(BaseModel):
    """A product or service sold by the shop."""
    sku: str
    name: str
    unit_price: float
    category: str = ""


class Purchase(BaseModel):
    """One line item in a customer order."""
    item_name: str
    quantity: int = 1
    unit_price: float

    @property
    def total(self) -> float:
        return round(self.quantity * self.unit_price, 2)


class Customer(BaseModel):
    """A simulated street customer visiting a specific shop."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    arrival_sim_time: datetime
    target_shop: str               # persona_name of the shop they want to visit
    purchases: list[Purchase] = Field(default_factory=list)
    payment_method: str = "card"   # "cash" | "card" | "invoice"
    delivery_required: bool = False
    delivery_address: str = ""
    state: str = "arriving"        # arriving | browsing | waiting_to_pay | billed | departed

    billed_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None

    @property
    def order_total(self) -> float:
        return round(sum(p.total for p in self.purchases), 2)

    @property
    def item_count(self) -> int:
        return sum(p.quantity for p in self.purchases)

    def billing_minutes(self) -> float:
        """Simulated minutes the shop owner must spend billing this customer."""
        base = 4.0 + self.item_count * 1.5
        if self.delivery_required:
            base += 12.0
        if self.payment_method == "invoice":
            base += 8.0
        return round(base, 1)

    def summary(self) -> str:
        items = ", ".join(f"{p.quantity}× {p.item_name}" for p in self.purchases[:3])
        suffix = f" (+{len(self.purchases)-3} more)" if len(self.purchases) > 3 else ""
        pay = f"paying by {self.payment_method}"
        deliv = ", needs delivery" if self.delivery_required else ""
        return f"{self.name} wants {items}{suffix} (${self.order_total:.2f}, {pay}{deliv})"


# ---------------------------------------------------------------------------
# Service business models (plumber, event organizer, CPA)
# ---------------------------------------------------------------------------

class ServiceLineItem(BaseModel):
    """One line item on an estimate or invoice for a service business."""
    service_name: str           # "Drain Clearing", "Wedding Reception Planning"
    rate: float                 # hourly rate or flat fee
    quantity: float = 1.0       # hours (if hourly) or units (if flat)
    rate_type: str = "flat"     # "hourly" | "flat"

    @property
    def total(self) -> float:
        return round(self.rate * self.quantity, 2)


class ServiceRequest(BaseModel):
    """A service inquiry from a client — the service-business equivalent of Customer.

    Lifecycle::

        inquiry → estimate_sent → accepted → in_progress →
        invoice_sent → paid → closed

    Or: inquiry → estimate_sent → rejected → closed
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    client_name: str
    contact_method: str = "phone"       # "phone" | "email"
    request_type: str = ""              # "emergency_repair", "wedding", "tax_individual", etc.
    description: str = ""               # "Kitchen sink won't drain, water backing up"
    urgency: str = "normal"             # "urgent" | "normal" | "low"
    estimated_value: float = 0.0        # approximate job value
    state: str = "inquiry"              # inquiry | estimate_sent | accepted | rejected |
                                        # in_progress | invoice_sent | paid | closed
    services: list[ServiceLineItem] = Field(default_factory=list)
    inquiry_sim_time: Optional[datetime] = None
    estimate_sent_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    invoice_sent_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    target_business: str = ""           # persona_name of the business they contacted

    @property
    def line_total(self) -> float:
        return round(sum(s.total for s in self.services), 2)

    def handling_minutes(self) -> float:
        """Simulated minutes the owner spends creating an estimate for this request."""
        base = 5.0
        base += len(self.services) * 3.0
        if self.urgency == "urgent":
            base += 2.0  # rushed, more pressure
        if self.contact_method == "email":
            base += 3.0  # reading the email, composing reply
        return round(base, 1)

    def summary(self) -> str:
        method = "called" if self.contact_method == "phone" else "emailed"
        svc_names = ", ".join(s.service_name for s in self.services[:2])
        suffix = f" (+{len(self.services)-2} more)" if len(self.services) > 2 else ""
        value = f"${self.estimated_value:.0f} est." if self.estimated_value else "value TBD"
        return f"{self.client_name} {method} about {svc_names}{suffix} ({value})"


class BankTransaction(BaseModel):
    """A single money movement through the bank."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    sim_time: datetime
    amount: float                  # positive = deposit, negative = debit
    description: str
    source: str                    # "customer_payment" | "supplier_bill" | "bank_fee" | "payroll"
    customer_id: Optional[str] = None
    recorded_in_app: bool = False  # True only once the owner logs it in the accounting app


class StreetEvent(BaseModel):
    """An event emitted by the street simulation."""
    event_type: str                # "customer_arrival" | "phone_call" | "email_inquiry" | etc.
    sim_time: datetime
    shop_name: str
    customer: Optional[Customer] = None
    service_request: Optional[ServiceRequest] = None
    narrative: str = ""
    blocks_owner_minutes: float = 0.0
    financial_impact: float = 0.0  # amount received or spent
