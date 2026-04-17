"""Webhook routes - receives results from n8n after processing each contact."""

import logging
from fastapi import APIRouter, Request

from app.db import database as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks")


@router.post("/n8n-result")
async def n8n_result_callback(request: Request):
    """Receive a result from n8n for a single contact.

    Expected payload from n8n:
    {
        "batch_id": 5,
        "campaign_id": 1,
        "contact_id": 123,
        "phone": "+91xxxxxxxxxx",
        "call_status": "connected" | "no_answer" | "failed" | "busy",
        "whatsapp_status": "sent" | "delivered" | "failed",
        "smartflo_response": { ... }  // optional raw response
    }
    """
    try:
        data = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid JSON"}

    batch_id = data.get("batch_id")
    campaign_id = data.get("campaign_id")
    contact_id = data.get("contact_id")
    phone = data.get("phone", "")
    call_status = data.get("call_status", "failed")
    whatsapp_status = data.get("whatsapp_status")
    smartflo_response = data.get("smartflo_response")

    # Resolve contact - prefer contact_id, fall back to phone + campaign_id
    if not contact_id and phone and campaign_id:
        contact = await db.get_contact_by_phone_and_campaign(phone, campaign_id)
        if contact:
            contact_id = contact["id"]

    if not contact_id:
        logger.warning(f"n8n result: could not resolve contact. Data: {data}")
        return {"success": False, "error": "Could not resolve contact"}

    # Normalize status
    status_map = {
        "connected": "connected",
        "answered": "connected",
        "picked_up": "connected",
        "success": "connected",
        "no_answer": "no_answer",
        "no answer": "no_answer",
        "unanswered": "no_answer",
        "not_answered": "no_answer",
        "busy": "no_answer",
        "ringing": "no_answer",
        "failed": "failed",
        "error": "failed",
        "invalid": "failed",
    }
    normalized_status = status_map.get(call_status.lower().strip(), "failed")

    # Verify contact exists before updating
    db_conn = await db.get_db()
    cursor = await db_conn.execute("SELECT id FROM contacts WHERE id = ?", (contact_id,))
    if not await cursor.fetchone():
        logger.warning(f"n8n result: contact {contact_id} not found in database")
        return {"success": False, "error": f"Contact {contact_id} not found"}

    # Update contact result
    await db.update_contact_result(
        contact_id=contact_id,
        status=normalized_status,
        call_status=call_status,
        whatsapp_status=whatsapp_status,
        smartflo_response=smartflo_response,
        batch_id=batch_id,
    )

    # Update batch counters
    if batch_id:
        await db.update_batch_result_counts(batch_id, normalized_status)

    # Update daily stats
    if campaign_id:
        await db.increment_daily_stat(campaign_id, normalized_status)

    logger.info(
        f"Result received: contact={contact_id} phone={phone} "
        f"status={normalized_status} batch={batch_id}"
    )

    return {"success": True, "contact_id": contact_id, "status": normalized_status}


@router.post("/n8n-batch-complete")
async def n8n_batch_complete(request: Request):
    """Optional: n8n can call this when an entire batch is done processing.

    If n8n sends individual results via /n8n-result, this endpoint is not strictly
    needed — the batch engine auto-detects completion by counting results.
    But having this explicit signal is more reliable.

    Expected payload:
    {
        "batch_id": 5,
        "campaign_id": 1
    }
    """
    try:
        data = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid JSON"}

    batch_id = data.get("batch_id")
    if not batch_id:
        return {"success": False, "error": "batch_id required"}

    batch = await db.get_batch(batch_id)
    if not batch:
        return {"success": False, "error": "Batch not found"}

    if batch["status"] != "completed":
        await db.update_batch_status(batch_id, "completed")
        logger.info(f"Batch {batch_id} marked as completed via explicit callback")

    return {"success": True}
