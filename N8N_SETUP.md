# n8n Workflow Modification Guide

This guide explains how to modify your existing n8n marketing workflow to work with the Campaign Manager app.

## Overview of Changes

**Before**: Manual trigger → Read Google Sheet → Loop → Process → Update Sheet
**After**: Webhook trigger → Receive batch from app → Loop → Process → POST results back to app

Your existing call logic (WhatsApp Plivo, Smartflo HTTP Request, Postgres logging, If conditions, Wait nodes) stays **exactly the same**. You only change the input and output.

---

## Step 1: Duplicate Your Workflow

Since you'll run up to 3 campaigns in parallel, duplicate your workflow 3 times:
- `Marketing Campaign - Slot 1`
- `Marketing Campaign - Slot 2`
- `Marketing Campaign - Slot 3`

For each copy, follow steps 2-5 below.

---

## Step 2: Replace the Trigger

### Remove
- "When clicking 'Execute workflow'" (manual trigger)
- "Get row(s) in sheet" (Google Sheets read node)

### Add: Webhook Trigger
1. Add a **Webhook** node as the new trigger
2. Configure it:
   - **HTTP Method**: POST
   - **Path**: `campaign-slot-1` (or `campaign-slot-2`, `campaign-slot-3` for duplicates)
   - **Response Mode**: "Respond to Webhook" (respond immediately)
3. The webhook URL will look like: `https://your-n8n.com/webhook/campaign-slot-1`
4. **Copy this URL** — you'll put it in the Campaign Manager's `.env` file

### What the webhook receives
The Campaign Manager sends this JSON payload:
```json
{
  "batch_id": 5,
  "campaign_id": 1,
  "callback_url": "http://your-server:8000/api/webhooks/n8n-result",
  "contacts": [
    {
      "id": 123,
      "phone": "+919876543210",
      "name": "John Doe",
      "extra_data": "{\"city\": \"Mumbai\"}",
      "attempt_number": 1
    },
    ...
  ]
}
```

---

## Step 3: Update the Loop

### Current Loop
Your "Loop Over Items" currently loops over rows from Google Sheets.

### New Loop
Connect the **Webhook** node to a **Code** node that extracts the contacts array:

**Code Node** (place between Webhook and Loop):
```javascript
// Extract contacts from webhook payload
const webhookData = $input.first().json;
const contacts = webhookData.contacts;
const batchId = webhookData.batch_id;
const campaignId = webhookData.campaign_id;
const callbackUrl = webhookData.callback_url;

// Return contacts as individual items for the loop
return contacts.map(contact => ({
  json: {
    ...contact,
    batch_id: batchId,
    campaign_id: campaignId,
    callback_url: callbackUrl,
  }
}));
```

Then connect this Code node → **Loop Over Items** (same as before).

---

## Step 4: Update References Inside the Loop

Inside your loop, wherever you reference the phone number or name from the Google Sheet row, update it to use the new field names:

| Old reference (Sheet) | New reference (Webhook) |
|---|---|
| `{{ $json.Phone }}` or `{{ $json.phone }}` | `{{ $json.phone }}` |
| `{{ $json.Name }}` or `{{ $json.name }}` | `{{ $json.name }}` |
| `{{ $json["Customer Name"] }}` | `{{ $json.name }}` |

The phone and name fields are standardized by the Campaign Manager, so the field names will always be `phone` and `name`.

You also have access to:
- `{{ $json.id }}` — contact ID (needed for the callback)
- `{{ $json.attempt_number }}` — which attempt this is (1 or 2)
- `{{ $json.batch_id }}` — batch ID
- `{{ $json.campaign_id }}` — campaign ID
- `{{ $json.callback_url }}` — where to POST results
- `{{ $json.extra_data }}` — JSON string with any extra columns from the original sheet

---

## Step 5: Add Result Callback

This is the most important change. After your call/WhatsApp logic completes for each contact, you need to POST the result back to the Campaign Manager.

### Add an HTTP Request Node at the End

After your existing If/If1/If2 conditions and Update Sheet nodes (you can remove the Update Sheet nodes since we're not using sheets anymore), add:

**HTTP Request Node** — "Report Result":
- **Method**: POST
- **URL**: `{{ $json.callback_url }}`
- **Body Content Type**: JSON
- **JSON Body**:

```json
{
  "batch_id": {{ $json.batch_id }},
  "campaign_id": {{ $json.campaign_id }},
  "contact_id": {{ $json.id }},
  "phone": "{{ $json.phone }}",
  "call_status": "{{ your_call_result_variable }}",
  "whatsapp_status": "{{ your_wa_result_variable }}",
  "smartflo_response": {{ $json.smartflo_raw_response || '{}' }}
}
```

**Setting `call_status`**: Map your existing If/If1/If2 conditions to these values:
- If the call was answered/connected → `"connected"`
- If the call was not answered → `"no_answer"`
- If the call failed/errored → `"failed"`

The Campaign Manager accepts these values (case-insensitive): `connected`, `answered`, `picked_up`, `success`, `no_answer`, `unanswered`, `busy`, `failed`, `error`

### Multiple Exit Points

If your If/If1/If2 nodes have different exit paths:

**For the "Success" path** (call was answered):
```json
{ "call_status": "connected" }
```

**For the "No Answer/Busy" path**:
```json
{ "call_status": "no_answer" }
```

**For the "Error" path**:
```json
{ "call_status": "failed" }
```

You can add a separate HTTP Request node for each exit path, or use a **Set** node before a single HTTP Request to set the status value based on the path.

---

## Step 6: Remove Google Sheets Update Nodes

Your current workflow has "Update row in sheet" and "Update row in sheet1" nodes. **Remove these** — the Campaign Manager handles all status tracking now. Those were the nodes that updated the Google Sheet with call results, which we no longer need.

Keep your:
- Wait nodes (for pacing between calls)
- Postgres: Insert WA Log (for your WhatsApp logging)
- All call/WhatsApp logic

---

## Step 7: Optional — Batch Complete Signal

Optionally, add one more HTTP Request at the very end (after the Loop's "Done" output):

**HTTP Request** — "Batch Complete":
- **Method**: POST
- **URL**: `http://your-server:8000/api/webhooks/n8n-batch-complete`
- **JSON Body**:
```json
{
  "batch_id": {{ $('Webhook').first().json.batch_id }},
  "campaign_id": {{ $('Webhook').first().json.campaign_id }}
}
```

This explicitly tells the Campaign Manager the batch is done. It's optional because the app auto-detects completion, but it's a good safety net.

---

## Final Workflow Structure

```
[Webhook Trigger]
       │
       ▼
[Code: Extract Contacts]
       │
       ▼
[Loop Over Items]───Done──→ [HTTP: Batch Complete (optional)]
       │
       └──Loop──→ [WhatsApp Plivo]
                  [HTTP: Smartflo Call]
                  [Postgres: Insert WA Log]
                       │
                       ▼
                  [HTTP Request - Smartflo]
                  ├── Success → [If1] → [HTTP: Report Result (connected)]
                  └── Error   → [If2] → [HTTP: Report Result (failed/no_answer)]
                                            │
                                            ▼
                                         [Wait]
```

---

## Step 8: Update .env in Campaign Manager

After setting up the webhooks, update your `.env` file:

```
N8N_WEBHOOK_URL_1=https://your-n8n.com/webhook/campaign-slot-1
N8N_WEBHOOK_URL_2=https://your-n8n.com/webhook/campaign-slot-2
N8N_WEBHOOK_URL_3=https://your-n8n.com/webhook/campaign-slot-3

CALLBACK_BASE_URL=http://your-campaign-manager-ip:8000
```

Make sure:
- Your n8n can reach the Campaign Manager's IP/port (for posting results back)
- Your Campaign Manager can reach n8n's webhook URLs

---

## Testing

1. Start the Campaign Manager app
2. Import a small test sheet (5-10 contacts)
3. Set batch_size to 5
4. Start the campaign
5. Watch n8n — it should receive the webhook with 5 contacts
6. After n8n processes them, check the Campaign Manager dashboard — results should appear
7. If everything works, increase batch_size to 100 and use it for real
