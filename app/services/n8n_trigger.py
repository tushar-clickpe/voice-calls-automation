"""n8n Trigger service - sends batches to n8n via webhooks and handles slot assignment."""

import httpx
import logging
from typing import Optional

from app.config import N8N_WEBHOOK_URLS, CALLBACK_BASE_URL

logger = logging.getLogger(__name__)


async def send_batch_to_n8n(
    slot: int,
    batch_id: int,
    campaign_id: int,
    contacts: list[dict],
) -> dict:
    """Send a batch of contacts to n8n via webhook.

    Args:
        slot: n8n webhook slot (1, 2, or 3)
        batch_id: Our batch ID for tracking
        campaign_id: Campaign ID for tracking
        contacts: List of contact dicts to process

    Returns:
        Response dict from n8n
    """
    webhook_url = N8N_WEBHOOK_URLS.get(slot)
    if not webhook_url:
        raise ValueError(f"No n8n webhook URL configured for slot {slot}")

    callback_url = f"{CALLBACK_BASE_URL}/api/webhooks/n8n-result"

    payload = {
        "batch_id": batch_id,
        "campaign_id": campaign_id,
        "callback_url": callback_url,
        "contacts": [
            {
                "id": c["id"],
                "phone": c["phone"],
                "name": c.get("name", ""),
                "extra_data": c.get("extra_data", "{}"),
                "attempt_number": c.get("attempt_count", 0) + 1,
            }
            for c in contacts
        ],
    }

    logger.info(
        f"Sending batch {batch_id} ({len(contacts)} contacts) to n8n slot {slot}: {webhook_url}"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
            logger.info(f"Batch {batch_id} sent successfully to n8n slot {slot}")
            return {"success": True, "status_code": response.status_code}
    except httpx.HTTPStatusError as e:
        logger.error(f"n8n returned error for batch {batch_id}: {e.response.status_code}")
        return {"success": False, "error": str(e), "status_code": e.response.status_code}
    except httpx.RequestError as e:
        logger.error(f"Failed to reach n8n for batch {batch_id}: {e}")
        return {"success": False, "error": str(e), "status_code": 0}


def get_available_slot(used_slots: list[int]) -> Optional[int]:
    """Find the first available n8n webhook slot.

    Returns:
        Available slot number (1-3) or None if all slots are in use
    """
    for slot in sorted(N8N_WEBHOOK_URLS.keys()):
        url = N8N_WEBHOOK_URLS.get(slot, "")
        if slot not in used_slots and url:
            return slot
    return None
