"""Campaign routes - CRUD, import from file upload, start/pause/stop."""

import logging
from fastapi import APIRouter, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import database as db
from app.services import file_parser, batch_engine
from app.config import (
    DEFAULT_BATCH_SIZE, DEFAULT_MAX_ATTEMPTS, DEFAULT_DAILY_TARGET,
    MAX_UPLOAD_SIZE, N8N_WEBHOOK_URLS,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _render(request: Request, template: str, context: dict = None):
    """Helper to render templates with the correct Starlette 1.0 API."""
    return request.app.state.templates.TemplateResponse(request, template, context=context)


@router.get("/campaigns", response_class=HTMLResponse)
async def list_campaigns(request: Request):
    """List all campaigns."""
    campaigns = await db.get_all_campaigns()

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
async def preview_file(file: UploadFile = File(...)):
    """Preview uploaded file columns and first few rows."""
    if not file.filename:
        return {"success": False, "error": "No file selected"}

    try:
        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            return {"success": False, "error": "File too large. Max 10MB."}

        headers, preview = file_parser.get_file_preview(content, file.filename, rows=5)
        clean_preview = []
        for row in preview:
            clean_preview.append({k: str(v) if v is not None else "" for k, v in row.items()})

        return {
            "success": True,
            "headers": headers,
            "preview": clean_preview,
            "row_count": len(clean_preview),
            "filename": file.filename,
        }
    except Exception as e:
        logger.error(f"File preview error: {e}")
        return {"success": False, "error": str(e)}


@router.post("/campaigns/import")
async def import_campaign(
    request: Request,
    name: str = Form(...),
    file: UploadFile = File(...),
    phone_column: str = Form(""),
    name_column: str = Form(""),
    batch_size: int = Form(DEFAULT_BATCH_SIZE),
    max_attempts: int = Form(DEFAULT_MAX_ATTEMPTS),
    daily_target: int = Form(DEFAULT_DAILY_TARGET),
):
    """Import contacts from uploaded CSV/XLSX file and create a campaign."""
    error_context = {
        "default_batch_size": batch_size,
        "default_max_attempts": max_attempts,
        "default_daily_target": daily_target,
    }

    if not file.filename:
        error_context["error"] = "No file selected. Please upload a CSV or XLSX file."
        return _render(request, "import.html", error_context)

    try:
        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            error_context["error"] = "File too large. Maximum size is 10MB."
            return _render(request, "import.html", error_context)

        contacts = file_parser.parse_uploaded_file(
            content,
            file.filename,
            phone_column=phone_column if phone_column.strip() else None,
            name_column=name_column if name_column.strip() else None,
        )

        if not contacts:
            error_context["error"] = (
                "No contacts found in the file. Check that the file has data rows "
                "and a column with phone numbers."
            )
            return _render(request, "import.html", error_context)

        campaign = await db.create_campaign(
            name=name,
            sheet_url=file.filename,  # Store original filename as reference
            batch_size=batch_size,
            max_attempts=max_attempts,
            daily_target=daily_target,
        )

        inserted = await db.bulk_insert_contacts(campaign["id"], contacts)

        logger.info(
            f"Campaign '{name}' created with {inserted} contacts from {file.filename}"
        )
        return RedirectResponse(f"/campaigns/{campaign['id']}", status_code=303)

    except ValueError as e:
        error_context["error"] = str(e)
        return _render(request, "import.html", error_context)
    except Exception as e:
        logger.error(f"Import error: {e}", exc_info=True)
        error_context["error"] = f"Failed to import: {str(e)}"
        return _render(request, "import.html", error_context)


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

    status_filter = request.query_params.get("status", None)
    page = int(request.query_params.get("page", 1))
    per_page = 50
    contacts = await db.get_contacts_by_campaign(
        campaign_id, status=status_filter, limit=per_page, offset=(page - 1) * per_page
    )

    # Get available n8n slots for the dropdown
    used_slots = await db.get_used_n8n_slots()
    n8n_slots = []
    for slot_num, url in N8N_WEBHOOK_URLS.items():
        if url:  # Only show slots that have a URL configured
            in_use_by = None
            if slot_num in used_slots:
                # Find which campaign is using it
                for other_c in await db.get_active_campaigns():
                    if other_c.get("n8n_slot") == slot_num and other_c["id"] != campaign_id:
                        in_use_by = other_c["name"]
                        break
            n8n_slots.append({
                "slot": slot_num,
                "url": url,
                "available": slot_num not in used_slots or campaign.get("n8n_slot") == slot_num,
                "in_use_by": in_use_by,
                "is_current": campaign.get("n8n_slot") == slot_num,
            })

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
        "n8n_slots": n8n_slots,
    })


@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(request: Request, campaign_id: int):
    # Accept slot from JSON body or query param
    slot = None
    try:
        body = await request.json()
        slot = body.get("slot")
    except Exception:
        pass
    if slot is not None:
        slot = int(slot)
    result = await batch_engine.start_campaign(campaign_id, preferred_slot=slot)
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: int):
    result = await batch_engine.pause_campaign(campaign_id)
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


@router.post("/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: int):
    result = await batch_engine.stop_campaign(campaign_id)
    if not result["success"]:
        raise HTTPException(400, result["error"])
    return result


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int):
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    if batch_engine.is_campaign_running(campaign_id):
        await batch_engine.stop_campaign(campaign_id)

    await db.delete_campaign(campaign_id)
    return {"success": True}
