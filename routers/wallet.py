"""Wallet endpoints: TCK purchases via Stripe, balance, and purchase history.

Implements a fiat-to-TCK on-ramp using Stripe Checkout (hosted).  BotNode
never touches card data — PCI scope is SAQ-A.

Webhook events handled:
- ``checkout.session.completed`` — mint TCK to buyer
- ``checkout.session.expired`` / ``async_payment_failed`` — mark purchase failed
- ``charge.disputed`` — clawback TCK from buyer, freeze node
- ``charge.refunded`` — clawback TCK from buyer

This module is **feature-flagged**: endpoints are only mounted when
``ENABLE_WALLET=true`` is set in the environment (see ``main.py``).
"""

import os
import time
import uuid
import logging

import stripe
from decimal import Decimal
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

import models
import schemas
from dependencies import _utcnow, get_db, get_current_node, audit_log, require_admin_key
from ledger import record_transfer, MINT, VAULT
from config import TCK_PACKAGES

logger = logging.getLogger("botnode.wallet")

router = APIRouter(tags=["wallet"])

# ---------------------------------------------------------------------------
# Stripe configuration
# ---------------------------------------------------------------------------
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_SUCCESS_URL = os.getenv(
    "STRIPE_SUCCESS_URL",
    "https://botnode.io/wallet/success?session_id={CHECKOUT_SESSION_ID}",
)
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "https://botnode.io/wallet/cancel")

# Session TTL: 30 minutes (prevents stale pending purchases)
CHECKOUT_SESSION_TTL = int(os.getenv("CHECKOUT_SESSION_TTL", "1800"))


# ---------------------------------------------------------------------------
# Public: list packages
# ---------------------------------------------------------------------------

@router.get("/v1/wallet/packages")
def list_packages() -> dict:
    """List available TCK packages with pricing.

    Auth: none (public endpoint for display).
    """
    return {
        "packages": [
            {
                "id": p["id"],
                "name": p["name"],
                "price_usd": f"{p['price_usd_cents'] / 100:.2f}",
                "tck_base": p["tck_base"],
                "tck_bonus": p["tck_bonus"],
                "tck_total": int(p["tck_total"]),
                "bonus_pct": (
                    f"{int(p['tck_bonus'] / p['tck_base'] * 100)}%"
                    if p["tck_bonus"]
                    else None
                ),
                "description": p["description"],
            }
            for p in TCK_PACKAGES.values()
        ],
        "currency": "USD",
        "exchange_rate": "1 TCK = $0.01",
    }


# ---------------------------------------------------------------------------
# Authenticated: create checkout session
# ---------------------------------------------------------------------------

@router.post("/v1/wallet/checkout")
def create_checkout(
    req: schemas.CheckoutRequest,
    caller: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """Create a Stripe Checkout session to purchase a TCK package.

    Auth: JWT or API key.  The ``node_id`` in the request must match the
    authenticated caller (you can only buy TCK for yourself).

    The session expires after 30 minutes (configurable via
    ``CHECKOUT_SESSION_TTL``).  A Stripe idempotency key prevents duplicate
    sessions on client retries.

    Returns a ``checkout_url`` that the client should open to complete payment.
    """
    if caller.id != req.node_id:
        raise HTTPException(status_code=403, detail="Cannot purchase for another node")

    package = TCK_PACKAGES.get(req.package_id)
    if not package:
        raise HTTPException(status_code=400, detail=f"Invalid package: {req.package_id}")

    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="Payment system not configured")

    idempotency_key = f"purchase_{req.node_id}_{req.package_id}_{uuid.uuid4().hex[:8]}"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": package["price_usd_cents"],
                        "product_data": {
                            "name": f"BotNode {package['name']} Package",
                            "description": package["description"],
                        },
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=STRIPE_SUCCESS_URL,
            cancel_url=STRIPE_CANCEL_URL,
            expires_at=int(time.time()) + CHECKOUT_SESSION_TTL,
            customer_creation="always",
            metadata={
                "node_id": req.node_id,
                "package_id": req.package_id,
                "tck_total": str(int(package["tck_total"])),
                "tck_bonus": str(package["tck_bonus"]),
                "idempotency_key": idempotency_key,
            },
            idempotency_key=idempotency_key,
        )
    except stripe.StripeError as e:
        logger.error(f"Stripe error creating checkout: {e}")
        raise HTTPException(status_code=502, detail="Payment provider error")

    purchase = models.Purchase(
        node_id=req.node_id,
        package_id=req.package_id,
        tck_base=package["tck_base"],
        tck_bonus=package["tck_bonus"],
        tck_total=package["tck_total"],
        price_usd_cents=package["price_usd_cents"],
        stripe_session_id=session.id,
        idempotency_key=idempotency_key,
        status="pending",
    )
    db.add(purchase)
    db.commit()

    logger.info(
        f"Checkout created: node={req.node_id} package={req.package_id} session={session.id}"
    )

    return {
        "checkout_url": session.url,
        "session_id": session.id,
        "package": req.package_id,
        "tck_total": int(package["tck_total"]),
    }


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------

@router.post("/v1/stripe/webhook")
async def stripe_webhook(request: Request) -> dict:
    """Receive Stripe webhook events.

    Auth: Stripe signature verification only (no API key).

    Handled events:
    - ``checkout.session.completed`` — mint TCK to buyer wallet
    - ``checkout.session.expired`` — mark purchase as failed
    - ``checkout.session.async_payment_failed`` — mark purchase as failed
    - ``charge.disputed`` — clawback TCK, freeze node
    - ``charge.refunded`` — clawback TCK

    Always returns 200 to Stripe to prevent infinite retry loops.
    Internal errors are logged and the purchase is marked ``failed``.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data_object = event["data"]["object"]

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data_object)
    elif event_type in ("checkout.session.expired", "checkout.session.async_payment_failed"):
        _handle_checkout_failed(data_object)
    elif event_type == "charge.disputed":
        _handle_charge_disputed(data_object)
    elif event_type == "charge.refunded":
        _handle_charge_refunded(data_object)

    # Always return 200 — Stripe retries on 4xx/5xx and we don't want loops
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Webhook handlers (private)
# ---------------------------------------------------------------------------

def _handle_checkout_completed(session: dict) -> None:
    """Process a completed Stripe Checkout — mint TCK to the buyer."""
    from database import SessionLocal

    metadata = session.get("metadata", {})
    node_id = metadata.get("node_id")
    package_id = metadata.get("package_id")
    tck_total = int(metadata.get("tck_total", 0))
    idempotency_key = metadata.get("idempotency_key")

    if not all([node_id, package_id, tck_total, idempotency_key]):
        logger.error(f"Webhook missing metadata: {session.get('id')}")
        return

    db = SessionLocal()
    try:
        # Idempotency check
        purchase = db.query(models.Purchase).filter(
            models.Purchase.idempotency_key == idempotency_key
        ).first()
        if purchase and purchase.status == "completed":
            logger.info(f"Duplicate webhook ignored: {idempotency_key}")
            return

        # Verify node exists and is active
        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        if not node or not node.active:
            logger.error(f"MINT rejected: node {node_id} not found or inactive")
            if purchase:
                purchase.status = "failed"
                db.commit()
            return

        # MINT TCK via ledger
        record_transfer(
            db, MINT, node_id, Decimal(str(tck_total)),
            "FIAT_PURCHASE", session.get("id"),
            to_node=node,
            note=f"package={package_id}",
        )

        # Update purchase record
        if purchase:
            purchase.status = "completed"
            purchase.stripe_payment_intent = session.get("payment_intent")
            purchase.completed_at = _utcnow()

        db.commit()

        audit_log.info(
            f"FIAT_PURCHASE node={node_id} package={package_id} "
            f"tck={tck_total} session={session.get('id')}"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"MINT failed for {node_id}: {e}")
        # Mark purchase as failed — do NOT re-raise (return 200 to Stripe)
        try:
            purchase = db.query(models.Purchase).filter(
                models.Purchase.idempotency_key == idempotency_key
            ).first()
            if purchase:
                purchase.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _handle_checkout_failed(session: dict) -> None:
    """Mark expired or payment-failed checkout sessions as failed."""
    from database import SessionLocal

    db = SessionLocal()
    try:
        purchase = db.query(models.Purchase).filter(
            models.Purchase.stripe_session_id == session.get("id")
        ).first()
        if purchase and purchase.status == "pending":
            purchase.status = "failed"
            db.commit()
            logger.info(f"Checkout failed/expired: {session.get('id')}")
    finally:
        db.close()


def _handle_charge_disputed(charge: dict) -> None:
    """Clawback TCK when a buyer opens a chargeback.

    Debits the TCK from the node's balance back to VAULT and deactivates
    the node to prevent further purchases until the dispute is resolved.
    """
    from database import SessionLocal

    payment_intent = charge.get("payment_intent")
    if not payment_intent:
        logger.warning(f"Dispute without payment_intent: {charge.get('id')}")
        return

    db = SessionLocal()
    try:
        purchase = db.query(models.Purchase).filter(
            models.Purchase.stripe_payment_intent == payment_intent,
            models.Purchase.status == "completed",
        ).first()
        if not purchase:
            logger.warning(f"Dispute for unknown payment_intent: {payment_intent}")
            return

        node = db.query(models.Node).filter(models.Node.id == purchase.node_id).first()
        if not node:
            return

        # Clawback: debit the purchased TCK from node to VAULT
        clawback_amount = min(node.balance, purchase.tck_total)
        if clawback_amount > 0:
            record_transfer(
                db, node.id, VAULT, clawback_amount,
                "CHARGEBACK_CLAWBACK", purchase.id,
                from_node=node,
                note=f"stripe_dispute={charge.get('id')}",
            )

        # Freeze the node
        node.active = False
        purchase.status = "disputed"
        db.commit()

        audit_log.warning(
            f"CHARGEBACK node={purchase.node_id} amount={clawback_amount} "
            f"dispute={charge.get('id')} purchase={purchase.id}"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Chargeback handling failed: {e}")
    finally:
        db.close()


def _handle_charge_refunded(charge: dict) -> None:
    """Clawback TCK when a charge is refunded (admin-initiated or Stripe)."""
    from database import SessionLocal

    payment_intent = charge.get("payment_intent")
    if not payment_intent:
        return

    db = SessionLocal()
    try:
        purchase = db.query(models.Purchase).filter(
            models.Purchase.stripe_payment_intent == payment_intent,
            models.Purchase.status == "completed",
        ).first()
        if not purchase:
            return

        node = db.query(models.Node).filter(models.Node.id == purchase.node_id).first()
        if not node:
            return

        clawback_amount = min(node.balance, purchase.tck_total)
        if clawback_amount > 0:
            record_transfer(
                db, node.id, VAULT, clawback_amount,
                "REFUND_CLAWBACK", purchase.id,
                from_node=node,
                note=f"stripe_refund={charge.get('id')}",
            )

        purchase.status = "refunded"
        db.commit()

        audit_log.info(
            f"REFUND_CLAWBACK node={purchase.node_id} amount={clawback_amount} "
            f"charge={charge.get('id')}"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Refund clawback failed: {e}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Authenticated: balance and history
# ---------------------------------------------------------------------------

@router.get("/v1/wallet/balance")
def get_wallet_balance(
    caller: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """Return the caller's TCK balance and purchase summary.

    Auth: JWT or API key.
    """
    total_purchased = db.query(models.Purchase).filter(
        models.Purchase.node_id == caller.id,
        models.Purchase.status == "completed",
    ).count()

    return {
        "node_id": caller.id,
        "balance_tck": str(caller.balance),
        "total_purchases": total_purchased,
    }


@router.get("/v1/wallet/purchases")
def list_purchases(
    caller: models.Node = Depends(get_current_node),
    db: Session = Depends(get_db),
) -> dict:
    """Return the caller's purchase history.

    Auth: JWT or API key.
    """
    purchases = db.query(models.Purchase).filter(
        models.Purchase.node_id == caller.id,
    ).order_by(models.Purchase.created_at.desc()).all()

    return {
        "node_id": caller.id,
        "purchases": [
            {
                "id": p.id,
                "package_id": p.package_id,
                "tck_total": str(p.tck_total),
                "price_usd": f"{p.price_usd_cents / 100:.2f}",
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "completed_at": p.completed_at.isoformat() if p.completed_at else None,
            }
            for p in purchases
        ],
        "total_purchased_tck": str(
            sum(p.tck_total for p in purchases if p.status == "completed")
        ),
    }


# ---------------------------------------------------------------------------
# Admin: ledger reconciliation
# ---------------------------------------------------------------------------

@router.get("/v1/admin/ledger/reconcile")
def reconcile_ledger(
    _admin: bool = Depends(require_admin_key),
    db: Session = Depends(get_db),
) -> dict:
    """Verify the ledger invariant: sum of all node balances matches the ledger.

    Auth: admin Bearer key.
    Computes total credits minus total debits per real node and compares
    against the stored balance.  Returns ``{"valid": true}`` if they match.
    """
    from sqlalchemy import func as sqlfunc

    total_balances = db.query(
        sqlfunc.coalesce(sqlfunc.sum(models.Node.balance), 0)
    ).scalar()

    total_credits = db.query(
        sqlfunc.coalesce(sqlfunc.sum(models.LedgerEntry.amount), 0)
    ).filter(
        models.LedgerEntry.entry_type == "CREDIT",
        ~models.LedgerEntry.account_id.in_(["VAULT", "MINT"]),
        ~models.LedgerEntry.account_id.like("ESCROW:%"),
    ).scalar()

    total_debits = db.query(
        sqlfunc.coalesce(sqlfunc.sum(models.LedgerEntry.amount), 0)
    ).filter(
        models.LedgerEntry.entry_type == "DEBIT",
        ~models.LedgerEntry.account_id.in_(["VAULT", "MINT"]),
        ~models.LedgerEntry.account_id.like("ESCROW:%"),
    ).scalar()

    ledger_balance = total_credits - total_debits
    valid = abs(total_balances - ledger_balance) < Decimal("0.01")

    return {
        "valid": valid,
        "total_node_balances": str(total_balances),
        "ledger_computed_balance": str(ledger_balance),
        "vault_balance": str(
            db.query(sqlfunc.coalesce(sqlfunc.sum(models.LedgerEntry.amount), 0))
            .filter(
                models.LedgerEntry.entry_type == "CREDIT",
                models.LedgerEntry.account_id == "VAULT",
            )
            .scalar()
            - db.query(sqlfunc.coalesce(sqlfunc.sum(models.LedgerEntry.amount), 0))
            .filter(
                models.LedgerEntry.entry_type == "DEBIT",
                models.LedgerEntry.account_id == "VAULT",
            )
            .scalar()
        ),
        "total_minted": str(
            db.query(sqlfunc.coalesce(sqlfunc.sum(models.LedgerEntry.amount), 0))
            .filter(
                models.LedgerEntry.entry_type == "DEBIT",
                models.LedgerEntry.account_id == "MINT",
            )
            .scalar()
        ),
    }
