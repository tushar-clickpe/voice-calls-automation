"""Campaign routes - CRUD, import from Google Sheets, start/pause/stop."""

import asyncio
import logging
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import database as db
from app.services import sheets, batch_engine
from app.config import DEFAULT_BATCH_SIZE, DEFAULT_MAX_ATTEMPTS, DEFAULT_DAILY_TARGET

logger = logging.getLogger(__name__)

router = APIRouter()


def _render(request: Request, template: str, context: dict = None):
    """Helper to render templates with the correct Starlette 1.0 API."""
    return request.app.state.templates.TemplateResponse(request, template, context=context)


@router.get("/campaigns", response_class=HTMLResponse)
async def list_campaigns(request: Request):
    """List all campaigns."""
    campaigns = await db.get_all_campaigns()

    # Enrich with stats and running status
    enriched = []
    for c in campaigns:
        stats = await db.get_campaign_stats(c["id"])
        c["stats"] = stats
        c["is_running"] = batch_engine.is_campaign_running(c["id"])
        enriched.append(c)

    return _render(request, "campaigns.html", {"campaigns": enriched})


@router.get("/campaigns/new", response_class=HTMLResponse)
async def new_campaign_form(request: Request):
    """Show the import form."""
    return _render(request, "import.html", {
        "default_batch_size": DEFAULT_BATCH_SIZE,
        "default_max_attempts": DEFAULT_MAX_ATTEMPTS,
        "default_daily_target": DEFAULT_DAILY_TARGET,
    })


@router.post("/campaigns/preview")
async def preview_sheet(request: Request):
    """Preview Google Sheet columns and first few rows."""
    form = await request.form()
    sheet_url = form.get("sheet_url", "").strip()

    if not sheet_url:
        raise HTTPException(400, "Sheet URL is required")

    try:
        headers = sheets.get_sheet_headers(sheet_url)
        preview = sheets.get_sheet_preview(sheet_url, rows=5)
        return {
            "success": True,
            "headers": headers,
            "preview": preview,
            "row_count": len(preview),
        }
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"Sheet preview error: {e}")
        return {"success": False, "error": str(e)}


@router.post("/campaigns/import")
async def import_campaign(
    request: Request,
    name: str = Form(...),
    sheet_url: str = Form(...),
    phone_column: str = Form(None),
    name_column: str = Form(None),
    batch_size: int = Form(DEFAULT_BATCH_SIZE),
    max_attempts: int = Form(DEFAULT_MAX_ATTEMPTS),
    daily_target: int = Form(DEFAULT_DAILY_TARGET),
):
    """Import contacts from Google Sheet and create a campaign."""
    try:
        # Read contacts from sheet
        contacts = sheets.read_sheet(
            sheet_url,
            phone_column=phone_column if phone_column else None,
            name_column=name_column if name_column else None,
        )

        if not contacts:
            return _render(request, "import.html", {
                "error": "No contacts found in the sheet. Check that the sheet has data and the phone column is detectable.",
                "default_batch_size": batch_size,
                "default_max_attempts": max_attempts,
                "default_daily_target": daily_target,
            })

        # Create campaign
        campaign = await db.create_campaign(
            name=name,
            sheet_url=sheet_url,
            batch_size=batch_size,
            max_attempts=max_attempts,
            daily_target=daily_target,
        )

        # Bulk insert contacts
        inserted = await db.bulk_insert_contacts(campaign["id"], contacts)

        logger.info(f"Campaign '{name}' created with {inserted} contacts from sheet")
        return RedirectResponse(f"/campaigns/{campaign['id']}", status_code=303)

    except FileNotFoundError as e:
        return _render(request, "import.html", {
            "error": str(e),
            "default_batch_size": batch_size,
            "default_max_attempts": max_attempts,
            "default_daily_target": daily_target,
        })
    except Exception as e:
        logger.error(f"Import error: {e}", exc_info=True)
        return _render(request, "import.html", {
            "error": f"Failed to import: {str(e)}",
            "default_batch_size": batch_size,
            "default_max_attempts": max_attempts,
            "default_daily_target": daily_target,
        })


@router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
async def campaign_detail(request: Request, campaign_id: int):
    """Campaign detail page."""
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    stats = await db.get_campaign_stats(campaign_id)
    batches = await db.get_campaign_batches(campaign_id)
    daily = await db.get_or_create_daily_stats(campaign_id)
    recent = await db.get_recent_activity(campaign_id, limit=30)
    is_running = batch_engine.is_campaign_running(campaign_id)

    # Get contacts with pagination
    status_filter = request.query_params.get("status", None)
    page = int(request.query_params.get("page", 1))
    per_page = 50
    contacts = await db.get_contacts_by_campaign(
        campaign_id, status=status_filter, limit=per_page, offset=(page - 1) * per_page
    )

    return _render(request, "campaign_detail.html", {
        "campaign": campaign,
        "stats": stats,
        "batches": batches,
        "daily": daily,
        "recent_activity": recent,
        "contacts": contacts,
        "is_running": is_running,
        "status_filter": status_filter,
        "page": page,
        "per_page": per_page,
    })


@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: int):
    """Start or resume a campaign."""
    result = await batch_engine.start_campaign(campaign_id)
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: int):
    """Pause a campaign."""
    result = await batch_engine.pause_campaign(campaign_id)
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


@router.post("/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: int):
    """Stop a campaign completely."""
    result = await batch_engine.stop_campaign(campaign_id)
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int):
    """Delete a campaign and all its data."""
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # Stop if running
    if batch_engine.is_campaign_running(campaign_id):
        await batch_engine.stop_campaign(campaign_id)

    await db.delete_campaign(campaign_id)
    return {"success": True}
