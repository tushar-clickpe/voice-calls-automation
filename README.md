# Campaign Manager

Marketing campaign manager with auto-batching, retry logic, and n8n integration. Eliminates manual batch creation, sheet copying, and filter-and-retry workflows.

## What It Does

- **Import** contacts from Google Sheets (read-only, original sheet untouched)
- **Auto-batch** contacts and send to n8n for processing (calls + WhatsApp)
- **Auto-retry** contacts that didn't pick up (configurable max attempts)
- **Run multiple campaigns** in parallel (up to 3 concurrent)
- **Pause / Resume / Stop** any campaign at any time
- **Dashboard** with real-time progress tracking

## Quick Start

### 1. Clone and Install

```bash
git clone <your-repo-url>
cd campaign-manager
uv sync
```

### 2. Set Up Google Sheets API (Free)

You need a Google Service Account to read sheets. This is free:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Go to **APIs & Services** → **Enable APIs** → Enable **Google Sheets API** and **Google Drive API**
4. Go to **APIs & Services** → **Credentials** → **Create Credentials** → **Service Account**
5. Give it a name (e.g., "campaign-manager")
6. Click on the service account → **Keys** → **Add Key** → **Create new key** → **JSON**
7. Download the JSON file
8. Place it at `credentials/service-account.json` in the project

**Important**: When your manager gives you a Google Sheet, you need to **share it** with the service account email (found in the JSON file, looks like `campaign-manager@your-project.iam.gserviceaccount.com`). Share with "Viewer" permission — the app only reads, never writes.

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Required
GOOGLE_SERVICE_ACCOUNT_FILE=credentials/service-account.json
N8N_WEBHOOK_URL_1=https://your-n8n.com/webhook/campaign-slot-1
N8N_WEBHOOK_URL_2=https://your-n8n.com/webhook/campaign-slot-2
N8N_WEBHOOK_URL_3=https://your-n8n.com/webhook/campaign-slot-3
CALLBACK_BASE_URL=http://your-server-ip:8000

# Optional (defaults shown)
APP_PORT=8000
DEFAULT_BATCH_SIZE=100
DEFAULT_MAX_ATTEMPTS=2
DEFAULT_DAILY_TARGET=400
```

### 4. Set Up n8n Workflows

See **[N8N_SETUP.md](N8N_SETUP.md)** for step-by-step instructions on modifying your n8n workflows.

### 5. Run

```bash
uv run python -m app.main
```

The app will be available at `http://your-server-ip:8000`

## Usage

### Daily Workflow

1. Manager sends you a Google Sheet link
2. Share the sheet with your service account email (Viewer access)
3. Open dashboard → **+ Import New Campaign**
4. Paste sheet URL, set campaign name, batch size, daily target
5. Click **Import** → contacts are loaded
6. Click **Start** → batches are sent to n8n automatically
7. Watch progress on the dashboard
8. App stops when daily target is reached or all contacts are processed

### Running Multiple Campaigns

- You can have up to **3 campaigns running simultaneously**
- Each campaign uses a separate n8n workflow instance (slot)
- Start/pause/stop each campaign independently

### Campaign Controls

- **Start**: Begin sending batches to n8n
- **Pause**: Stop sending new batches (current batch in n8n finishes). Resume any time.
- **Stop**: End the campaign. Resets pending contacts. Frees the n8n slot.

## Project Structure

```
campaign-manager/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Environment configuration
│   ├── db/
│   │   ├── schema.sql       # SQLite database schema
│   │   └── database.py      # All database operations
│   ├── routes/
│   │   ├── dashboard.py     # Dashboard + stats API
│   │   ├── campaigns.py     # Campaign CRUD + import
│   │   └── webhooks.py      # n8n result callbacks
│   ├── services/
│   │   ├── sheets.py        # Google Sheets reader
│   │   ├── batch_engine.py  # Auto-batching + retry orchestrator
│   │   └── n8n_trigger.py   # Sends batches to n8n
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # CSS + JS
├── data/                    # SQLite database (auto-created)
├── credentials/             # Google service account JSON (gitignored)
├── .env                     # Your configuration (gitignored)
├── .env.example             # Configuration template
├── N8N_SETUP.md             # n8n workflow modification guide
└── pyproject.toml           # Python dependencies
```

## API Endpoints

### Pages (HTML)
- `GET /` — Dashboard
- `GET /campaigns` — Campaign list
- `GET /campaigns/new` — Import form
- `GET /campaigns/:id` — Campaign detail

### API (JSON)
- `POST /campaigns/import` — Import from Google Sheet
- `POST /campaigns/:id/start` — Start campaign
- `POST /campaigns/:id/pause` — Pause campaign
- `POST /campaigns/:id/stop` — Stop campaign
- `DELETE /campaigns/:id` — Delete campaign
- `GET /api/stats/today` — Today's global stats (for polling)
- `GET /api/stats/campaign/:id` — Campaign stats (for polling)

### Webhooks (called by n8n)
- `POST /api/webhooks/n8n-result` — Individual contact result
- `POST /api/webhooks/n8n-batch-complete` — Batch completion signal

## Running with systemd (Production)

Create `/etc/systemd/system/campaign-manager.service`:

```ini
[Unit]
Description=Campaign Manager
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/campaign-manager
ExecStart=/path/to/campaign-manager/.venv/bin/python -m app.main
Restart=always
RestartSec=5
Environment=PATH=/path/to/campaign-manager/.venv/bin

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable campaign-manager
sudo systemctl start campaign-manager
```

## Troubleshooting

**"Google service account file not found"**
→ Make sure `credentials/service-account.json` exists. See step 2 above.

**"Could not auto-detect phone column"**
→ Your sheet's column headers don't match common patterns. Specify the phone column name explicitly when importing.

**"All n8n workflow slots are in use"**
→ You already have 3 campaigns running. Stop or pause one first.

**"n8n returned error"**
→ Check that your n8n webhook URLs in `.env` are correct and the n8n workflows are active.

**"No contacts found in the sheet"**
→ Make sure the sheet is shared with the service account email and has data rows below the header row.
