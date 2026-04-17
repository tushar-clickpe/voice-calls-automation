"""Batch Engine - orchestrates campaign execution with auto-batching and retry logic."""

import asyncio
import logging
from typing import Optional

from app.db import database as db
from app.services.n8n_trigger import send_batch_to_n8n, get_available_slot

logger = logging.getLogger(__name__)

# Track running campaign tasks so we can cancel them
_running_tasks: dict[int, asyncio.Task] = {}


async def start_campaign(campaign_id: int) -> dict:
    """Start or resume processing a campaign.

    Assigns an n8n slot and begins dispatching batches.
    Returns status dict.
    """
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found"}

    if campaign["status"] not in ("active", "paused"):
        return {"success": False, "error": f"Campaign is {campaign['status']}, cannot start"}

    # Check if already running
    if campaign_id in _running_tasks and not _running_tasks[campaign_id].done():
        return {"success": False, "error": "Campaign is already running"}

    # Check for running batch (means n8n is still processing)
    running_batch = await db.get_running_batch_for_campaign(campaign_id)
    if running_batch:
        return {
            "success": False,
            "error": f"Batch #{running_batch['batch_number']} is still being processed by n8n. Wait for it to complete.",
        }

    # Assign n8n slot
    used_slots = await db.get_used_n8n_slots()
    slot = campaign.get("n8n_slot")

    if not slot or slot in used_slots:
        # Need a new slot
        slot = get_available_slot(used_slots)
        if slot is None:
            return {
                "success": False,
                "error": "All n8n workflow slots are in use. Stop another campaign first or wait for it to finish.",
            }
        await db.assign_n8n_slot(campaign_id, slot)

    # Mark active
    await db.update_campaign_status(campaign_id, "active")

    # Start the campaign loop in background
    task = asyncio.create_task(_campaign_loop(campaign_id))
    _running_tasks[campaign_id] = task

    logger.info(f"Campaign {campaign_id} started on n8n slot {slot}")
    return {"success": True, "slot": slot}


async def pause_campaign(campaign_id: int) -> dict:
    """Pause a campaign. Current batch in n8n finishes but no new batch is sent."""
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found"}

    # Cancel the background task (it will stop after current iteration)
    task = _running_tasks.get(campaign_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await db.update_campaign_status(campaign_id, "paused")
    # Don't release the slot — they might resume soon
    logger.info(f"Campaign {campaign_id} paused")
    return {"success": True}


async def stop_campaign(campaign_id: int) -> dict:
    """Stop a campaign completely. Releases n8n slot."""
    campaign = await db.get_campaign(campaign_id)
    if not campaign:
        return {"success": False, "error": "Campaign not found"}

    # Cancel background task
    task = _running_tasks.get(campaign_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Reset any in_progress contacts back to their previous state
    db_conn = await db.get_db()
    await db_conn.execute(
        """UPDATE contacts SET status = 'pending'
           WHERE campaign_id = ? AND status = 'in_progress'""",
        (campaign_id,),
    )
    # Also reset queued contacts
    await db_conn.execute(
        """UPDATE contacts SET status = 'pending'
           WHERE campaign_id = ? AND status = 'queued'""",
        (campaign_id,),
    )
    await db_conn.commit()

    await db.update_campaign_status(campaign_id, "stopped")
    await db.release_n8n_slot(campaign_id)

    logger.info(f"Campaign {campaign_id} stopped")
    return {"success": True}


async def _campaign_loop(campaign_id: int):
    """Main campaign processing loop. Runs in background."""
    try:
        while True:
            campaign = await db.get_campaign(campaign_id)
            if not campaign or campaign["status"] != "active":
                logger.info(f"Campaign {campaign_id} is no longer active, stopping loop")
                break

            slot = campaign["n8n_slot"]
            if not slot:
                logger.error(f"Campaign {campaign_id} has no n8n slot assigned")
                break

            # Check daily target
            daily = await db.get_or_create_daily_stats(campaign_id)
            if daily["attempted"] >= daily["target"]:
                logger.info(
                    f"Campaign {campaign_id} reached daily target ({daily['target']}). "
                    f"Pausing until tomorrow. Hit Resume to continue."
                )
                await db.update_campaign_status(campaign_id, "paused")
                await db.release_n8n_slot(campaign_id)
                break

            # Check if there's already a running batch
            running = await db.get_running_batch_for_campaign(campaign_id)
            if running:
                # Wait and check again
                logger.debug(f"Campaign {campaign_id} waiting for batch {running['id']} to complete")
                await asyncio.sleep(5)
                continue

            # Get next batch of contacts
            contacts = await db.get_next_batch_contacts(
                campaign_id, campaign["batch_size"], campaign["max_attempts"]
            )

            if not contacts:
                logger.info(f"Campaign {campaign_id} has no more contacts to process")
                await db.update_campaign_status(campaign_id, "completed")
                await db.release_n8n_slot(campaign_id)
                break

            # Mark contacts as in_progress
            contact_ids = [c["id"] for c in contacts]
            await db.mark_contacts_in_progress(contact_ids)

            # Create batch record
            batch_number = await db.get_next_batch_number(campaign_id)
            batch = await db.create_batch(campaign_id, batch_number, len(contacts))

            # Update daily stats
            await db.increment_daily_stat(campaign_id, "attempted", len(contacts))

            # Send to n8n
            result = await send_batch_to_n8n(slot, batch["id"], campaign_id, contacts)

            if not result["success"]:
                logger.error(f"Failed to send batch to n8n: {result.get('error')}")
                # Mark batch as failed
                await db.update_batch_status(batch["id"], "failed")
                # Reset contacts to pending
                db_conn = await db.get_db()
                placeholders = ",".join("?" for _ in contact_ids)
                await db_conn.execute(
                    f"""UPDATE contacts SET status = CASE
                        WHEN attempt_count > 0 THEN 'no_answer'
                        ELSE 'pending'
                    END WHERE id IN ({placeholders})""",
                    contact_ids,
                )
                await db_conn.commit()
                # Wait before retrying
                await asyncio.sleep(30)
                continue

            # Mark batch as running
            await db.update_batch_status(batch["id"], "running")

            logger.info(
                f"Campaign {campaign_id} batch #{batch_number} sent "
                f"({len(contacts)} contacts) to slot {slot}"
            )

            # Wait for batch to complete (n8n will call back for each contact)
            # We poll the batch status
            while True:
                await asyncio.sleep(5)

                # Re-check campaign status (might have been paused/stopped)
                campaign = await db.get_campaign(campaign_id)
                if not campaign or campaign["status"] != "active":
                    break

                batch_data = await db.get_batch(batch["id"])
                if batch_data and batch_data["status"] == "completed":
                    logger.info(f"Batch #{batch_number} completed")
                    break

                # Check if all results are in
                total_results = await db.count_batch_results(batch["id"])
                if total_results >= batch_data["size"]:
                    await db.update_batch_status(batch["id"], "completed")
                    logger.info(f"Batch #{batch_number} completed (all results received)")
                    break

            # Small delay between batches
            await asyncio.sleep(2)

    except asyncio.CancelledError:
        logger.info(f"Campaign {campaign_id} loop cancelled")
        raise
    except Exception as e:
        logger.error(f"Campaign {campaign_id} loop error: {e}", exc_info=True)
        await db.update_campaign_status(campaign_id, "paused")
    finally:
        _running_tasks.pop(campaign_id, None)


def is_campaign_running(campaign_id: int) -> bool:
    """Check if a campaign has an active background task."""
    task = _running_tasks.get(campaign_id)
    return task is not None and not task.done()


def get_running_campaign_ids() -> list[int]:
    """Get list of campaign IDs that have active background tasks."""
    return [cid for cid, task in _running_tasks.items() if not task.done()]
