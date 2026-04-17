# Campaign Manager

Marketing campaign manager with auto-batching, retry logic, and n8n integration. Eliminates manual batch creation, sheet copying, and filter-and-retry workflows.

## What It Does

- **Import** contacts from CSV or Excel files (drag & drop upload)
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

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# Required - your n8n webhook URLs
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

### 3. Set Up n8n Workflows

See **[N8N_SETUP.md](N8N_SETUP.md)** for step-by-step instructions on modifying your n8n workflows.

### 4. Run

```bash
uv run python -m app.main
```

The app will be available at `http://your-server-ip:8000`

## Usage

### Daily Workflow

1. Manager gives you a Google Sheet / Excel file with phone numbers
2. Download it as CSV or XLSX (File > Download > .csv or .xlsx)
3. Open dashboard -> **+ New Campaign**
4. Give it a name, drag & drop the file, set batch size and daily target
5. Click **Import** -> contacts are loaded
6. Click **Start** -> batches are sent to n8n automatically
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
│   │   ├── campaigns.py     # Campaign CRUD + file upload import
│   │   └── webhooks.py      # n8n result callbacks
│   ├── services/
│   │   ├── file_parser.py   # CSV/XLSX file parser
│   │   ├── batch_engine.py  # Auto-batching + retry orchestrator
│   │   └── n8n_trigger.py   # Sends batches to n8n
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # CSS + JS
├── data/                    # SQLite database (auto-created)
├── .env                     # Your configuration (gitignored)
├── .env.example             # Configuration template
├── N8N_SETUP.md             # n8n workflow modification guide
└── pyproject.toml           # Python dependencies
```

## API Endpoints

### Pages (HTML)
- `GET /` — Dashboard
- `GET /campaigns` — Campaign list
- `GET /campaigns/new` — Import form (file upload)
- `GET /campaigns/:id` — Campaign detail

### API (JSON)
- `POST /campaigns/import` — Import from uploaded CSV/XLSX
- `POST /campaigns/preview` — Preview uploaded file
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

**"Unsupported file format"**
→ The app supports `.csv` and `.xlsx` files. Download your Google Sheet as one of these formats.

**"Could not auto-detect phone column"**
→ Your file's column headers don't match common patterns (phone, mobile, number, etc.). Specify the phone column name explicitly when importing.

**"All n8n workflow slots are in use"**
→ You already have 3 campaigns running. Stop or pause one first.

**"n8n returned error"**
→ Check that your n8n webhook URLs in `.env` are correct and the n8n workflows are active.

**"No contacts found in the file"**
→ Make sure the file has data rows below the header row and contains valid phone numbers.
