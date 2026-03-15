"""Simulated bank account — tracks balance and pending (unrecorded) transactions."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from throngs.street.models import BankTransaction

logger = logging.getLogger(__name__)


class BankAccount:
    """Simulated business bank account for a shop.

    Money arrives (``receive_payment``) before it is recorded in the accounting
    app (``record_in_app``).  The balance only grows when the owner actually
    logs the transaction — mirroring the real-world lag between cash-in-hand
    and books being updated.
    """

    def __init__(
        self,
        initial_balance: float = 0.0,
        account_name: str = "Business Checking",
    ) -> None:
        self.account_name = account_name
        self._balance: float = round(initial_balance, 2)
        self._transactions: list[BankTransaction] = []

    # ------------------------------------------------------------------
    # Read-only views
    # ------------------------------------------------------------------

    @property
    def balance(self) -> float:
        """Recorded balance (only includes app-confirmed transactions)."""
        return round(self._balance, 2)

    @property
    def unrecorded_cash(self) -> float:
        """Money physically received but not yet entered in the app."""
        return round(
            sum(t.amount for t in self._transactions if not t.recorded_in_app and t.amount > 0),
            2,
        )

    @property
    def pending_deposit_count(self) -> int:
        return sum(1 for t in self._transactions if not t.recorded_in_app and t.amount > 0)

    @property
    def todays_receipts(self) -> float:
        return round(sum(t.amount for t in self._transactions if t.amount > 0), 2)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def receive_payment(
        self,
        amount: float,
        description: str,
        sim_time: datetime,
        source: str = "customer_payment",
        customer_id: Optional[str] = None,
    ) -> BankTransaction:
        """Money arrives — does NOT update the recorded balance yet."""
        txn = BankTransaction(
            sim_time=sim_time,
            amount=round(amount, 2),
            description=description,
            source=source,
            customer_id=customer_id,
            recorded_in_app=False,
        )
        self._transactions.append(txn)
        logger.debug("Bank: received %.2f (%s) — unrecorded", amount, description)
        return txn

    def record_in_app(self, transaction_id: str) -> bool:
        """Owner enters the transaction in the app — balance is updated."""
        for txn in self._transactions:
            if txn.id == transaction_id and not txn.recorded_in_app:
                txn.recorded_in_app = True
                self._balance = round(self._balance + txn.amount, 2)
                logger.info(
                    "Bank: transaction %s recorded — new balance %.2f",
                    transaction_id,
                    self._balance,
                )
                return True
        return False

    def record_all_pending(self) -> int:
        """Flush all unrecorded transactions into the balance. Returns count."""
        count = 0
        for txn in self._transactions:
            if not txn.recorded_in_app:
                txn.recorded_in_app = True
                self._balance = round(self._balance + txn.amount, 2)
                count += 1
        return count

    def recent_transactions(self, limit: int = 10) -> list[BankTransaction]:
        return self._transactions[-limit:]

    def world_state_snapshot(self) -> dict:
        """Compact dict suitable for injection into goal-synthesis world_state_dict."""
        return {
            "bank_balance": self.balance,
            "unrecorded_cash": self.unrecorded_cash,
            "pending_deposit_count": self.pending_deposit_count,
            "todays_receipts": self.todays_receipts,
        }
