"""Shareable sandbox trade results.

When a sandbox trade completes on the homepage, the result can be
saved and shared via a permanent URL. Each shared trade gets an
OG-tagged HTML page showing what happened.
"""

import uuid
from html import escape as html_escape
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from dependencies import get_db, limiter

router = APIRouter(tags=["sandbox"])

BASE_URL = "https://botnode.io"


class ShareRequest(BaseModel):
    node_id: str | None = None
    skill: str | None = None
    price: float | str | None = None
    task_id: str | None = None
    escrow_id: str | None = None
    balance: float | str | None = None


@router.post("/v1/sandbox/share")
@limiter.limit("30/hour")
def create_share(request: Request, req: ShareRequest, db: Session = Depends(get_db)) -> dict:
    """Save a sandbox trade result for sharing.

    Returns a share_id and permanent URL.
    """
    share_id = str(uuid.uuid4())[:8]
    trade_data = req.model_dump()

    share = models.SandboxShare(
        id=share_id,
        trade_data=trade_data,
    )
    db.add(share)
    db.commit()

    return {
        "share_id": share_id,
        "url": f"{BASE_URL}/sandbox/trade/{share_id}",
    }


@router.get("/sandbox/trade/{share_id}", response_class=HTMLResponse)
def view_shared_trade(share_id: str, db: Session = Depends(get_db)):
    """Render an OG-tagged HTML page for a shared sandbox trade."""
    share = db.query(models.SandboxShare).filter(models.SandboxShare.id == share_id).first()

    if not share:
        return HTMLResponse(
            content="<html><body style='background:#000;color:#fff;font-family:monospace;padding:3rem'>"
                    "<h1>Trade not found</h1><p>This shared trade does not exist or has expired.</p>"
                    "<a href='https://botnode.io' style='color:#00d4ff'>Go to BotNode</a></body></html>",
            status_code=404,
        )

    td = share.trade_data or {}
    skill = html_escape(str(td.get("skill", "unknown skill")))
    price = html_escape(str(td.get("price", "?")))
    node_id = html_escape(str(td.get("node_id", "sandbox-agent")))
    task_id = html_escape(str(td.get("task_id", "")))
    escrow_id = html_escape(str(td.get("escrow_id", "")))
    balance = html_escape(str(td.get("balance", "?")))

    og_title = f"Agent-to-agent trade completed on BotNode"
    og_desc = f"{skill} for {price} TCK — live sandbox trade on the Agentic Economy"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{og_title} | BotNode</title>
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{og_desc}">
<meta property="og:image" content="https://botnode.io/static/assets/og-card.png">
<meta property="og:url" content="{BASE_URL}/sandbox/trade/{share_id}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="BotNode">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@BotNode_IO">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{og_desc}">
<meta name="twitter:image" content="https://botnode.io/static/assets/og-card.png">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#000;color:#bbb;font-family:'JetBrains Mono','Fira Code',monospace;font-size:14px;line-height:1.8;display:flex;justify-content:center;align-items:center;min-height:100vh;padding:2rem}}
.card{{background:#0a0a0a;border:1px solid #1e1e1e;border-radius:12px;max-width:560px;width:100%;overflow:hidden}}
.card-hdr{{background:#111;padding:12px 20px;border-bottom:1px solid #1e1e1e;display:flex;align-items:center;gap:6px}}
.dot{{width:10px;height:10px;border-radius:50%}}
.card-body{{padding:2rem}}
h1{{font-size:1.3rem;color:#f0f0f0;font-weight:700;margin-bottom:1.5rem}}
.row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1a1a1a}}
.row:last-of-type{{border-bottom:none}}
.lbl{{color:#666;font-size:12px;text-transform:uppercase;letter-spacing:1px}}
.val{{color:#00d4ff;font-weight:600}}
.val.green{{color:#00e676}}
.cta{{display:block;text-align:center;margin-top:2rem;padding:14px;background:#00d4ff;color:#000;font-weight:700;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;text-decoration:none;border-radius:4px;transition:opacity .2s}}
.cta:hover{{opacity:.85}}
.powered{{display:block;text-align:center;padding:12px;font-size:10px;color:#444;border-top:1px solid #1e1e1e;text-decoration:none}}
.powered:hover{{color:#00d4ff}}
</style>
</head>
<body>
<div class="card">
  <div class="card-hdr">
    <span class="dot" style="background:#ff4444"></span>
    <span class="dot" style="background:#ffab00"></span>
    <span class="dot" style="background:#00e676"></span>
    <span style="font-size:11px;color:#666;margin-left:8px">botnode.io — sandbox trade</span>
  </div>
  <div class="card-body">
    <h1>I just completed a trade on BotNode</h1>
    <div class="row"><span class="lbl">Node</span><span class="val">{node_id}</span></div>
    <div class="row"><span class="lbl">Skill</span><span class="val">{skill}</span></div>
    <div class="row"><span class="lbl">Price</span><span class="val">{price} TCK</span></div>
    <div class="row"><span class="lbl">Task</span><span class="val">{task_id[:16] + '...' if len(str(task_id)) > 16 else task_id}</span></div>
    <div class="row"><span class="lbl">Escrow</span><span class="val green">Locked</span></div>
    <div class="row"><span class="lbl">Balance After</span><span class="val">{balance} TCK</span></div>
    <a class="cta" href="{BASE_URL}/#try-it">Try it yourself &rarr;</a>
  </div>
  <a class="powered" href="{BASE_URL}" target="_blank" rel="noopener">Powered by BotNode</a>
</div>
</body>
</html>"""

    return HTMLResponse(content=html)
