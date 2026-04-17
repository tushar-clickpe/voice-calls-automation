"""Dashboard routes - main dashboard and stats API."""

import logging
from datetime import date
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db import database as db
from app.services import batch_engine

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    global_stats = await db.get_today_global_stats()
    campaigns = await db.get_all_campaigns()

    # Enrich campaigns with stats and running info
    enriched = []
    for c in campaigns:
        stats = await db.get_campaign_stats(c["id"])
        daily = await db.get_or_create_daily_stats(c["id"])
        running_batch = await db.get_running_batch_for_campaign(c["id"])
        c["stats"] = stats
        c["daily"] = daily
        c["is_running"] = batch_engine.is_campaign_running(c["id"])
        c["running_batch"] = running_batch
        enriched.append(c)

    recent = await db.get_recent_activity(limit=30)

    return request.app.state.templates.TemplateResponse(
        request,
        "dashboard.html",
        context={
            "global_stats": global_stats,
            "campaigns": enriched,
            "recent_activity": recent,
            "today": date.today().strftime("%B %d, %Y"),
        },
    )


@router.get("/api/stats/today")
async def today_stats():
    """API: Get today's global stats (for dashboard polling)."""
    global_stats = await db.get_today_global_stats()
    campaigns = await db.get_all_campaigns()

    campaign_stats = []
    for c in campaigns:
        stats = await db.get_campaign_stats(c["id"])
        daily = await db.get_or_create_daily_stats(c["id"])
        running_batch = await db.get_running_batch_for_campaign(c["id"])
        campaign_stats.append({
            "id": c["id"],
            "name": c["name"],
            "status": c["status"],
            "is_running": batch_engine.is_campaign_running(c["id"]),
            "stats": stats,
            "daily": daily,
            "running_batch": dict(running_batch) if running_batch else None,
        })

    return {
        "global_stats": global_stats,
        "campaigns": campaign_stats,
    }


@router.get("/api/stats/campaign/{campaign_id}")
async def campaign_stats_api(campaign_id: int):
    """API: Get stats for a specific campaign (for polling)."""
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        return {"error": "Campaign not found"}

    stats = await db.get_campaign_stats(campaign_id)
    daily = await db.get_or_create_daily_stats(campaign_id)
    running_batch = await db.get_running_batch_for_campaign(campaign_id)
    recent = await db.get_recent_activity(campaign_id, limit=15)

    return {
        "campaign": campaign,
        "stats": stats,
        "daily": daily,
        "is_running": batch_engine.is_campaign_running(campaign_id),
        "running_batch": dict(running_batch) if running_batch else None,
        "recent_activity": recent,
    }
