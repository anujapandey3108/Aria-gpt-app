# Test Drive Booking — GPT App + MCP Server

One backend, two ways in:
- `app/` — FastAPI REST API + OpenAPI schema → used by a **Custom GPT's Actions** (what gets listed in the GPT Store)
- `mcp_server/` — MCP server exposing the same logic as tools → used by Claude, Claude Desktop, or any MCP-compatible host

Both call the same `app/booking_logic.py`, so behavior never drifts between the two.

## 1. Deploy the REST API publicly

GPT Actions require a **public HTTPS endpoint** with a valid cert (no self-signed, no localhost).

Quickest paths:
- **Render.com**: connect this repo, set build command `pip install -r requirements.txt`, start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, set env var `GPT_ACTION_API_KEY`.
- **Fly.io**: `fly launch` (it will detect the Dockerfile), `fly secrets set GPT_ACTION_API_KEY=...`, `fly deploy`.
- **Google Cloud Run**: `gcloud run deploy testdrive-api --source . --set-env-vars GPT_ACTION_API_KEY=...`
- **Azure App Service** (natural fit given your Salesforce/enterprise stack): deploy the container, set the app setting for the API key.

After deploying, update `servers[0].url` in `app/main.py` to your real domain, and redeploy.

Verify:
```
curl -H "Authorization: Bearer YOUR_KEY" https://your-domain.example.com/vehicles
```

## 2. Get the OpenAPI schema

Once live:
```
curl https://your-domain.example.com/openapi.json
```
Save this — you'll paste it into the GPT Builder.

## 3. Build the Custom GPT (this is what gets listed publicly)

1. Go to chatgpt.com → "Explore GPTs" → "Create" (requires ChatGPT Plus/Team/Enterprise).
2. In the GPT Builder, go to **Configure** tab.
3. Fill in Name, Description, Instructions (e.g. "You help customers browse vehicle models and book test drives. Always confirm the customer's name, email, phone, model, dealer, and preferred time before calling createBooking.").
4. Under **Actions**, click **Create new action**.
5. Paste your OpenAPI schema (or "Import from URL" → `https://your-domain.example.com/openapi.json`).
6. Set **Authentication** → API Key → Auth Type: `Bearer`, and paste your `GPT_ACTION_API_KEY` value. This is what your `verify_key` dependency checks against.
7. Test each action in the builder's action test panel (list vehicles, create a booking, etc.) — you did this exact validation above, just repeat via the UI.
8. Under **Privacy Policy URL**, add a real URL (required for public listing — even a simple hosted page is enough).
9. Click **Save** → choose **Publish to: Everyone** (or "Anyone with a link" if you want a soft launch first).
10. Once published publicly, OpenAI can surface it in the **GPT Store** — this can take review time and may require domain verification for the Action's server if you want the "verified" badge.

## 4. (Optional) Run the MCP server for Claude / other MCP hosts

Local/stdio (Claude Desktop, Claude Code):
```bash
pip install -r requirements.txt
python mcp_server/server.py
```
Add to Claude Desktop's `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "testdrive-booking": {
      "command": "python",
      "args": ["/absolute/path/to/mcp_server/server.py"]
    }
  }
}
```

Remote/HTTP (for hosted MCP, e.g. exposing to Claude.ai custom connectors):
```bash
python mcp_server/server.py --http --port 8001
```
Then register `https://your-domain.example.com:8001/sse` as a connector.

## 5. Production hardening checklist
- [ ] Swap the in-memory `BOOKINGS`/`CATALOG` dicts for a real DB or your Salesforce org (given your FSC background, an Apex REST endpoint behind this FastAPI layer is a natural fit)
- [ ] Rate limiting on `/bookings` POST
- [ ] Real auth (rotate the bearer key, or move to OAuth if you want per-user identity)
- [ ] Input validation on phone numbers / booking windows per dealer's actual business hours
- [ ] Logging + monitoring (Cloud Run/Fly/Render all have basic built-in log viewers)
- [ ] CORS config if any web frontend also calls this API directly
