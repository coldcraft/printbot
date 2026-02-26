# PrintBot

PrintBot is a FastAPI service that receives SMS webhooks, routes messages through Ollama for intent parsing, and prints formatted receipts to a thermal printer. It includes a full local simulator so you can develop and test without hardware.

## Features

- SMS webhook ingestion (TextBee)
- Ollama-powered intent parsing and formatting
- Receipt printing via ESC/POS (Epson TM-T88V compatible)
- Local printer simulator and mock server
- Disk-backed job queue with retry
- Docker and local dev workflows

## Quick Start (Local)

1. Create a virtual environment and install deps
	```bash
	python -m venv .venv
	.venv\Scripts\activate
	pip install -r requirements.txt
	```

2. Create a `.env`
	```bash
	copy .env.example .env
	```

3. Run the mock printer (Terminal 1)
	```bash
	python dev_printer.py
	```

4. Start PrintBot (Terminal 2)
	```bash
	python app/main.py
	```

5. Health check
	```bash
	curl http://localhost:8000/health
	```

## Printer Simulator

The simulator listens on port 9100 and renders receipts in the console.

```bash
python dev_printer.py          # interactive
python dev_printer.py --auto   # demo samples
```

The router automatically switches to the mock printer when `PRINTER_IP=127.0.0.1`.

## Environment Variables

Common settings (see `.env.example`):

- `TEXTBEE_WEBHOOK_KEY` - optional verification key
- `OLLAMA_HOST` - Ollama endpoint (default: http://host.docker.internal:11434)
- `OLLAMA_MODEL` - model name (default: mistral)
- `PRINTER_IP` - printer or simulator IP
- `PRINTER_PORT` - printer port (default: 9100)
- `RATE_LIMIT_MESSAGES`, `RATE_LIMIT_WINDOW_MINUTES`, `RATE_LIMIT_COOLDOWN_MINUTES`
- `MAX_MESSAGE_CHARS`

Do not commit secrets. `.env` is already ignored by `.gitignore`.

## API Endpoints

- `POST /webhook/textbee` - TextBee SMS webhook
- `POST /test/print` - manual test printing
- `GET /queue/status` - queue summary
- `POST /queue/retry` - retry queued jobs
- `GET /health` - health check

## Docker

```bash
docker compose up --build
```

The container exposes port 8000 and passes env vars from your `.env`.

## Project Layout

- `app/` - FastAPI app, router, printers, queue
- `dev_printer.py` - mock printer server + demo
- `printer_simulator.py` - ESC/POS interpreter
- `test_receipts.py` - sample receipts
- `prompts/` - Ollama prompts
- `logs/` - log output

## Notes

- For real hardware, set `PRINTER_IP` to your printer and restart.
- For local testing, use `PRINTER_IP=127.0.0.1` and run `dev_printer.py`.

## License

Add your license here.