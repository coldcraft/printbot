# PrintBot

PrintBot is a FastAPI service that prints incoming SMS or Telegram messages as formatted thermal receipts. A local Ollama model classifies each message first. The service speaks ESC/POS to an Epson TM-T88V over the network. It ships with a full software simulator, so you can build and demo without real hardware.

## What it looks like

The simulator drives the real ESC/POS pipeline in [app/printer.py](app/printer.py). It renders the byte stream as a PNG that resembles thermal paper. The previews below come from the actual print code, not hand-drawn mockups.

<table>
  <tr>
    <td align="center"><b>Reminder</b><br><img src="docs/receipts/reminder.png" alt="Reminder receipt" width="260"></td>
    <td align="center"><b>Checklist</b><br><img src="docs/receipts/list.png" alt="Checklist receipt" width="260"></td>
    <td align="center"><b>URL summary</b><br><img src="docs/receipts/url.png" alt="URL summary receipt" width="260"></td>
  </tr>
  <tr>
    <td align="center"><b>Question</b><br><img src="docs/receipts/question.png" alt="Question receipt" width="260"></td>
    <td align="center"><b>Generic</b><br><img src="docs/receipts/generic.png" alt="Generic receipt" width="260"></td>
    <td></td>
  </tr>
</table>

Regenerate locally:

```bash
python test_receipts.py --images                # all samples -> docs/receipts/*.png
python test_receipts.py --reminder              # text-art for one intent
PYTHONIOENCODING=utf-8 python test_receipts.py  # on Windows for box-drawing glyphs
```

For a live preview while the service runs, set `PRINTER_IP=127.0.0.1` and start `python dev_printer.py` in another terminal.

## The pitch

Yes, this is software whose job is to print SMS messages on a thermal receipt printer. Here is the workflow it is built for:

1. **Buy a cheap receipt printer.** A used Epson TM-T88V on eBay is about $25 to $40. Give it a good cleaning. There is a real chance the previous owner had it strapped under a counter at a juice bar. Expect a gunky print head. Five minutes with isopropyl and a microfiber cloth makes it like new.
2. **Buy a burner Android phone.** Anything that boots and can hold a SIM. Insert a prepaid SIM and install [SMS Gateway by capcom6](https://sms-gate.app/). The phone becomes a webhook for incoming SMS. Park it on the same Wi-Fi as your host and forget it exists.
3. **Tunnel the webhook.** Run [cloudflared](https://github.com/cloudflare/cloudflared) on the host with a free `*.trycloudflare.com` tunnel that points at port 8000. Use a Named Tunnel on your own domain if you want it durable. Paste that URL into the SMS Gateway webhook field. The burner can now reach PrintBot from anywhere a cell tower can reach the burner.
4. **Text the burner.**
   - Your todos for the day print as a checklist with empty boxes. Tick them by hand. Crumple when done.
   - Send a question you do not need an immediate answer to (*"who was the first US senator from Hawaii?"*). Ollama answers on paper a few seconds later. No phone in hand, no rabbit hole, no eight more tabs.
   - A link to read later prints as a short summary and a scannable QR code. A physical internet bookmark, in 2026.
   - Anything else mirrors back verbatim. The printer becomes a quiet inbox that does not notify, beep, or track you.
5. **Use the receipts as kindling.** Complete the loop. Burn the brnr.

It is a deliberately friction-laden, deliberately physical inbox for the parts of phone use you do not like. Worst case, you own a $30 receipt printer that occasionally prints groceries. Not the worst outcome.

## How it works

```
  SMS / Telegram  ─▶  FastAPI webhook  ─▶  Router  ─▶  Ollama (intent JSON)
                                              │
                                              ├─▶  Question context fetch (optional)
                                              ├─▶  Disk-backed job queue
                                              └─▶  ESC/POS printer  (or simulator)
```

The router classifies every message into one of five intents: `reminder`, `url`, `list`, `question`, or `generic`. The system prompt in [prompts/system.txt](prompts/system.txt) defines them. The prompt is conservative. Anything that is not an explicit instruction falls through to `generic`, and the printer mirrors it back verbatim. The printer does not invent tasks.

## Features

- **Multiple inbound sources**: SMS Gateway by capcom6 (local Android device, with HMAC signing), TextBee webhook, and a Telegram bridge. The bridge can preview and approve prints before they fire.
- **Ollama intent parsing**: runs locally with no cloud API. Choose any model that returns clean JSON (`mistral` is the default).
- **Question grounding**: for `question` intents the router can fetch a small page snippet first. The model then has real context, not just training data.
- **ESC/POS output**: Epson TM-T88V compatible. Codepage and timezone are configurable.
- **Software simulator**: `dev_printer.py` listens on port 9100 and renders receipts in your terminal exactly as they print.
- **Disk-backed job queue**: retry, dedup, and rate limiting (per-sender, sliding window with cooldown).
- **Outbound replies**: the Telegram bridge can answer the sender by SMS via TextBee or SMS Gateway.
- **Docker and bare-metal** dev workflows.

## Quick start

1. Virtualenv + deps
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Config
   ```powershell
   copy .env.example .env
   ```
   Leave `TELEGRAM_*`, `TEXTBEE_*`, and `SMSGATE_*` blank to disable any source you do not use.
3. Start the simulator (terminal 1)
   ```powershell
   python dev_printer.py
   ```
4. Start PrintBot (terminal 2)
   ```powershell
   python app/main.py
   ```
5. Smoke test
   ```powershell
   curl http://localhost:8000/health
   curl -X POST http://localhost:8000/test/print -H "Content-Type: application/json" -d "{\"message\":\"remind me to call mom at 3pm\"}"
   ```

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/webhook/sms-gate` | Inbound from SMS Gateway by capcom6 (HMAC-verified when you set `SMSGATE_SIGNING_KEY`) |
| `POST` | `/webhook/textbee` | Inbound from TextBee (key-verified when you set `TEXTBEE_WEBHOOK_KEY`) |
| `POST` | `/test/print` | Classify and print a message by hand |
| `POST` | `/test/photo` | Print a test photo / image fixture |
| `GET`  | `/queue/status` | Snapshot of pending/retry jobs |
| `POST` | `/queue/retry` | Force-retry queued jobs |
| `GET`  | `/health` | Liveness |

## Environment variables

The full list with defaults is in [.env.example](.env.example). These are the ones you change most often:

- `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_KEEP_ALIVE`
- `PRINTER_IP`, `PRINTER_PORT`, `PRINTER_CODEPAGE`, `PRINTER_TIMEZONE`
- `RATE_LIMIT_MESSAGES`, `RATE_LIMIT_WINDOW_MINUTES`, `RATE_LIMIT_COOLDOWN_MINUTES`
- `MAX_MESSAGE_CHARS`
- `QUESTION_CONTEXT_ENABLED`, `QUESTION_CONTEXT_TIMEOUT_SECONDS`, `QUESTION_CONTEXT_MAX_CHARS`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `TEXTBEE_API_KEY`, `TEXTBEE_DEVICE_ID`, `TEXTBEE_WEBHOOK_KEY`
- `SMSGATE_BASE_URL`, `SMSGATE_USERNAME`, `SMSGATE_PASSWORD`, `SMSGATE_SIGNING_KEY`
- `CONTACTS_PATH`: optional JSON map from E.164 number to friendly label (see [contacts.sample.json](contacts.sample.json))

Do not commit secrets. The `.gitignore` file excludes `.env`, `config/`, and `.claude/`.

## Docker

```bash
docker compose up --build
```

Exposes port 8000 and reads env from your `.env`.

## Project layout

```
app/
  main.py            FastAPI app + webhook routes
  router.py          Intent classification, Ollama client, dispatch
  printer.py         ESC/POS encoder for real hardware
  mock_printer.py    ESC/POS encoder used when PRINTER_IP=127.0.0.1
  job_queue.py       Disk-backed queue with retry
  fetcher.py         URL fetch + question-context scrape
  question_context.py
  photo_fixtures.py
  telegram_bridge.py Long-poll Telegram bot for review-before-print
  smsgate_outbound.py / textbee_outbound.py   Outbound SMS clients
  logger.py
dev_printer.py       Simulator server + interactive composer
printer_simulator.py ESC/POS interpreter (used by the simulator)
test_receipts.py     Generates the sample receipts shown above
prompts/system.txt   Ollama system prompt: intents and guardrails
```

## Notes

- For real hardware, set `PRINTER_IP` to the IP of the printer and restart. For local testing, set `PRINTER_IP=127.0.0.1` and run `dev_printer.py` alongside the app.
- The `question` intent uses the general knowledge of the model by default. Set `QUESTION_CONTEXT_ENABLED=true` to make the router do a quick web fetch first for grounding. This is slower but more accurate.
- The prompt explicitly resists reminder-creep ("I like waffles" is `generic`, not a reminder). If you tune the prompt, keep that guardrail.
