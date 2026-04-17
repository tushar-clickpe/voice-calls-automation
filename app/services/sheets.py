"""Google Sheets service - read-only import of contacts from Google Sheets."""

import re
import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path
from typing import Optional

from app.config import GOOGLE_SERVICE_ACCOUNT_FILE

_client: Optional[gspread.Client] = None

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _get_client() -> gspread.Client:
    """Get or create a gspread client using service account credentials."""
    global _client
    if _client is None:
        creds_path = Path(GOOGLE_SERVICE_ACCOUNT_FILE)
        if not creds_path.exists():
            raise FileNotFoundError(
                f"Google service account file not found at {creds_path}. "
                "Please download it from Google Cloud Console and place it there."
            )
        creds = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


def extract_sheet_id(url: str) -> str:
    """Extract the spreadsheet ID from a Google Sheets URL."""
    # Handles URLs like:
    # https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit#gid=0
    # https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if match:
        return match.group(1)
    # Maybe it's just the ID itself
    if re.match(r"^[a-zA-Z0-9-_]+$", url):
        return url
    raise ValueError(f"Could not extract spreadsheet ID from: {url}")


def read_sheet(
    sheet_url: str,
    worksheet_index: int = 0,
    phone_column: str = None,
    name_column: str = None,
) -> list[dict]:
    """Read all rows from a Google Sheet and return as list of dicts.

    Args:
        sheet_url: Google Sheets URL or spreadsheet ID
        worksheet_index: Which worksheet tab to read (0 = first)
        phone_column: Name of the column containing phone numbers (auto-detected if None)
        name_column: Name of the column containing names (auto-detected if None)

    Returns:
        List of dicts with 'phone', 'name', and any extra columns
    """
    client = _get_client()
    sheet_id = extract_sheet_id(sheet_url)
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.get_worksheet(worksheet_index)

    # Get all records (first row = headers)
    records = worksheet.get_all_records()

    if not records:
        return []

    # Auto-detect phone column
    headers = list(records[0].keys())
    phone_col = _find_column(headers, phone_column, ["phone", "mobile", "number", "contact", "tel", "cell", "whatsapp"])
    name_col = _find_column(headers, name_column, ["name", "customer", "client", "person", "full name", "customer name"])

    if not phone_col:
        raise ValueError(
            f"Could not auto-detect phone column. Available columns: {headers}. "
            "Please specify the phone column name."
        )

    contacts = []
    for row in records:
        phone = str(row.get(phone_col, "")).strip()
        if not phone:
            continue

        # Normalize phone: ensure it's a string, remove spaces/dashes
        phone = re.sub(r"[\s\-\(\)]", "", phone)
        # Remove .0 from numbers that got cast to float
        if phone.endswith(".0"):
            phone = phone[:-2]

        contact = {
            "phone": phone,
            "name": str(row.get(name_col, "")) if name_col else "",
        }

        # Include all other columns as extra data
        for key, value in row.items():
            if key not in (phone_col, name_col):
                contact[key] = str(value) if value is not None else ""

        contacts.append(contact)

    return contacts


def _find_column(headers: list[str], explicit: str = None, keywords: list[str] = None) -> Optional[str]:
    """Find a column by explicit name or keyword matching."""
    if explicit:
        # Case-insensitive match
        for h in headers:
            if h.lower().strip() == explicit.lower().strip():
                return h
        return None

    if keywords:
        for h in headers:
            h_lower = h.lower().strip()
            for kw in keywords:
                if kw in h_lower:
                    return h
    return None


def get_sheet_headers(sheet_url: str, worksheet_index: int = 0) -> list[str]:
    """Get just the column headers from a sheet (for preview/column mapping)."""
    client = _get_client()
    sheet_id = extract_sheet_id(sheet_url)
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.get_worksheet(worksheet_index)
    return worksheet.row_values(1)


def get_sheet_preview(sheet_url: str, worksheet_index: int = 0, rows: int = 5) -> list[dict]:
    """Get a preview of the first N rows from the sheet."""
    client = _get_client()
    sheet_id = extract_sheet_id(sheet_url)
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.get_worksheet(worksheet_index)
    records = worksheet.get_all_records()
    return records[:rows]
