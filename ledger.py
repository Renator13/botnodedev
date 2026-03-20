"""Double-entry ledger for all financial operations.

Every TCK movement is recorded as a pair of DEBIT + CREDIT entries.
Node balances are mutated atomically alongside ledger writes so that
``SUM(credits) - SUM(debits)`` per account always equals ``Node.balance``.

System accounts (no Node row):
- ``VAULT``: receives protocol tax and confiscated funds.
- ``MINT``: source for initial balances and Genesis bonuses.
"""

import logging
from decimal import Decimal
from sqlalchemy.orm import Session
import models

audit_log = logging.getLogger("botnode.audit")

VAULT = "VAULT"
MINT = "MINT"


def record_transfer(
    db: Session,
    from_account: str,
    to_account: str,
    amount: Decimal,
    reference_type: str,
    reference_id: str | None = None,
    note: str | None = None,
    from_node: "models.Node | None" = None,
    to_node: "models.Node | None" = None,
) -> None:
    """Record a double-entry transfer and update node balances.

    For system accounts (VAULT, MINT) or escrow pseudo-accounts only the
    ledger entry is written -- there is no Node row to update.  For real
    nodes, pass the pre-locked Node object as ``from_node`` / ``to_node``
    so that the balance is mutated in-place without a second query.

    Creates both DEBIT and CREDIT LedgerEntry rows.
    """
    from_balance_after = None
    to_balance_after = None

    # Debit
    if from_node is not None:
        from_node.balance -= amount
        from_balance_after = from_node.balance

    db.add(models.LedgerEntry(
        account_id=from_account,
        entry_type="DEBIT",
        amount=amount,
        balance_after=from_balance_after,
        reference_type=reference_type,
        reference_id=reference_id,
        counterparty_id=to_account,
        note=note,
    ))

    # Credit
    if to_node is not None:
        to_node.balance += amount
        to_balance_after = to_node.balance

    db.add(models.LedgerEntry(
        account_id=to_account,
        entry_type="CREDIT",
        amount=amount,
        balance_after=to_balance_after,
        reference_type=reference_type,
        reference_id=reference_id,
        counterparty_id=from_account,
        note=note,
    ))

    audit_log.info(
        f"LEDGER {reference_type} {from_account}->{to_account} "
        f"amount={amount} ref={reference_id} "
        f"from_bal={from_balance_after} to_bal={to_balance_after}"
    )
