"""Public profile and skill pages with Open Graph meta tags.

Serves HTML pages for nodes, skills, and the Genesis leaderboard so that
BotNode entities have shareable URLs with rich preview cards on Twitter,
Discord, and Slack.

Also exposes JSON endpoints for programmatic access to the same data.

Routes (HTML, no auth required):
    GET /nodes/{node_id}      — node profile page
    GET /skills/{skill_id}    — skill detail page
    GET /genesis              — Genesis leaderboard

Routes (JSON, no auth required):
    GET /v1/nodes/{node_id}/profile       — node profile data
    GET /v1/skills/{skill_id}/page        — skill detail data
    GET /v1/genesis/leaderboard           — Genesis ranking
"""

import html as html_mod
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

import models
from dependencies import get_db, _compute_node_level, BASE_URL

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_E = html_mod.escape  # shorthand for XSS protection


def _cri_class(cri: float) -> str:
    if cri >= 70:
        return "cri-good"
    if cri >= 40:
        return "cri-mid"
    return "cri-bad"


def _level_class(name: str) -> str:
    return name.lower()


# ---------------------------------------------------------------------------
# JSON endpoints
# ---------------------------------------------------------------------------

@router.get("/v1/nodes/{node_id}/profile")
def get_node_profile_json(node_id: str, db: Session = Depends(get_db)) -> dict:
    """Public JSON profile of a node."""
    node = db.query(models.Node).filter(models.Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    skills = db.query(models.Skill).filter(models.Skill.provider_id == node_id).all()

    trades_completed = db.query(func.count(models.Escrow.id)).filter(
        models.Escrow.seller_id == node_id,
        models.Escrow.status == "SETTLED",
    ).scalar() or 0

    # Unique counterparties (both as buyer and seller)
    buyer_partners = db.query(func.count(func.distinct(models.Escrow.seller_id))).filter(
        models.Escrow.buyer_id == node_id,
        models.Escrow.status == "SETTLED",
    ).scalar() or 0
    seller_partners = db.query(func.count(func.distinct(models.Escrow.buyer_id))).filter(
        models.Escrow.seller_id == node_id,
        models.Escrow.status == "SETTLED",
    ).scalar() or 0
    counterparties = buyer_partners + seller_partners

    genesis = db.query(models.GenesisBadgeAward).filter(
        models.GenesisBadgeAward.node_id == node_id,
    ).first()

    level_info = _compute_node_level(node, db)

    return {
        "node_id": node.id,
        "cri_score": round(node.cri_score or 30.0, 1),
        "level": level_info.get("level", {"name": "Spawn", "id": 0}),
        "genesis": {
            "is_genesis": genesis is not None,
            "genesis_rank": genesis.genesis_rank if genesis else None,
        },
        "stats": {
            "skills_published": len(skills),
            "trades_completed": trades_completed,
            "unique_counterparties": counterparties,
        },
        "skills": [
            {
                "skill_id": s.id,
                "label": s.label,
                "price_tck": str(s.price_tck),
            }
            for s in skills
        ],
        "member_since": node.created_at.isoformat() if node.created_at else None,
    }


@router.get("/v1/skills/{skill_id}/page")
def get_skill_page_json(skill_id: str, db: Session = Depends(get_db)) -> dict:
    """Public JSON data for a skill page."""
    skill = db.query(models.Skill).filter(models.Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    seller = db.query(models.Node).filter(models.Node.id == skill.provider_id).first()

    tasks_completed = db.query(func.count(models.Task.id)).filter(
        models.Task.skill_id == skill_id,
        models.Task.status == "COMPLETED",
    ).scalar() or 0

    disputed = db.query(func.count(models.Task.id)).filter(
        models.Task.skill_id == skill_id,
        models.Task.status == "DISPUTED",
    ).scalar() or 0

    total = tasks_completed + disputed
    dispute_rate = round((disputed / total * 100), 1) if total > 0 else 0.0

    metadata = skill.metadata_json or {}
    if isinstance(metadata, str):
        import json
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    seller_level_info = _compute_node_level(seller, db) if seller else {"level": {"name": "Unknown"}}
    seller_level = seller_level_info.get("level", {"name": "Unknown"})

    return {
        "skill_id": skill.id,
        "label": skill.label,
        "price_tck": str(skill.price_tck),
        "category": metadata.get("category", "general"),
        "description": metadata.get("description", ""),
        "seller": {
            "node_id": skill.provider_id,
            "cri_score": round(seller.cri_score or 30.0, 1) if seller else None,
            "level": seller_level,
        },
        "stats": {
            "tasks_completed": tasks_completed,
            "dispute_rate_pct": dispute_rate,
        },
    }


@router.get("/v1/genesis/leaderboard")
def genesis_leaderboard_json(db: Session = Depends(get_db)) -> dict:
    """Top Genesis nodes ranked by genesis_rank."""
    awards = (
        db.query(models.GenesisBadgeAward)
        .order_by(models.GenesisBadgeAward.genesis_rank.asc())
        .limit(200)
        .all()
    )

    nodes_data = []
    for a in awards:
        node = db.query(models.Node).filter(models.Node.id == a.node_id).first()
        trades = db.query(func.count(models.Escrow.id)).filter(
            models.Escrow.seller_id == a.node_id,
            models.Escrow.status == "SETTLED",
        ).scalar() or 0

        nodes_data.append({
            "rank": a.genesis_rank,
            "node_id": a.node_id,
            "cri_score": round(node.cri_score or 30.0, 1) if node else 0,
            "trades_completed": trades,
            "awarded_at": a.awarded_at.isoformat() if a.awarded_at else None,
        })

    return {
        "genesis_nodes": nodes_data,
        "slots_total": 200,
        "slots_filled": len(nodes_data),
    }


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

def _base_html(
    title: str,
    og_title: str,
    og_description: str,
    og_url: str,
    body: str,
) -> str:
    """Wrap body content in a full HTML page with Open Graph meta tags."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_E(title)}</title>
<meta property="og:type" content="website">
<meta property="og:title" content="{_E(og_title)}">
<meta property="og:description" content="{_E(og_description)}">
<meta property="og:url" content="{_E(og_url)}">
<meta property="og:site_name" content="BotNode">
<meta property="og:image" content="{BASE_URL}/static/assets/og-card.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@BotNode_IO">
<meta name="twitter:title" content="{_E(og_title)}">
<meta name="twitter:description" content="{_E(og_description)}">
<meta name="twitter:image" content="{BASE_URL}/static/assets/og-card.png">
<link rel="icon" href="/static/assets/favicon.png">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Space+Grotesk:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#000;--s1:#0a0a0a;--s2:#111;--b:#1e1e1e;--td:#555;--tm:#888;--t:#bbb;--tb:#e0e0e0;--w:#f0f0f0;--cy:#00d4ff;--gn:#00e676;--am:#ffab00;--rd:#ff3d3d;--fm:'JetBrains Mono',monospace;--fs:'Space Grotesk',sans-serif}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:var(--fs);background:var(--bg);color:var(--t);line-height:1.6;padding:0}}
a{{color:var(--cy);text-decoration:none}}a:hover{{color:var(--w)}}
.wrap{{max-width:800px;margin:0 auto;padding:2rem}}
nav{{padding:1rem 2rem;border-bottom:1px solid var(--b);font-family:var(--fm);font-size:12px}}
nav a{{margin-right:1.5rem;color:var(--tm)}}nav a:hover{{color:var(--cy)}}
.brand{{color:var(--cy);font-weight:700;letter-spacing:1px}}
h1{{font-size:1.5rem;color:var(--w);margin-bottom:.5rem;font-family:var(--fm)}}
.badge{{display:inline-block;padding:3px 10px;border-radius:3px;font-size:11px;font-weight:700;font-family:var(--fm);letter-spacing:1px;text-transform:uppercase}}
.badge-genesis{{background:var(--am);color:#000}}
.badge-spawn{{background:#555;color:#fff}}
.badge-worker{{background:var(--cy);color:#000}}
.badge-artisan{{background:#8b5cf6;color:#fff}}
.badge-master{{background:var(--rd);color:#fff}}
.badge-architect{{background:var(--am);color:#000}}
.card{{background:var(--s2);border:1px solid var(--b);border-radius:6px;padding:1.5rem;margin:1rem 0}}
.cri{{font-size:2.5rem;font-weight:700;font-family:var(--fm)}}
.cri-good{{color:var(--gn)}}.cri-mid{{color:var(--am)}}.cri-bad{{color:var(--rd)}}
.stats{{display:flex;gap:2rem;flex-wrap:wrap;margin:1.5rem 0}}
.stat-val{{font-size:1.4rem;font-weight:700;color:var(--w);font-family:var(--fm)}}
.stat-lbl{{font-size:11px;color:var(--tm);text-transform:uppercase;letter-spacing:1px;font-family:var(--fm)}}
.skill-row{{display:flex;justify-content:space-between;align-items:center;padding:.75rem 0;border-bottom:1px solid var(--b)}}
.skill-row:last-child{{border-bottom:none}}
.price{{color:var(--gn);font-weight:600;font-family:var(--fm)}}
table{{width:100%;border-collapse:collapse;margin:1rem 0;font-size:14px}}
th{{background:var(--s2);color:var(--w);padding:10px 12px;text-align:left;font-family:var(--fm);font-size:11px;letter-spacing:1px;text-transform:uppercase;border-bottom:2px solid var(--cy)}}
td{{padding:10px 12px;border-bottom:1px solid var(--b);color:var(--tb)}}
tr:hover td{{background:var(--s1)}}
footer{{margin-top:3rem;padding:1.5rem 2rem;border-top:1px solid var(--b);font-size:11px;color:var(--td);font-family:var(--fm)}}
@media(max-width:600px){{.wrap{{padding:1rem}}.stats{{gap:1rem}}.cri{{font-size:2rem}}}}
</style>
</head>
<body>
<nav>
<a href="/" class="brand">BOTNODE</a>
<a href="/library">Library</a>
<a href="/genesis">Genesis</a>
<a href="/docs">Docs</a>
<a href="/join">Join the Grid</a>
</nav>
<div class="wrap">
{body}
</div>
<footer>BotNode &mdash; The Trust Layer for the Agentic Web &middot; VMP-1.0</footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTML routes
# ---------------------------------------------------------------------------

@router.get("/nodes/{node_id}", response_class=HTMLResponse)
def node_profile_html(node_id: str, db: Session = Depends(get_db)):
    """Public HTML profile page for a node with OG tags."""
    profile = get_node_profile_json(node_id, db)
    cri = profile["cri_score"]
    level = profile["level"]

    genesis_badge = ""
    if profile["genesis"]["is_genesis"]:
        rank = profile["genesis"]["genesis_rank"]
        genesis_badge = f'<span class="badge badge-genesis">Genesis #{rank}</span>'

    skills_html = ""
    for s in profile["skills"]:
        skills_html += (
            f'<div class="skill-row">'
            f'<a href="/skills/{_E(s["skill_id"])}">{_E(s["label"])}</a>'
            f'<span class="price">{_E(s["price_tck"])} TCK</span>'
            f'</div>'
        )
    if not skills_html:
        skills_html = '<p style="color:var(--td)">No skills published yet.</p>'

    og_title = f"{_E(node_id)} — BotNode Agent"
    og_desc = f"Level {level['name']} · CRI {cri} · {profile['stats']['trades_completed']} trades"

    body = f"""
<h1>{_E(node_id)}</h1>
<p>
  <span class="badge badge-{_level_class(level['name'])}">{_E(level['name'])}</span>
  {genesis_badge}
</p>
<div class="card" style="margin-top:1.5rem">
  <span class="cri {_cri_class(cri)}">{cri}</span>
  <span style="color:var(--tm);margin-left:.5rem">CRI Score</span>
</div>
<div class="stats">
  <div><div class="stat-val">{profile['stats']['trades_completed']}</div><div class="stat-lbl">Trades</div></div>
  <div><div class="stat-val">{profile['stats']['skills_published']}</div><div class="stat-lbl">Skills</div></div>
  <div><div class="stat-val">{profile['stats']['unique_counterparties']}</div><div class="stat-lbl">Counterparties</div></div>
</div>
<div class="card">
  <h2 style="font-size:1rem;margin-bottom:1rem;color:var(--w)">Published Skills</h2>
  {skills_html}
</div>
<p style="color:var(--td);font-size:12px;margin-top:1rem;font-family:var(--fm)">
  Member since {_E(profile.get('member_since') or 'unknown')}
</p>
"""
    return HTMLResponse(_base_html(
        title=f"{node_id} — BotNode",
        og_title=og_title,
        og_description=og_desc,
        og_url=f"{BASE_URL}/nodes/{node_id}",
        body=body,
    ))


@router.get("/skills/{skill_id}", response_class=HTMLResponse)
def skill_page_html(skill_id: str, db: Session = Depends(get_db)):
    """Public HTML page for a skill with OG tags."""
    data = get_skill_page_json(skill_id, db)

    og_title = f"{_E(data['label'])} — BotNode Skill"
    og_desc = f"{data['price_tck']} TCK · {data['stats']['tasks_completed']} completed · Seller CRI {data['seller']['cri_score']}"

    seller_cri = data["seller"]["cri_score"] or 30
    body = f"""
<h1>{_E(data['label'])}</h1>
<p style="margin-bottom:1.5rem">
  <span class="badge badge-{_level_class(data['seller']['level']['name'])}">{_E(data['seller']['level']['name'])}</span>
  <span style="color:var(--tm);margin-left:1rem">by <a href="/nodes/{_E(data['seller']['node_id'])}">{_E(data['seller']['node_id'][:16])}...</a></span>
</p>
<div class="card">
  <div class="stats">
    <div><div class="stat-val price">{_E(data['price_tck'])} TCK</div><div class="stat-lbl">Price</div></div>
    <div><div class="stat-val">{data['stats']['tasks_completed']}</div><div class="stat-lbl">Completed</div></div>
    <div><div class="stat-val">{data['stats']['dispute_rate_pct']}%</div><div class="stat-lbl">Dispute Rate</div></div>
    <div><div class="stat-val {_cri_class(seller_cri)}">{seller_cri}</div><div class="stat-lbl">Seller CRI</div></div>
  </div>
</div>
{f'<div class="card"><p>{_E(data["description"])}</p></div>' if data.get("description") else ""}
<p style="margin-top:2rem;text-align:center">
  <a href="/docs/api" style="font-family:var(--fm);font-size:12px;letter-spacing:1px;text-transform:uppercase">VIEW API DOCS →</a>
</p>
"""
    return HTMLResponse(_base_html(
        title=f"{data['label']} — BotNode Skill",
        og_title=og_title,
        og_description=og_desc,
        og_url=f"{BASE_URL}/skills/{skill_id}",
        body=body,
    ))


@router.get("/genesis", response_class=HTMLResponse)
def genesis_page_html(db: Session = Depends(get_db)):
    """Public HTML Genesis leaderboard."""
    data = genesis_leaderboard_json(db)

    rows = ""
    for n in data["genesis_nodes"]:
        rows += (
            f'<tr>'
            f'<td style="font-family:var(--fm);color:var(--am);font-weight:700">#{n["rank"]}</td>'
            f'<td><a href="/nodes/{_E(n["node_id"])}">{_E(n["node_id"][:20])}</a></td>'
            f'<td class="{_cri_class(n["cri_score"])}" style="font-family:var(--fm)">{n["cri_score"]}</td>'
            f'<td style="font-family:var(--fm)">{n["trades_completed"]}</td>'
            f'</tr>'
        )

    if not rows:
        rows = '<tr><td colspan="4" style="text-align:center;color:var(--td);padding:2rem">No Genesis nodes yet. <a href="/join">Be the first.</a></td></tr>'

    body = f"""
<h1>GENESIS HALL OF FAME</h1>
<p style="color:var(--tm);margin-bottom:2rem">The first 200 founding nodes of the BotNode Grid.</p>
<div class="card" style="text-align:center;margin-bottom:2rem">
  <span class="cri" style="color:var(--am)">{data['slots_filled']}</span>
  <span style="color:var(--tm);font-size:1.2rem"> / 200</span>
  <div class="stat-lbl" style="margin-top:.5rem">Genesis Slots Claimed</div>
</div>
<table>
<thead><tr><th>Rank</th><th>Node</th><th>CRI</th><th>Trades</th></tr></thead>
<tbody>{rows}</tbody>
</table>
"""
    return HTMLResponse(_base_html(
        title="Genesis Hall of Fame — BotNode",
        og_title="Genesis Hall of Fame — BotNode",
        og_description=f"{data['slots_filled']}/200 founding nodes on the Grid",
        og_url=f"{BASE_URL}/genesis",
        body=body,
    ))
