# Wrenfield Motors: Test Drive Booking Platform

A booking platform for the Wrenfield SUV and Wrenfield Sedan, with three ways in that all share the same booking logic:

- `website/` : the public dealership site customers browse and book from directly
- `app/` : FastAPI REST API, powering both the website and a Custom GPT's Actions
- `mcp_server/` : an MCP server exposing the same booking tools to ChatGPT Apps and Claude Connectors

All three call the same `app/booking_logic.py`, so a booking made through the website, a Custom GPT, or an AI assistant behaves identically and lands in the same store.

## Architecture

```
Customer or agent
   |
   |-- Website (website/index.html) -----> REST API /public/* routes (no auth)
   |-- Custom GPT Actions ---------------> REST API, Bearer-authenticated routes
   |-- ChatGPT Apps / Claude Connectors -> MCP server (mcp_server/server.py)
                                              |
                                              v
                                    app/booking_logic.py
                                    (shared booking logic and catalog)
```

## 1. Deploy the REST API

This needs a public HTTPS endpoint with a valid certificate.

Render.com:
- Connect this repository
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment variable: `GPT_ACTION_API_KEY` (a secret string used to authenticate Custom GPT Actions calls)

After deploying, update `servers[0].url` in `app/main.py` to the real domain and redeploy.

Verify:
```bash
curl https://your-domain.example.com/health
curl https://your-domain.example.com/public/vehicles
```

## 2. Deploy the MCP server

This is a separate service from the REST API, since it runs a different process and protocol.

Render.com, second web service, same repository:
- Build command: `pip install -r requirements.txt`
- Start command: `python mcp_server/server.py`
- Environment variable: `PUBLIC_HOSTNAME` set to the exact hostname of this service (for example `aria-mcp.onrender.com`), required so the built-in DNS rebinding protection allows public traffic

Verify:
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://your-mcp-domain.example.com/mcp
```
A `406` response is correct here. It confirms the server is live and enforcing the MCP protocol handshake.

## 3. Deploy the website

`website/index.html` is a static file with no build step. Any static host works, including GitHub Pages.

Before deploying, set `API_BASE` near the bottom of `index.html` to the REST API URL from step 1, and update the URLs inside the JSON-LD block and `llms.txt` to match.

Also deploy alongside it: `robots.txt`, `sitemap.xml`, and `llms.txt`, all at the site root.

## 4. Connect a Custom GPT

1. chatgpt.com, Explore GPTs, Create, Configure tab
2. Under Actions, Create new action, Import from URL using `https://your-domain.example.com/openapi.json`
3. Set Authentication to API Key, Bearer, using the `GPT_ACTION_API_KEY` value
4. Add a Privacy Policy URL
5. Save and publish

## 5. Connect ChatGPT Apps or Claude Connectors

Point either platform at the MCP server's `/mcp` endpoint from step 2. Both platforms will discover `list_vehicles`, `check_availability`, `create_booking`, `get_booking`, and `cancel_booking` automatically, along with their descriptions and safety annotations.

`model_id` and `dealer_id` accept natural language (for example "Wrenfield Sedan" and "Melbourne CBD"), so neither platform needs to know the internal catalog identifiers.

## Local development

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000       # REST API
python mcp_server/server.py --stdio             # MCP server, local stdio mode
```

## Production checklist

- [ ] Replace the in-memory `BOOKINGS` and `CATALOG` dictionaries in `booking_logic.py` with a real database or CRM integration
- [ ] Move from a shared Bearer key to per-user OAuth if per-customer identity is needed
- [ ] Tighten CORS on the REST API from `allow_origins=["*"]` to the website's real domain
- [ ] Add monitoring and alerting on both Render services
- [ ] Confirm booking windows and rate limits match actual dealer operating hours and capacity