import aiosqlite
import json
from pathlib import Path
from datetime import date, datetime
from typing import Optional

from app.config import DATABASE_PATH

_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    """Get the database connection, creating it if needed."""
    global _db
    if _db is None:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(str(DATABASE_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def init_db():
    """Initialize the database with the schema."""
    db = await get_db()
    schema_path = Path(__file__).parent / "schema.sql"
    schema = schema_path.read_text()
    await db.executescript(schema)
    await db.commit()


async def close_db():
    """Close the database connection."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None


# ---------------------
# Campaign operations
# ---------------------

async def create_campaign(
    name: str,
    sheet_url: str = "",
    batch_size: int = 100,
    max_attempts: int = 2,
    daily_target: int = 400,
) -> dict:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO campaigns (name, sheet_url, batch_size, max_attempts, daily_target)
           VALUES (?, ?, ?, ?, ?)""",
        (name, sheet_url, batch_size, max_attempts, daily_target),
    )
    await db.commit()
    return await get_campaign(cursor.lastrowid)


async def get_campaign(campaign_id: int) -> Optional[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_all_campaigns() -> list[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM campaigns ORDER BY created_at DESC")
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_active_campaigns() -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM campaigns WHERE status = 'active' ORDER BY created_at ASC"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def update_campaign_status(campaign_id: int, status: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE campaigns SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, campaign_id),
    )
    await db.commit()


async def assign_n8n_slot(campaign_id: int, slot: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE campaigns SET n8n_slot = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (slot, campaign_id),
    )
    await db.commit()


async def release_n8n_slot(campaign_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE campaigns SET n8n_slot = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (campaign_id,),
    )
    await db.commit()


async def get_used_n8n_slots() -> list[int]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT n8n_slot FROM campaigns WHERE n8n_slot IS NOT NULL AND status = 'active'"
    )
    rows = await cursor.fetchall()
    return [row["n8n_slot"] for row in rows]


async def update_campaign_total_contacts(campaign_id: int) -> None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM contacts WHERE campaign_id = ?", (campaign_id,)
    )
    row = await cursor.fetchone()
    await db.execute(
        "UPDATE campaigns SET total_contacts = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (row["cnt"], campaign_id),
    )
    await db.commit()


async def delete_campaign(campaign_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
    await db.commit()


# ---------------------
# Contact operations
# ---------------------

async def bulk_insert_contacts(campaign_id: int, contacts: list[dict]) -> int:
    """Insert contacts in bulk. Returns count inserted."""
    db = await get_db()
    inserted = 0
    for contact in contacts:
        phone = contact.get("phone", "").strip()
        if not phone:
            continue
        name = contact.get("name", "")
        extra = {k: v for k, v in contact.items() if k not in ("phone", "name")}
        await db.execute(
            """INSERT INTO contacts (campaign_id, phone, name, extra_data)
               VALUES (?, ?, ?, ?)""",
            (campaign_id, phone, name, json.dumps(extra)),
        )
        inserted += 1
    await db.commit()
    await update_campaign_total_contacts(campaign_id)
    return inserted


async def get_next_batch_contacts(
    campaign_id: int, batch_size: int, max_attempts: int
) -> list[dict]:
    """Get the next batch of contacts to process.
    Priority: retries first (no_answer with attempts < max), then fresh pending contacts.
    """
    db = await get_db()

    # Retries first
    cursor = await db.execute(
        """SELECT * FROM contacts
           WHERE campaign_id = ? AND status = 'no_answer' AND attempt_count < ?
           ORDER BY last_attempt_at ASC
           LIMIT ?""",
        (campaign_id, max_attempts, batch_size),
    )
    retries = [dict(r) for r in await cursor.fetchall()]

    remaining = batch_size - len(retries)
    fresh = []
    if remaining > 0:
        cursor = await db.execute(
            """SELECT * FROM contacts
               WHERE campaign_id = ? AND status = 'pending'
               ORDER BY id ASC
               LIMIT ?""",
            (campaign_id, remaining),
        )
        fresh = [dict(r) for r in await cursor.fetchall()]

    return retries + fresh


async def mark_contacts_in_progress(contact_ids: list[int]) -> None:
    if not contact_ids:
        return
    db = await get_db()
    placeholders = ",".join("?" for _ in contact_ids)
    await db.execute(
        f"UPDATE contacts SET status = 'in_progress' WHERE id IN ({placeholders})",
        contact_ids,
    )
    await db.commit()


async def update_contact_result(
    contact_id: int, status: str, call_status: str = None, whatsapp_status: str = None,
    smartflo_response: str = None, batch_id: int = None,
) -> None:
    db = await get_db()
    # Update contact
    await db.execute(
        """UPDATE contacts
           SET status = ?, attempt_count = attempt_count + 1, last_attempt_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (status, contact_id),
    )
    # Get attempt number
    cursor = await db.execute(
        "SELECT attempt_count FROM contacts WHERE id = ?", (contact_id,)
    )
    row = await cursor.fetchone()
    attempt_number = row["attempt_count"] if row else 1

    # Insert call log
    await db.execute(
        """INSERT INTO call_logs (contact_id, batch_id, attempt_number, call_status, whatsapp_status, smartflo_response)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (contact_id, batch_id or 0, attempt_number, call_status, whatsapp_status,
         json.dumps(smartflo_response) if smartflo_response else "{}"),
    )
    await db.commit()


async def get_contact_by_phone_and_campaign(phone: str, campaign_id: int) -> Optional[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM contacts WHERE phone = ? AND campaign_id = ?",
        (phone, campaign_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_contacts_by_campaign(
    campaign_id: int, status: str = None, limit: int = 100, offset: int = 0
) -> list[dict]:
    db = await get_db()
    if status:
        cursor = await db.execute(
            """SELECT * FROM contacts WHERE campaign_id = ? AND status = ?
               ORDER BY id ASC LIMIT ? OFFSET ?""",
            (campaign_id, status, limit, offset),
        )
    else:
        cursor = await db.execute(
            """SELECT * FROM contacts WHERE campaign_id = ?
               ORDER BY id ASC LIMIT ? OFFSET ?""",
            (campaign_id, limit, offset),
        )
    return [dict(r) for r in await cursor.fetchall()]


# ---------------------
# Batch operations
# ---------------------

async def create_batch(campaign_id: int, batch_number: int, size: int) -> dict:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO batches (campaign_id, batch_number, size, status, started_at)
           VALUES (?, ?, ?, 'sent', CURRENT_TIMESTAMP)""",
        (campaign_id, batch_number, size),
    )
    await db.commit()
    batch_id = cursor.lastrowid
    row = await (await db.execute("SELECT * FROM batches WHERE id = ?", (batch_id,))).fetchone()
    return dict(row)


async def update_batch_status(batch_id: int, status: str) -> None:
    db = await get_db()
    extra = ", completed_at = CURRENT_TIMESTAMP" if status == "completed" else ""
    await db.execute(
        f"UPDATE batches SET status = ?{extra} WHERE id = ?",
        (status, batch_id),
    )
    await db.commit()


async def update_batch_result_counts(batch_id: int, result: str) -> None:
    """Increment the appropriate counter on a batch."""
    db = await get_db()
    col_map = {
        "connected": "connected_count",
        "no_answer": "no_answer_count",
        "failed": "failed_count",
    }
    col = col_map.get(result)
    if col:
        await db.execute(
            f"UPDATE batches SET {col} = {col} + 1 WHERE id = ?", (batch_id,)
        )
        await db.commit()


async def get_batch(batch_id: int) -> Optional[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM batches WHERE id = ?", (batch_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_campaign_batches(campaign_id: int) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM batches WHERE campaign_id = ? ORDER BY batch_number ASC",
        (campaign_id,),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_next_batch_number(campaign_id: int) -> int:
    db = await get_db()
    cursor = await db.execute(
        "SELECT COALESCE(MAX(batch_number), 0) + 1 as next_num FROM batches WHERE campaign_id = ?",
        (campaign_id,),
    )
    row = await cursor.fetchone()
    return row["next_num"]


async def get_running_batch_for_campaign(campaign_id: int) -> Optional[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM batches WHERE campaign_id = ? AND status IN ('sent', 'running') LIMIT 1",
        (campaign_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def count_batch_results(batch_id: int) -> int:
    """Count how many results we've received for a batch."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT connected_count + no_answer_count + failed_count as total
           FROM batches WHERE id = ?""",
        (batch_id,),
    )
    row = await cursor.fetchone()
    return row["total"] if row else 0


# ---------------------
# Stats operations
# ---------------------

async def get_or_create_daily_stats(campaign_id: int) -> dict:
    db = await get_db()
    today = date.today().isoformat()
    cursor = await db.execute(
        "SELECT * FROM daily_stats WHERE date = ? AND campaign_id = ?",
        (today, campaign_id),
    )
    row = await cursor.fetchone()
    if row:
        return dict(row)
    # Get campaign target
    campaign = await get_campaign(campaign_id)
    target = campaign["daily_target"] if campaign else 400
    cursor = await db.execute(
        """INSERT INTO daily_stats (date, campaign_id, target)
           VALUES (?, ?, ?)""",
        (today, campaign_id, target),
    )
    await db.commit()
    return {
        "id": cursor.lastrowid, "date": today, "campaign_id": campaign_id,
        "target": target, "attempted": 0, "connected": 0, "no_answer": 0, "failed": 0,
    }


async def increment_daily_stat(campaign_id: int, field: str, count: int = 1) -> None:
    db = await get_db()
    today = date.today().isoformat()
    await get_or_create_daily_stats(campaign_id)
    valid_fields = ("attempted", "connected", "no_answer", "failed")
    if field not in valid_fields:
        return
    await db.execute(
        f"UPDATE daily_stats SET {field} = {field} + ? WHERE date = ? AND campaign_id = ?",
        (count, today, campaign_id),
    )
    await db.commit()


async def get_today_global_stats() -> dict:
    db = await get_db()
    today = date.today().isoformat()
    cursor = await db.execute(
        """SELECT
             COALESCE(SUM(target), 0) as target,
             COALESCE(SUM(attempted), 0) as attempted,
             COALESCE(SUM(connected), 0) as connected,
             COALESCE(SUM(no_answer), 0) as no_answer,
             COALESCE(SUM(failed), 0) as failed
           FROM daily_stats WHERE date = ?""",
        (today,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else {
        "target": 0, "attempted": 0, "connected": 0, "no_answer": 0, "failed": 0,
    }


async def get_campaign_stats(campaign_id: int) -> dict:
    """Get aggregate stats for a campaign."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT
             COUNT(*) as total,
             SUM(CASE WHEN contacts.status = 'pending' THEN 1 ELSE 0 END) as pending,
             SUM(CASE WHEN contacts.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
             SUM(CASE WHEN contacts.status = 'connected' THEN 1 ELSE 0 END) as connected,
             SUM(CASE WHEN contacts.status = 'no_answer' THEN 1 ELSE 0 END) as no_answer,
             SUM(CASE WHEN contacts.status = 'failed' THEN 1 ELSE 0 END) as failed,
             SUM(CASE WHEN contacts.status = 'no_answer' AND contacts.attempt_count < c.max_attempts THEN 1 ELSE 0 END) as retries_pending
           FROM contacts
           JOIN campaigns c ON c.id = contacts.campaign_id
           WHERE contacts.campaign_id = ?""",
        (campaign_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else {}


async def get_recent_activity(campaign_id: int = None, limit: int = 20) -> list[dict]:
    db = await get_db()
    if campaign_id:
        cursor = await db.execute(
            """SELECT cl.*, ct.phone, ct.name as contact_name, ct.status as contact_status
               FROM call_logs cl
               JOIN contacts ct ON ct.id = cl.contact_id
               WHERE ct.campaign_id = ?
               ORDER BY cl.created_at DESC LIMIT ?""",
            (campaign_id, limit),
        )
    else:
        cursor = await db.execute(
            """SELECT cl.*, ct.phone, ct.name as contact_name, ct.campaign_id,
                      ct.status as contact_status
               FROM call_logs cl
               JOIN contacts ct ON ct.id = cl.contact_id
               ORDER BY cl.created_at DESC LIMIT ?""",
            (limit,),
        )
    return [dict(r) for r in await cursor.fetchall()]
