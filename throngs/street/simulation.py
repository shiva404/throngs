"""StreetSimulation — manages one or more shops on a simulated street.

A ``ShopConfig`` describes one shop.  ``StreetSimulation.tick()`` advances
time, generates customer arrivals (Poisson-distributed, time-of-day adjusted),
moves customers through: arriving → browsing → waiting_to_pay → billed → departed,
and emits ``StreetEvent`` objects that the agent runtime consumes as context.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Optional

from throngs.street.bank import BankAccount
from throngs.street.crowd import (
    arrivals_in_window,
    delivery_required,
    email_inquiries_in_window,
    phone_calls_in_window,
    pick_payment_method,
    pick_phone_urgency,
)
from throngs.street.models import (
    Customer,
    ProductItem,
    Purchase,
    ServiceLineItem,
    ServiceRequest,
    StreetEvent,
    random_customer_name,
)

logger = logging.getLogger(__name__)

# Default product catalogs per shop type
_DEFAULT_PRODUCTS: dict[str, list[dict]] = {
    "bakery": [
        {"sku": "SOD01", "name": "Sourdough Loaf",    "unit_price": 8.50,  "category": "bread"},
        {"sku": "CRO01", "name": "Butter Croissant",   "unit_price": 3.50,  "category": "pastry"},
        {"sku": "CRO02", "name": "Almond Croissant",   "unit_price": 4.25,  "category": "pastry"},
        {"sku": "MUF01", "name": "Blueberry Muffin",   "unit_price": 3.00,  "category": "pastry"},
        {"sku": "COF01", "name": "Filter Coffee",      "unit_price": 2.75,  "category": "drinks"},
        {"sku": "CAK01", "name": "Slice of Cake",      "unit_price": 5.00,  "category": "cake"},
        {"sku": "CAT01", "name": "Catering Box (12)",  "unit_price": 36.00, "category": "catering"},
    ],
    "bookstore": [
        {"sku": "FIC01", "name": "Fiction Novel",      "unit_price": 14.99, "category": "fiction"},
        {"sku": "NFC01", "name": "Non-Fiction Book",   "unit_price": 18.99, "category": "non-fiction"},
        {"sku": "CHI01", "name": "Children's Book",    "unit_price": 9.99,  "category": "children"},
        {"sku": "COO01", "name": "Cookbook",           "unit_price": 24.99, "category": "cooking"},
        {"sku": "GFT01", "name": "Gift Card ($25)",    "unit_price": 25.00, "category": "gift"},
        {"sku": "MAP01", "name": "Local Map / Guide",  "unit_price": 7.99,  "category": "reference"},
    ],
    "florist": [
        {"sku": "BQT01", "name": "Mixed Bouquet",      "unit_price": 24.99, "category": "flowers"},
        {"sku": "BQT02", "name": "Rose Dozen",         "unit_price": 39.99, "category": "flowers"},
        {"sku": "POT01", "name": "Potted Plant",       "unit_price": 18.99, "category": "plants"},
        {"sku": "ARR01", "name": "Floral Arrangement", "unit_price": 59.99, "category": "arrangement"},
        {"sku": "EVT01", "name": "Event Flowers",      "unit_price": 249.99,"category": "event"},
    ],
    "cafe": [
        {"sku": "ESP01", "name": "Espresso",           "unit_price": 2.50,  "category": "coffee"},
        {"sku": "LAT01", "name": "Latte",              "unit_price": 4.50,  "category": "coffee"},
        {"sku": "SAN01", "name": "Sandwich",           "unit_price": 7.50,  "category": "food"},
        {"sku": "CAK01", "name": "Slice of Cake",      "unit_price": 4.75,  "category": "food"},
    ],
    "cpa": [
        {"sku": "CON01", "name": "Consultation (1hr)", "unit_price": 150.00,"category": "service"},
        {"sku": "TAX01", "name": "Tax Return",         "unit_price": 350.00,"category": "service"},
        {"sku": "BKP01", "name": "Bookkeeping (mo.)",  "unit_price": 200.00,"category": "service"},
    ],
    "accounting": [
        {"sku": "CON01", "name": "Consultation (1hr)", "unit_price": 125.00,"category": "service"},
        {"sku": "REC01", "name": "Reconciliation",     "unit_price": 175.00,"category": "service"},
        {"sku": "PAY01", "name": "Payroll Processing", "unit_price": 95.00, "category": "service"},
    ],
}
_DEFAULT_PRODUCTS["retail"] = [
    {"sku": "GEN01", "name": "General Item",       "unit_price": 12.99, "category": "general"},
    {"sku": "GEN02", "name": "Premium Item",       "unit_price": 29.99, "category": "general"},
]


def _infer_shop_type(persona_name: str, persona_description: str = "") -> str:
    """Guess shop type from persona name and/or description.

    Order matters: more-specific terms are checked before shorter substrings
    (e.g. "bookkeeper" before "book" to avoid misclassifying accountants as
    bookstore owners).
    """
    low = (persona_name + " " + persona_description).lower()
    # --- check unambiguous accounting roles first ---
    if "cpa" in low:
        return "cpa"
    if any(w in low for w in ("bookkeeper", "bookkeep", "accountant", "accounting", "quickbook")):
        return "accounting"
    # --- retail / food ---
    if any(w in low for w in ("baker", "bakery", "bread", "pastry", "baked")):
        return "bakery"
    if any(w in low for w in ("florist", "flower", "floral")):
        return "florist"
    if any(w in low for w in ("cafe", "coffee", "barista", "espresso")):
        return "cafe"
    if any(w in low for w in ("bookstore", "book shop", "book store", "library", "novel", "publisher")):
        return "bookstore"
    if any(w in low for w in ("plumb", "pipe", "drain", "hvac")):
        return "plumber"
    if any(w in low for w in ("event", "wedding", "party", "organiz")):
        return "event_organizer"
    if any(w in low for w in ("contractor", "tradesperson", "construct")):
        return "plumber"  # general contractors use similar workflow
    return "retail"

# Business types that use the service model (phone calls + email) vs retail (walk-ins)
SERVICE_BUSINESS_TYPES = {"plumber", "event_organizer", "cpa"}


class ShopConfig:
    """Configuration for one shop/business on the street."""

    def __init__(
        self,
        persona_name: str,
        shop_type: Optional[str] = None,
        persona_description: str = "",
        products: Optional[list[ProductItem]] = None,
        opening_hour: int = 8,
        closing_hour: int = 18,
        initial_bank_balance: float = 5_000.0,
        shop_label: str = "",
    ) -> None:
        self.persona_name = persona_name
        self.shop_type = shop_type or _infer_shop_type(persona_name, persona_description)
        self.business_model = "service" if self.shop_type in SERVICE_BUSINESS_TYPES else "retail"
        raw = products or [
            ProductItem(**p)
            for p in _DEFAULT_PRODUCTS.get(self.shop_type, _DEFAULT_PRODUCTS.get("retail", []))
        ]
        self.products: list[ProductItem] = raw
        self.opening_hour = opening_hour
        self.closing_hour = closing_hour
        self.initial_bank_balance = initial_bank_balance
        self.shop_label = shop_label or persona_name


class ShopState:
    """Runtime state for a single shop/business during a simulation run."""

    def __init__(self, config: ShopConfig, rng: random.Random) -> None:
        self.config = config
        self.bank = BankAccount(
            initial_balance=config.initial_bank_balance,
            account_name=f"{config.shop_label} — Business Checking",
        )
        self._queue: list[Customer] = []   # customers currently on premises (retail)
        self._departed: list[Customer] = []
        self._events: list[StreetEvent] = []
        self._rng = rng
        self._pending_customer_events: list[StreetEvent] = []  # ready for distraction engine

        # --- Service business state ---
        self._service_requests: list[ServiceRequest] = []      # all requests (any state)
        self._pending_phone_calls: list[StreetEvent] = []      # unhandled calls (CRITICAL)
        self._pending_emails: list[StreetEvent] = []           # unread emails (NORMAL)

        # --- Retail: cap at 2 customers per 30-minute window ---
        self._arrival_times: list[datetime] = []

    # ------------------------------------------------------------------
    # Retail helpers
    # ------------------------------------------------------------------

    def customers_waiting(self) -> list[Customer]:
        return [c for c in self._queue if c.state == "waiting_to_pay"]

    def customers_browsing(self) -> list[Customer]:
        return [c for c in self._queue if c.state == "browsing"]

    def served_today(self) -> int:
        return len(self._departed)

    def pop_pending_events(self) -> list[StreetEvent]:
        evts = list(self._pending_customer_events)
        self._pending_customer_events.clear()
        return evts

    # ------------------------------------------------------------------
    # Service business helpers
    # ------------------------------------------------------------------

    def pop_pending_phone_calls(self) -> list[StreetEvent]:
        """Return and clear unhandled phone call events (CRITICAL priority)."""
        calls = list(self._pending_phone_calls)
        self._pending_phone_calls.clear()
        return calls

    def pop_pending_emails(self) -> list[StreetEvent]:
        """Return and clear unread email inquiry events (NORMAL priority)."""
        emails = list(self._pending_emails)
        self._pending_emails.clear()
        return emails

    def unread_email_count(self) -> int:
        return len(self._pending_emails)

    def active_service_requests(self) -> list[ServiceRequest]:
        """Requests that need attention (not closed/rejected/paid)."""
        return [r for r in self._service_requests if r.state not in ("closed", "rejected", "paid")]

    def requests_needing_estimate(self) -> list[ServiceRequest]:
        return [r for r in self._service_requests if r.state == "inquiry"]

    def requests_needing_invoice(self) -> list[ServiceRequest]:
        return [r for r in self._service_requests if r.state == "in_progress"]

    def outstanding_invoices(self) -> list[ServiceRequest]:
        return [r for r in self._service_requests if r.state == "invoice_sent"]

    def receive_phone_call(self, sim_time: datetime) -> ServiceRequest:
        """Generate a phone call from a new client."""
        from throngs.street.services import DEFAULT_SERVICES, REQUEST_TYPES

        cfg = self.config
        svc_catalog = DEFAULT_SERVICES.get(cfg.shop_type, [])
        req_types = REQUEST_TYPES.get(cfg.shop_type, [])

        # Pick a random request type
        req_info = self._rng.choice(req_types) if req_types else {"type": "general", "description": "General inquiry"}

        # Pick 1-3 services
        n_services = min(self._rng.randint(1, 3), len(svc_catalog)) if svc_catalog else 0
        chosen_services = self._rng.sample(svc_catalog, n_services) if n_services > 0 else []

        urgency = pick_phone_urgency(cfg.shop_type, self._rng)
        est_value = sum(s.total for s in chosen_services)

        request = ServiceRequest(
            client_name=random_customer_name(self._rng),
            contact_method="phone",
            request_type=req_info["type"],
            description=req_info["description"],
            urgency=urgency,
            estimated_value=est_value,
            services=chosen_services,
            inquiry_sim_time=sim_time,
            target_business=cfg.persona_name,
        )
        self._service_requests.append(request)

        urgency_label = " (URGENT)" if urgency == "urgent" else ""
        evt = StreetEvent(
            event_type="phone_call",
            sim_time=sim_time,
            shop_name=cfg.persona_name,
            service_request=request,
            narrative=(
                f"Your phone rings{urgency_label}. It's {request.client_name} — "
                f"{request.description}"
            ),
            blocks_owner_minutes=request.handling_minutes(),
            financial_impact=est_value,
        )
        self._events.append(evt)
        self._pending_phone_calls.append(evt)
        logger.info(
            "[%s] Phone call from %s: %s (%s, $%.0f est.)",
            cfg.persona_name, request.client_name, request.request_type,
            urgency, est_value,
        )
        return request

    def receive_email_inquiry(self, sim_time: datetime) -> ServiceRequest:
        """Generate an email inquiry from a new client."""
        from throngs.street.services import DEFAULT_SERVICES, REQUEST_TYPES

        cfg = self.config
        svc_catalog = DEFAULT_SERVICES.get(cfg.shop_type, [])
        req_types = REQUEST_TYPES.get(cfg.shop_type, [])

        req_info = self._rng.choice(req_types) if req_types else {"type": "general", "description": "General inquiry"}

        n_services = min(self._rng.randint(1, 2), len(svc_catalog)) if svc_catalog else 0
        chosen_services = self._rng.sample(svc_catalog, n_services) if n_services > 0 else []
        est_value = sum(s.total for s in chosen_services)

        request = ServiceRequest(
            client_name=random_customer_name(self._rng),
            contact_method="email",
            request_type=req_info["type"],
            description=req_info["description"],
            urgency="normal",
            estimated_value=est_value,
            services=chosen_services,
            inquiry_sim_time=sim_time,
            target_business=cfg.persona_name,
        )
        self._service_requests.append(request)

        evt = StreetEvent(
            event_type="email_inquiry",
            sim_time=sim_time,
            shop_name=cfg.persona_name,
            service_request=request,
            narrative=(
                f"New email from {request.client_name}: "
                f"'{request.description}'"
            ),
            blocks_owner_minutes=0.0,  # emails don't block — persona checks at leisure
            financial_impact=est_value,
        )
        self._events.append(evt)
        self._pending_emails.append(evt)
        logger.debug(
            "[%s] Email inquiry from %s: %s ($%.0f est.)",
            cfg.persona_name, request.client_name, request.request_type, est_value,
        )
        return request

    # ------------------------------------------------------------------

    def arrive(self, sim_time: datetime) -> Optional[Customer]:
        """Generate a new customer and add them to the shop queue. Returns None if capped (max 2 per 30 min)."""
        # Cap: at most 2 arrivals in any 30-minute window
        cutoff = sim_time - timedelta(minutes=30)
        self._arrival_times = [t for t in self._arrival_times if t > cutoff]
        if len(self._arrival_times) >= 2:
            return None

        cfg = self.config
        # Pick random items
        item_count = self._rng.randint(1, min(4, len(cfg.products)))
        chosen = self._rng.sample(cfg.products, item_count)
        purchases = [
            Purchase(
                item_name=p.name,
                quantity=self._rng.randint(1, 3),
                unit_price=p.unit_price,
            )
            for p in chosen
        ]
        customer = Customer(
            name=random_customer_name(self._rng),
            arrival_sim_time=sim_time,
            target_shop=cfg.persona_name,
            purchases=purchases,
            payment_method=pick_payment_method(cfg.shop_type, self._rng),
            delivery_required=delivery_required(cfg.shop_type, self._rng),
            state="arriving",
        )
        self._queue.append(customer)

        evt = StreetEvent(
            event_type="customer_arrival",
            sim_time=sim_time,
            shop_name=cfg.persona_name,
            customer=customer,
            narrative=(
                f"{customer.name} walks into {cfg.shop_label}. "
                f"They want to buy: {customer.summary().split('wants ')[1]}."
            ),
            blocks_owner_minutes=0.0,  # not blocking yet — they're browsing
        )
        self._events.append(evt)
        self._arrival_times.append(sim_time)
        logger.debug(
            "[%s] +1 customer: %s (state=arriving, total=%d)",
            cfg.persona_name, customer.name, len(self._queue),
        )
        return customer

    def advance_customers(self, sim_time: datetime) -> None:
        """Move customers through their states; emit events when ready to pay."""
        cfg = self.config
        for c in list(self._queue):
            if c.state == "arriving":
                c.state = "browsing"

            # Note: intentionally `if` not `elif` — a customer who just became
            # "browsing" this tick can also immediately decide to pay (models a
            # large elapsed sim-time window where they arrived and finished
            # browsing within the same tick).
            if c.state == "browsing":
                # Chance they're now ready to pay (modelled as ~5 sim-min browse time)
                if self._rng.random() < 0.4:
                    c.state = "waiting_to_pay"
                    evt = StreetEvent(
                        event_type="customer_ready_to_pay",
                        sim_time=sim_time,
                        shop_name=cfg.persona_name,
                        customer=c,
                        narrative=(
                            f"{c.name} has finished browsing and is waiting at the counter "
                            f"to pay for {c.summary().split('wants ')[1]}."
                        ),
                        blocks_owner_minutes=c.billing_minutes(),
                        financial_impact=c.order_total,
                    )
                    self._events.append(evt)
                    self._pending_customer_events.append(evt)

    def bill_customer(self, customer: Customer, sim_time: datetime) -> StreetEvent:
        """Owner completes billing — money moves to bank (unrecorded)."""
        customer.state = "billed"
        customer.billed_at = sim_time
        customer.paid_at = sim_time

        txn = self.bank.receive_payment(
            amount=customer.order_total,
            description=(
                f"{customer.name} — {', '.join(p.item_name for p in customer.purchases[:2])}"
                + (" ..." if len(customer.purchases) > 2 else "")
            ),
            sim_time=sim_time,
            source="customer_payment",
            customer_id=customer.id,
        )
        self._queue.remove(customer)
        self._departed.append(customer)

        evt = StreetEvent(
            event_type="customer_billed",
            sim_time=sim_time,
            shop_name=self.config.persona_name,
            customer=customer,
            narrative=(
                f"{customer.name} paid ${customer.order_total:.2f} "
                f"by {customer.payment_method}."
                + (f" Delivery to {customer.delivery_address or 'their address'} arranged."
                   if customer.delivery_required else "")
            ),
            blocks_owner_minutes=customer.billing_minutes(),
            financial_impact=customer.order_total,
        )
        self._events.append(evt)
        logger.info(
            "[%s] Billed %s — $%.2f (%s). Bank unrecorded: $%.2f",
            self.config.persona_name, customer.name, customer.order_total,
            customer.payment_method, self.bank.unrecorded_cash,
        )
        return evt

    def world_state_snapshot(self) -> dict:
        """Snapshot for goal-synthesis world_state_dict."""
        snap = self.bank.world_state_snapshot()

        if self.config.business_model == "service":
            # Service business world state
            outstanding = self.outstanding_invoices()
            outstanding_amount = sum(r.estimated_value for r in outstanding)
            snap.update({
                "business_model": "service",
                "pending_phone_calls": len(self._pending_phone_calls),
                "unread_email_inquiries": len(self._pending_emails),
                "estimates_to_send": len(self.requests_needing_estimate()),
                "invoices_to_send": len(self.requests_needing_invoice()),
                "outstanding_invoices": len(outstanding),
                "outstanding_amount": round(outstanding_amount, 2),
                "total_active_requests": len(self.active_service_requests()),
            })
        else:
            # Retail walk-in business world state
            snap.update({
                "business_model": "retail",
                "customers_served_today": self.served_today(),
                "customers_waiting_to_pay": len(self.customers_waiting()),
                "customers_browsing": len(self.customers_browsing()),
                "todays_sales": self.bank.todays_receipts,
            })
        return snap


class StreetSimulation:
    """Manages a street with one or more shops, advancing time and generating events.

    Usage::

        sim = StreetSimulation([ShopConfig("Linda_Small_Biz_Owner")])
        events = sim.tick(get_clock().now())
        world_state = sim.world_state_for_persona("Linda_Small_Biz_Owner")
    """

    def __init__(
        self,
        shops: list[ShopConfig],
        rng_seed: Optional[int] = None,
    ) -> None:
        self._rng = random.Random(rng_seed)
        self._shops: dict[str, ShopState] = {
            cfg.persona_name: ShopState(cfg, random.Random(self._rng.randint(0, 2**32)))
            for cfg in shops
        }
        self._last_tick: Optional[datetime] = None

    # ------------------------------------------------------------------

    def tick(self, sim_now: datetime) -> list[StreetEvent]:
        """Advance all shops to ``sim_now`` and return new events."""
        all_events: list[StreetEvent] = []

        if self._last_tick is None:
            self._last_tick = sim_now
            return all_events

        elapsed_minutes = (sim_now - self._last_tick).total_seconds() / 60.0
        if elapsed_minutes <= 0:
            return all_events

        sim_hour = sim_now.hour
        events_before = 0

        for shop_state in self._shops.values():
            cfg = shop_state.config
            events_before = len(shop_state._events)

            # Skip outside opening hours
            if not (cfg.opening_hour <= sim_hour < cfg.closing_hour):
                continue

            if cfg.business_model == "service":
                # --- Service business: phone calls + email inquiries ---
                n_calls = phone_calls_in_window(
                    cfg.shop_type, sim_hour, elapsed_minutes, self._rng
                )
                for _ in range(n_calls):
                    shop_state.receive_phone_call(sim_now)

                n_emails = email_inquiries_in_window(
                    cfg.shop_type, sim_hour, elapsed_minutes, self._rng
                )
                for _ in range(n_emails):
                    shop_state.receive_email_inquiry(sim_now)

                # Advance service request states (auto-progress for simulation)
                self._advance_service_requests(shop_state, sim_now)

            else:
                # --- Retail business: walk-in customers ---
                n_arrivals = arrivals_in_window(
                    cfg.shop_type, sim_hour, elapsed_minutes, self._rng
                )
                for _ in range(n_arrivals):
                    shop_state.arrive(sim_now)

                shop_state.advance_customers(sim_now)

                # Auto-bill any waiting customers (owner handles them)
                for waiting in shop_state.customers_waiting():
                    shop_state.bill_customer(waiting, sim_now)

            all_events.extend(shop_state._events[events_before:])

        self._last_tick = sim_now
        return all_events

    def _advance_service_requests(self, shop: ShopState, sim_now: datetime) -> None:
        """Auto-advance service requests through their lifecycle.

        This simulates the passage of time — estimates get accepted,
        jobs get completed, invoices get paid — so the persona always
        has a realistic pipeline of work. The persona's QB tasks are
        about *recording* these transitions, not causing them.
        """
        for req in shop._service_requests:
            r = shop._rng.random()

            if req.state == "estimate_sent" and r < 0.15:
                # Client accepts the estimate
                if shop._rng.random() < 0.85:
                    req.state = "accepted"
                    req.accepted_at = sim_now
                else:
                    req.state = "rejected"

            elif req.state == "accepted" and r < 0.10:
                # Job progresses to in-progress
                req.state = "in_progress"

            elif req.state == "in_progress" and r < 0.08:
                # Job completes — persona needs to send invoice
                req.state = "invoice_sent"
                req.invoice_sent_at = sim_now

            elif req.state == "invoice_sent" and r < 0.06:
                # Client pays
                req.state = "paid"
                req.paid_at = sim_now
                shop.bank.receive_payment(
                    amount=req.estimated_value,
                    description=f"Payment from {req.client_name} — {req.request_type}",
                    sim_time=sim_now,
                    source="client_payment",
                    customer_id=req.id,
                )

    def pop_pending_customer_events(self, persona_name: str) -> list[StreetEvent]:
        """Return and clear pending events (customer ready-to-pay) for a retail shop."""
        shop = self._shops.get(persona_name)
        if not shop:
            return []
        return shop.pop_pending_events()

    def pop_pending_phone_calls(self, persona_name: str) -> list[StreetEvent]:
        """Return and clear pending phone call events for a service business."""
        shop = self._shops.get(persona_name)
        if not shop:
            return []
        return shop.pop_pending_phone_calls()

    def pop_pending_emails(self, persona_name: str) -> list[StreetEvent]:
        """Return and clear pending email inquiry events for a service business."""
        shop = self._shops.get(persona_name)
        if not shop:
            return []
        return shop.pop_pending_emails()

    def world_state_for_persona(self, persona_name: str) -> dict:
        """Get world_state_dict for goal synthesis for a specific persona's shop."""
        shop = self._shops.get(persona_name)
        if not shop:
            return {}
        return shop.world_state_snapshot()

    def bank_for_persona(self, persona_name: str) -> Optional[BankAccount]:
        shop = self._shops.get(persona_name)
        return shop.bank if shop else None

    def summary(self) -> dict:
        return {
            p: {
                "served": s.served_today(),
                "waiting": len(s.customers_waiting()),
                "bank_balance": s.bank.balance,
                "unrecorded": s.bank.unrecorded_cash,
            }
            for p, s in self._shops.items()
        }
