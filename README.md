# SuperOwl Voice AI — Quick Start

> Pre-configured with VAPI account, assistants, tools, and business data. Only ngrok setup needed.

---

## 1. Install

```bash
# Install uv (package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync
```

## 2. Create `.env`

```bash
cp .env.example .env
```

Open `.env` — **only change this one line**:

```
VAPI_WEBHOOK_URL=https://YOUR-NGROK-URL.ngrok-free.dev/vapi-webhook
```

Everything else (VAPI keys, Groq, assistants, phone numbers) is already configured.

## 3. Start ngrok

```bash
ngrok http 8000
```

Copy the forwarding URL (e.g. `https://abc123.ngrok-free.dev`) and paste it into `VAPI_WEBHOOK_URL` in `.env`.

## 4. Run server

```bash
uv run uvicorn main:app --reload --port 8000
```

## 5. Seed demo data (one-time)

```bash
curl -X POST http://localhost:8000/playground/seed
```

Returns: `{"status": "seeded", "business_id": "8ea5a5e8-...", "dashboard_url": "..."}`

## 6. Open dashboard

```
http://localhost:8000/?business_id=8ea5a5e8-cce5-41dd-ad75-55f474d499f3
```

**That's the only link  needed.** This loads the configuration dashboard where you can:
- Edit business settings (name, phone, fallback)
- Configure outbound/inbound welcome messages
- Connect Slack workspace (via Nango OAuth)
- Edit shared system prompt and voice settings
- Use the Playground tab to test chat and trigger calls

---

## What's Pre-Configured (No Setup Needed)

| Component | Status |
|-----------|--------|
| VAPI API key | ✅ Your account |
| VAPI assistants (inbound, outbound, owner) | ✅ Pre-created |
| VAPI phone number | ✅ Pre-configured |
| VAPI tools (transfer, notify) | ✅ Pre-created |
| Groq API (summarization) | ✅ Configured |
| ElevenLabs voice (Priya) | ✅ Configured |
| Vobiz SIP (Indian transfers) | ✅ Configured |
| Demo business data | ✅ Seeded |
| Prompt templates | ✅ Pre-loaded |

## What Changes Every Restart

| Component | Action |
|-----------|--------|
| ngrok URL | Update `VAPI_WEBHOOK_URL` in `.env` |
| Nango webhook (for Slack) | Update Nango dashboard with new ngrok URL + `/onboarding/webhook/nango` |

---

## Troubleshooting

**"Business not found" on Slack connect button?**
→ Enter the exact phone: `+919611896916`

**VAPI webhook not firing?**
→ Make sure `VAPI_WEBHOOK_URL` matches your current ngrok URL exactly

**Slack OAuth not completing?**
→ Check Nango dashboard — webhook URL must be your ngrok URL + `/onboarding/webhook/nango`

**Server won't start?**
→ Run `uv sync` to ensure all dependencies are installed
