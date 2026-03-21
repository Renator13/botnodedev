"""Analytics worker — builds daily activity snapshots and serves KPI queries.

Runs as a background task inside the FastAPI process. Every hour it
materializes a daily_active_nodes snapshot for the current day (upsert).
The analytics API queries this table for historical data and live tables
for the current period.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func as sqlfunc, cast, Date as SADate, case, text
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

import models

logger = logging.getLogger("botnode.analytics")


def build_daily_snapshot(db: Session, target_date: date = None) -> dict:
    """Build or update the daily_active_nodes snapshot for target_date."""
    target_date = target_date or date.today()
    day_start = f"{target_date} 00:00:00"
    day_end = f"{target_date} 23:59:59"

    # Buyers: tasks created
    buyers = db.query(
        models.Task.buyer_id.label("node_id"),
        sqlfunc.count(models.Task.id).label("tasks_created"),
    ).filter(
        models.Task.created_at.between(day_start, day_end),
    ).group_by(models.Task.buyer_id).subquery()

    # Sellers: tasks completed
    sellers = db.query(
        models.Task.seller_id.label("node_id"),
        sqlfunc.count(models.Task.id).label("tasks_completed"),
    ).filter(
        models.Task.created_at.between(day_start, day_end),
        models.Task.status == "COMPLETED",
    ).group_by(models.Task.seller_id).subquery()

    # TCK spent (ESCROW_LOCK debits)
    spent = db.query(
        models.LedgerEntry.account_id.label("node_id"),
        sqlfunc.sum(models.LedgerEntry.amount).label("tck_spent"),
    ).filter(
        models.LedgerEntry.created_at.between(day_start, day_end),
        models.LedgerEntry.reference_type == "ESCROW_LOCK",
        models.LedgerEntry.entry_type == "DEBIT",
    ).group_by(models.LedgerEntry.account_id).subquery()

    # TCK earned (ESCROW_SETTLE credits)
    earned = db.query(
        models.LedgerEntry.account_id.label("node_id"),
        sqlfunc.sum(models.LedgerEntry.amount).label("tck_earned"),
    ).filter(
        models.LedgerEntry.created_at.between(day_start, day_end),
        models.LedgerEntry.reference_type == "ESCROW_SETTLE",
        models.LedgerEntry.entry_type == "CREDIT",
    ).group_by(models.LedgerEntry.account_id).subquery()

    # Collect all active node IDs from each activity source
    active_ids = set()
    for sq in [buyers, sellers, spent, earned]:
        for (nid,) in db.query(sq.c.node_id).all():
            if nid:
                active_ids.add(nid)

    if not active_ids:
        return {"date": str(target_date), "rows": 0}

    # Build lookup dicts
    buyer_map = {r[0]: r[1] for r in db.query(buyers.c.node_id, buyers.c.tasks_created).all()}
    seller_map = {r[0]: r[1] for r in db.query(sellers.c.node_id, sellers.c.tasks_completed).all()}
    spent_map = {r[0]: r[1] for r in db.query(spent.c.node_id, spent.c.tck_spent).all()}
    earned_map = {r[0]: r[1] for r in db.query(earned.c.node_id, earned.c.tck_earned).all()}

    # Get node metadata
    node_meta = {n.id: n for n in db.query(models.Node).filter(models.Node.id.in_(active_ids)).all()}

    rows = []
    for nid in active_ids:
        node = node_meta.get(nid)
        rows.append((
            nid,
            node.is_sandbox if node else False,
            node.country_code if node else None,
            buyer_map.get(nid, 0),
            seller_map.get(nid, 0),
            spent_map.get(nid, 0),
            earned_map.get(nid, 0),
        ))

    # Upsert into daily_active_nodes
    inserted = 0
    for node_id, is_sandbox, country_code, tc, tcomp, ts, te in rows:
        if not node_id:
            continue
        stmt = pg_insert(models.DailyActiveNodes).values(
            date=target_date,
            node_id=node_id,
            is_sandbox=bool(is_sandbox),
            country_code=country_code,
            tasks_created=tc,
            tasks_completed=tcomp,
            tck_spent=ts,
            tck_earned=te,
        ).on_conflict_do_update(
            constraint="daily_active_nodes_date_node_id_key",
            set_={
                "tasks_created": tc,
                "tasks_completed": tcomp,
                "tck_spent": ts,
                "tck_earned": te,
            },
        )
        db.execute(stmt)
        inserted += 1

    db.commit()
    logger.info(f"Analytics snapshot for {target_date}: {inserted} rows")
    return {"date": str(target_date), "rows": inserted}


def get_analytics(db: Session, period: str = "today") -> dict:
    """Return structured KPI data for the given period."""
    today = date.today()
    period_map = {
        "today": (today, today),
        "7d": (today - timedelta(days=7), today),
        "30d": (today - timedelta(days=30), today),
        "quarter": (today - timedelta(days=90), today),
        "year": (today - timedelta(days=365), today),
        "all": (date(2020, 1, 1), today),
    }
    start, end = period_map.get(period, period_map["today"])
    start_ts = f"{start} 00:00:00"
    end_ts = f"{end} 23:59:59"

    # --- NODES ---
    total_nodes = db.query(sqlfunc.count(models.Node.id)).filter(models.Node.is_sandbox == False).scalar()
    new_nodes = db.query(sqlfunc.count(models.Node.id)).filter(
        models.Node.is_sandbox == False,
        models.Node.created_at.between(start_ts, end_ts),
    ).scalar()
    total_sandbox = db.query(sqlfunc.count(models.Node.id)).filter(models.Node.is_sandbox == True).scalar()
    new_sandbox = db.query(sqlfunc.count(models.Node.id)).filter(
        models.Node.is_sandbox == True,
        models.Node.created_at.between(start_ts, end_ts),
    ).scalar()

    # Active nodes (had escrow activity in period, non-sandbox)
    active_buyers = db.query(sqlfunc.count(sqlfunc.distinct(models.Escrow.buyer_id))).filter(
        models.Escrow.created_at.between(start_ts, end_ts),
    ).scalar()
    active_sellers = db.query(sqlfunc.count(sqlfunc.distinct(models.Escrow.seller_id))).filter(
        models.Escrow.created_at.between(start_ts, end_ts),
    ).scalar()

    # Nodes by country (top 15, non-sandbox)
    by_country = db.query(
        models.Node.country_code,
        sqlfunc.count(models.Node.id),
    ).filter(
        models.Node.is_sandbox == False,
        models.Node.country_code != None,
    ).group_by(models.Node.country_code).order_by(sqlfunc.count(models.Node.id).desc()).limit(15).all()

    # --- TASKS ---
    tasks_created = db.query(sqlfunc.count(models.Task.id)).filter(
        models.Task.created_at.between(start_ts, end_ts),
        models.Task.is_shadow == False,
    ).scalar()
    tasks_completed = db.query(sqlfunc.count(models.Task.id)).filter(
        models.Task.created_at.between(start_ts, end_ts),
        models.Task.status == "COMPLETED",
        models.Task.is_shadow == False,
    ).scalar()

    # Tasks by protocol
    by_protocol = db.query(
        models.Task.protocol, sqlfunc.count(models.Task.id),
    ).filter(
        models.Task.created_at.between(start_ts, end_ts),
    ).group_by(models.Task.protocol).all()

    # Tasks by LLM provider
    by_provider = db.query(
        models.Task.llm_provider_used, sqlfunc.count(models.Task.id),
    ).filter(
        models.Task.created_at.between(start_ts, end_ts),
        models.Task.llm_provider_used != None,
    ).group_by(models.Task.llm_provider_used).all()

    # Top skills by task count
    top_skills = db.query(
        models.Skill.label, sqlfunc.count(models.Task.id),
    ).join(models.Task, models.Task.skill_id == models.Skill.id).filter(
        models.Task.created_at.between(start_ts, end_ts),
    ).group_by(models.Skill.label).order_by(sqlfunc.count(models.Task.id).desc()).limit(10).all()

    # --- ECONOMY ---
    gmv = db.query(sqlfunc.coalesce(sqlfunc.sum(models.Escrow.amount), 0)).filter(
        models.Escrow.created_at.between(start_ts, end_ts),
        models.Escrow.status.in_(["SETTLED", "AWAITING_SETTLEMENT"]),
    ).scalar()
    tax_collected = db.query(sqlfunc.coalesce(sqlfunc.sum(models.LedgerEntry.amount), 0)).filter(
        models.LedgerEntry.created_at.between(start_ts, end_ts),
        models.LedgerEntry.reference_type == "PROTOCOL_TAX",
    ).scalar()

    # Settlement rate
    settled = db.query(sqlfunc.count(models.Escrow.id)).filter(
        models.Escrow.created_at.between(start_ts, end_ts),
        models.Escrow.status == "SETTLED",
    ).scalar()
    refunded = db.query(sqlfunc.count(models.Escrow.id)).filter(
        models.Escrow.created_at.between(start_ts, end_ts),
        models.Escrow.status == "REFUNDED",
    ).scalar()
    disputed = db.query(sqlfunc.count(models.Escrow.id)).filter(
        models.Escrow.created_at.between(start_ts, end_ts),
        models.Escrow.status == "DISPUTED",
    ).scalar()
    total_outcomes = settled + refunded + disputed
    settle_rate = round(settled / total_outcomes, 4) if total_outcomes > 0 else 0

    # Vault balance
    vault_credit = db.query(sqlfunc.coalesce(sqlfunc.sum(models.LedgerEntry.amount), 0)).filter(
        models.LedgerEntry.account_id == "VAULT",
        models.LedgerEntry.entry_type == "CREDIT",
    ).scalar()
    vault_debit = db.query(sqlfunc.coalesce(sqlfunc.sum(models.LedgerEntry.amount), 0)).filter(
        models.LedgerEntry.account_id == "VAULT",
        models.LedgerEntry.entry_type == "DEBIT",
    ).scalar()
    vault_balance = float(vault_credit) - float(vault_debit)

    # --- SKILLS ---
    total_skills = db.query(sqlfunc.count(models.Skill.id)).scalar()
    skills_published = db.query(sqlfunc.count(models.LedgerEntry.id)).filter(
        models.LedgerEntry.created_at.between(start_ts, end_ts),
        models.LedgerEntry.reference_type == "LISTING_FEE",
    ).scalar()

    # --- GENESIS ---
    genesis_filled = db.query(sqlfunc.count(models.Node.id)).filter(
        models.Node.has_genesis_badge == True,
    ).scalar()

    # --- FUNNEL ---
    funnel_sandbox = db.query(sqlfunc.count(models.FunnelEvent.id)).filter(
        models.FunnelEvent.event_type == "sandbox_trade",
        models.FunnelEvent.created_at.between(start_ts, end_ts),
    ).scalar()
    funnel_register = db.query(sqlfunc.count(models.FunnelEvent.id)).filter(
        models.FunnelEvent.event_type == "register",
        models.FunnelEvent.created_at.between(start_ts, end_ts),
    ).scalar()
    funnel_first_trade = db.query(sqlfunc.count(models.FunnelEvent.id)).filter(
        models.FunnelEvent.event_type == "first_trade",
        models.FunnelEvent.created_at.between(start_ts, end_ts),
    ).scalar()

    # Funnel conversion: sandbox IPs that later registered
    funnel_sandbox_to_register = 0
    if funnel_sandbox > 0:
        sandbox_ips = db.query(models.FunnelEvent.ip_fingerprint).filter(
            models.FunnelEvent.event_type == "sandbox_trade",
            models.FunnelEvent.ip_fingerprint != None,
        ).subquery()
        funnel_sandbox_to_register = db.query(sqlfunc.count(models.FunnelEvent.id)).filter(
            models.FunnelEvent.event_type == "register",
            models.FunnelEvent.ip_fingerprint.in_(sandbox_ips),
        ).scalar()

    # --- CRI COMPONENT ANALYSIS ---
    cri_stats = {}
    cri_count = db.query(sqlfunc.count(models.CRISnapshot.id)).filter(
        models.CRISnapshot.calculated_at.between(start_ts, end_ts),
    ).scalar()
    if cri_count > 0:
        cri_stats = {
            "snapshots": cri_count,
            "avg_components": {
                "base": round(float(db.query(sqlfunc.avg(models.CRISnapshot.base)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
                "tx_score": round(float(db.query(sqlfunc.avg(models.CRISnapshot.tx_score)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
                "diversity_score": round(float(db.query(sqlfunc.avg(models.CRISnapshot.diversity_score)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
                "volume_score": round(float(db.query(sqlfunc.avg(models.CRISnapshot.volume_score)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
                "age_score": round(float(db.query(sqlfunc.avg(models.CRISnapshot.age_score)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
                "buyer_score": round(float(db.query(sqlfunc.avg(models.CRISnapshot.buyer_score)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
                "genesis_bonus": round(float(db.query(sqlfunc.avg(models.CRISnapshot.genesis_bonus)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
                "dispute_penalty": round(float(db.query(sqlfunc.avg(models.CRISnapshot.dispute_penalty)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
                "concentration_penalty": round(float(db.query(sqlfunc.avg(models.CRISnapshot.concentration_penalty)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
                "strike_penalty": round(float(db.query(sqlfunc.avg(models.CRISnapshot.strike_penalty)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
            },
            "avg_cri": round(float(db.query(sqlfunc.avg(models.CRISnapshot.cri_after)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
            "min_cri": round(float(db.query(sqlfunc.min(models.CRISnapshot.cri_after)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
            "max_cri": round(float(db.query(sqlfunc.max(models.CRISnapshot.cri_after)).filter(models.CRISnapshot.calculated_at.between(start_ts, end_ts)).scalar() or 0), 2),
        }

    # --- DAILY TREND (last 30 days from materialized table) ---
    daily_trend = db.query(
        models.DailyActiveNodes.date,
        sqlfunc.count(sqlfunc.distinct(models.DailyActiveNodes.node_id)),
        sqlfunc.sum(models.DailyActiveNodes.tasks_created),
        sqlfunc.sum(models.DailyActiveNodes.tck_spent),
    ).filter(
        models.DailyActiveNodes.date >= today - timedelta(days=30),
        models.DailyActiveNodes.is_sandbox == False,
    ).group_by(models.DailyActiveNodes.date).order_by(models.DailyActiveNodes.date).all()

    return {
        "period": period,
        "range": {"start": str(start), "end": str(end)},
        "nodes": {
            "total": total_nodes,
            "new": new_nodes,
            "sandbox_total": total_sandbox,
            "sandbox_new": new_sandbox,
            "active_buyers": active_buyers,
            "active_sellers": active_sellers,
            "by_country": [{"country": c or "unknown", "count": n} for c, n in by_country],
        },
        "tasks": {
            "created": tasks_created,
            "completed": tasks_completed,
            "completion_rate": round(tasks_completed / tasks_created, 4) if tasks_created > 0 else 0,
            "by_protocol": {p or "unknown": n for p, n in by_protocol},
            "by_provider": {p or "unknown": n for p, n in by_provider},
            "top_skills": [{"skill": s, "count": n} for s, n in top_skills],
        },
        "economy": {
            "gmv_tck": float(gmv),
            "tax_collected_tck": float(tax_collected),
            "vault_balance_tck": vault_balance,
            "settled": settled,
            "refunded": refunded,
            "disputed": disputed,
            "settle_rate": settle_rate,
        },
        "skills": {
            "total": total_skills,
            "published_in_period": skills_published,
        },
        "genesis": {
            "filled": genesis_filled,
            "total_slots": 200,
            "fill_rate": round(genesis_filled / 200, 4),
        },
        "funnel": {
            "sandbox_trades": funnel_sandbox,
            "registrations": funnel_register,
            "first_trades": funnel_first_trade,
            "sandbox_to_register": funnel_sandbox_to_register,
            "conversion_sandbox_to_register": round(funnel_sandbox_to_register / funnel_sandbox, 4) if funnel_sandbox > 0 else 0,
            "conversion_register_to_trade": round(funnel_first_trade / funnel_register, 4) if funnel_register > 0 else 0,
        },
        "cri": cri_stats,
        "daily_trend": [
            {"date": str(d), "active_nodes": n, "tasks": t or 0, "tck_volume": float(v or 0)}
            for d, n, t, v in daily_trend
        ],
    }


def get_export_data(db: Session, table: str, period: str = "30d", fmt: str = "json") -> list:
    """Export raw aggregated data (no PII) for external analysis tools."""
    today = date.today()
    period_map = {
        "7d": today - timedelta(days=7),
        "30d": today - timedelta(days=30),
        "quarter": today - timedelta(days=90),
        "year": today - timedelta(days=365),
        "all": date(2020, 1, 1),
    }
    start = period_map.get(period, period_map["30d"])

    if table == "daily_active":
        rows = db.query(
            models.DailyActiveNodes.date,
            models.DailyActiveNodes.is_sandbox,
            models.DailyActiveNodes.country_code,
            models.DailyActiveNodes.tasks_created,
            models.DailyActiveNodes.tasks_completed,
            models.DailyActiveNodes.tck_spent,
            models.DailyActiveNodes.tck_earned,
        ).filter(models.DailyActiveNodes.date >= start).order_by(models.DailyActiveNodes.date).all()
        return [{"date": str(r[0]), "sandbox": r[1], "country": r[2], "tasks_created": r[3],
                 "tasks_completed": r[4], "tck_spent": float(r[5]), "tck_earned": float(r[6])} for r in rows]

    elif table == "tasks":
        rows = db.query(
            cast(models.Task.created_at, SADate).label("date"),
            models.Task.protocol,
            models.Task.llm_provider_used,
            models.Task.status,
            sqlfunc.count(models.Task.id),
        ).filter(
            models.Task.created_at >= f"{start} 00:00:00",
        ).group_by("date", models.Task.protocol, models.Task.llm_provider_used, models.Task.status
        ).order_by("date").all()
        return [{"date": str(r[0]), "protocol": r[1], "provider": r[2], "status": r[3], "count": r[4]} for r in rows]

    elif table == "escrows":
        rows = db.query(
            cast(models.Escrow.created_at, SADate).label("date"),
            models.Escrow.status,
            sqlfunc.count(models.Escrow.id),
            sqlfunc.sum(models.Escrow.amount),
        ).filter(
            models.Escrow.created_at >= f"{start} 00:00:00",
        ).group_by("date", models.Escrow.status).order_by("date").all()
        return [{"date": str(r[0]), "status": r[1], "count": r[2], "volume_tck": float(r[3] or 0)} for r in rows]

    elif table == "nodes":
        rows = db.query(
            cast(models.Node.created_at, SADate).label("date"),
            models.Node.is_sandbox,
            models.Node.country_code,
            sqlfunc.count(models.Node.id),
        ).filter(
            models.Node.created_at >= f"{start} 00:00:00",
        ).group_by("date", models.Node.is_sandbox, models.Node.country_code).order_by("date").all()
        return [{"date": str(r[0]), "sandbox": r[1], "country": r[2], "count": r[3]} for r in rows]

    elif table == "funnel":
        rows = db.query(
            cast(models.FunnelEvent.created_at, SADate).label("date"),
            models.FunnelEvent.event_type,
            models.FunnelEvent.country_code,
            sqlfunc.count(models.FunnelEvent.id),
        ).filter(
            models.FunnelEvent.created_at >= f"{start} 00:00:00",
        ).group_by("date", models.FunnelEvent.event_type, models.FunnelEvent.country_code).order_by("date").all()
        return [{"date": str(r[0]), "event": r[1], "country": r[2], "count": r[3]} for r in rows]

    elif table == "cri":
        rows = db.query(models.CRISnapshot).filter(
            models.CRISnapshot.calculated_at >= f"{start} 00:00:00",
        ).order_by(models.CRISnapshot.calculated_at).all()
        return [{
            "date": r.calculated_at.strftime("%Y-%m-%d") if r.calculated_at else None,
            "node_id": r.node_id,
            "base": r.base, "tx_score": r.tx_score, "diversity_score": r.diversity_score,
            "volume_score": r.volume_score, "age_score": r.age_score, "buyer_score": r.buyer_score,
            "genesis_bonus": r.genesis_bonus, "dispute_penalty": r.dispute_penalty,
            "concentration_penalty": r.concentration_penalty, "strike_penalty": r.strike_penalty,
            "decay_factor": r.decay_factor,
            "settled_total": r.settled_total, "unique_counterparties": r.unique_counterparties,
            "total_volume_tck": r.total_volume_tck, "age_days": r.age_days,
            "cri_before": r.cri_before, "cri_after": r.cri_after,
        } for r in rows]

    return []
