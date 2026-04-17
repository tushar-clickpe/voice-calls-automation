-- Campaign Manager Database Schema

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sheet_url TEXT,
    total_contacts INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'paused', 'stopped', 'completed')),
    batch_size INTEGER DEFAULT 100,
    max_attempts INTEGER DEFAULT 2,
    daily_target INTEGER DEFAULT 400,
    n8n_slot INTEGER DEFAULT NULL,  -- which n8n webhook slot (1, 2, or 3) is assigned
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    phone TEXT NOT NULL,
    name TEXT DEFAULT '',
    extra_data TEXT DEFAULT '{}',  -- JSON string for any extra columns from sheet
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'queued', 'in_progress', 'connected', 'no_answer', 'failed', 'do_not_call')),
    attempt_count INTEGER DEFAULT 0,
    last_attempt_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    batch_number INTEGER NOT NULL,
    size INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'sent', 'running', 'completed', 'failed')),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    connected_count INTEGER DEFAULT 0,
    no_answer_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS call_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL,
    batch_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,
    call_status TEXT,      -- connected, no_answer, failed, busy, etc.
    whatsapp_status TEXT,  -- sent, delivered, read, failed, etc.
    smartflo_response TEXT DEFAULT '{}',  -- raw JSON from smartflo
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,  -- YYYY-MM-DD
    campaign_id INTEGER,
    target INTEGER DEFAULT 400,
    attempted INTEGER DEFAULT 0,
    connected INTEGER DEFAULT 0,
    no_answer INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_contacts_campaign_status ON contacts(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_contacts_status_attempts ON contacts(status, attempt_count);
CREATE INDEX IF NOT EXISTS idx_batches_campaign_status ON batches(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON daily_stats(date);
CREATE INDEX IF NOT EXISTS idx_call_logs_contact ON call_logs(contact_id);
CREATE INDEX IF NOT EXISTS idx_contacts_phone_campaign ON contacts(phone, campaign_id);
