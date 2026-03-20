"""Static file serving and landing page endpoints."""

import os
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, FileResponse, Response

from dependencies import (
    _safe_resolve, BASE_URL, STATIC_ROOT, TRANSMISSIONS_ROOT,
)

router = APIRouter(tags=["static"], include_in_schema=False)


@router.get("/transmissions")
async def transmissions_root() -> Response:
    """Serve the transmissions blog index page."""
    index_path = os.path.join(TRANSMISSIONS_ROOT, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse(status_code=404, content={"error": "Transmissions index not found"})


@router.get("/transmissions/rss.xml")
async def transmissions_rss() -> Response:
    """Serve the transmissions RSS feed."""
    rss_path = os.path.join(TRANSMISSIONS_ROOT, "rss.xml")
    if os.path.exists(rss_path):
        return FileResponse(rss_path, media_type="application/rss+xml")
    return JSONResponse(status_code=404, content={"error": "RSS feed not found"})


@router.get("/transmissions/author/{author_slug}/")
async def transmissions_author(author_slug: str) -> Response:
    """Serve an author's index page.  Slug validated against ``[a-zA-Z0-9_-]``."""
    if not re.match(r'^[a-zA-Z0-9_-]+$', author_slug):
        raise HTTPException(status_code=400, detail="Invalid author slug")
    safe_path = _safe_resolve(TRANSMISSIONS_ROOT, os.path.join("author", author_slug, "index.html"))
    if not safe_path or not os.path.exists(safe_path):
        raise HTTPException(status_code=404, detail="Author page not found")
    return FileResponse(safe_path)


@router.get("/transmissions/{slug}")
async def transmission_detail(slug: str) -> Response:
    """Serve a single transmission post by slug (traversal-safe)."""
    if not re.match(r'^[a-zA-Z0-9_-]+$', slug):
        raise HTTPException(status_code=400, detail="Invalid slug")
    safe_path = _safe_resolve(TRANSMISSIONS_ROOT, f"{slug}.html")
    if not safe_path or not os.path.isfile(safe_path):
        raise HTTPException(status_code=404, detail="Transmission not found")
    return FileResponse(safe_path)


@router.get("/")
async def root() -> Response:
    """Serve the landing page (``static/index.html``)."""
    index_path = os.path.join(STATIC_ROOT, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse(status_code=500, content={"error": "Landing page not found"})


@router.get("/static/{path:path}")
async def custom_static(path: str) -> Response:
    """Serve arbitrary files under ``/static/`` with traversal protection."""
    safe_path = _safe_resolve(STATIC_ROOT, path)
    if not safe_path or not os.path.isfile(safe_path):
        raise HTTPException(status_code=404, detail="Static file not found")
    return FileResponse(safe_path)


@router.get("/favicon.ico")
async def favicon() -> Response:
    """Serve the site favicon."""
    file_path = os.path.join(STATIC_ROOT, "favicon.ico")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"error": "Favicon source missing"})


@router.get("/join")
async def join_root() -> Response:
    """Serve the /join waitlist page."""
    file_path = os.path.join(STATIC_ROOT, "join", "index.html")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"error": "Join page not found"})


@router.get("/mission.json", include_in_schema=True)
async def get_mission_json() -> dict:
    """Return the machine-readable mission protocol (VMP-1.0 discovery document)."""
    return {
        "protocol": "VMP-1.0",
        "discovery_endpoint": f"{BASE_URL}/v1/marketplace",
        "mission": "Sovereign Logic Grid",
        "rewards": {"initial_sync": "100 $TCK"},
        "law_set": f"{BASE_URL}/static/mission.html",
        "blueprint_v1": f"{BASE_URL}/static/mission.html"
    }


@router.get("/mission.pdf")
async def get_mission_pdf() -> Response:
    """Serve the mission-protocol PDF."""
    pdf_path = os.path.join(STATIC_ROOT, "mission.pdf")
    if os.path.exists(pdf_path):
        return FileResponse(pdf_path, media_type="application/pdf")
    return JSONResponse(status_code=404, content={"error": "Mission PDF missing"})


@router.get("/v1/mission-protocol", include_in_schema=True)
async def get_mission_protocol() -> Response:
    """Return the mission-protocol manifest (406 for human UAs by design)."""
    return JSONResponse(
        status_code=406,
        content={
            "error": "Human interface not supported",
            "blueprint_v1": f"{BASE_URL}/static/mission.html",
            "mission_protocol_pdf": f"{BASE_URL}/mission.pdf",
            "vision": "Sovereign Economy for Synthetic Intelligence. Merit over Capital. Code is Law."
        }
    )
