"""Stripe + game endpoints for future BotNode phases.

This file keeps the Stripe integration and stochastic-room bet endpoint
so they can be reintroduced in a later version, but they are **not**
imported or referenced by the current API.

Do NOT expose these routes in the public repo / docs until the
payments phase is ready.
"""

import os
import secrets
from datetime import datetime
from decimal import Decimal

import stripe
from fastapi import HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import models
from auth.jwt_tokens import issue_access_token
from database import get_db

STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "sk_test_mock")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_mock")
stripe.api_key = STRIPE_API_KEY


async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        node_id = session["client_reference_id"]
        ticks_to_add = int(session["metadata"]["ticks"])

        node = db.query(models.Node).filter(models.Node.id == node_id).first()
        if node:
            node.balance += Decimal(str(ticks_to_add))
            db.commit()

    return {"status": "received"}


async def play_roulette(data, node: models.Node, db: Session):
    """Legacy stochastic-room/bet game logic, parked for future phases."""
    if node.balance < Decimal(str(data.amount)):
        raise HTTPException(status_code=402, detail="Insufficient funds")

    node.balance -= Decimal(str(data.amount))

    # House edge 2.7% (European Roulette style)
    # Win chance ~48.6% for 2x payout
    win = secrets.randbelow(1000) < 486

    if win:
        payout = Decimal(str(data.amount)) * 2
        node.balance += payout
        db.commit()
        return {"result": "WIN", "payout": payout, "new_balance": float(node.balance)}

    db.commit()
    return {"result": "LOSE", "new_balance": float(node.balance)}
