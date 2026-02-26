# PrintBot + Thermal Printer Simulator Integration

Complete setup to test PrintBot WITHOUT a physical printer, with live output visualization.

## Quick Setup (2 terminals)

### Terminal 1: Start the Mock Printer Server

```bash
cd t:\Documents\code\printbot
python dev_printer.py
```

Output:
```
============================================================
PRINTBOT DEV PRINTER - Thermal Printer Simulator
============================================================

✓ Mock printer listening on 127.0.0.1:9100
  Listening for print jobs...
```

The server is now waiting for print jobs.

### Terminal 2: Configure & Run PrintBot

Edit `.env`:
```env
PRINTER_IP=127.0.0.1
PRINTER_PORT=9100
```

Then run PrintBot:
```bash
cd t:\Documents\code\printbot
# Activate venv if needed
python -m venv .venv
.venv\Scripts\activate

# Start PrintBot
python app/main.py
```

## What Happens

1. ✅ PrintBot starts and connects to `127.0.0.1:9100`
2. ✅ RouterRouter automatically selects **MockPrinter** (not real Printer)
3. ✅ MockPrinter buffers all ESC/POS commands
4. ✅ When print job completes, buffer is sent to dev_printer.py on Terminal 1
5. ✅ Terminal 1 displays the receipt in real-time with printer simulation

## Testing Receipt Types

Send SMS messages to TextBee that trigger different receipt types:

### Reminder
```
reminder: call mom on friday
```
→ Displays reminder receipt

### URL Summary  
```
Research: https://github.com/example
A cool project for thermal printing
```
→ Displays URL summary receipt

### Shopping List
```
list: milk, bread, eggs, coffee
```
→ Displays checklist receipt

### General Message
```
Just a note about something important
```
→ Displays generic message receipt

## When Real Printer Arrives

**Zero code changes needed!** Just update `.env`:

```env
PRINTER_IP=192.168.1.50   # Your real printer IP
PRINTER_PORT=9100
```

That's it. PrintBot will automatically use the real `Printer` class instead of `MockPrinter`.

## Architecture

```
SMS Gateway (TextBee)
        ↓
    PrintBot
        ↓
   Router
        ↓
   [CONDITION]
        ├─→ IP = 127.0.0.1 → MockPrinter (dev)
        └─→ IP = 192.168.x.x → Printer (prod)
        ↓
   [Dev] dev_printer.py (Terminal 1)
        ↓
    printer_simulator.py
        ↓
    Display to console
```

## Live Output Example

You'll see receipts appear in Terminal 1 like this:

```
[Receipt received at 14:05:23]
┌────────────────────────────────────────────┐
│                  [REMINDER]                │
│             Feb 26 2026  14:05             │
│ --------------------------------           │
│ [call mom on friday]                       │
│ --------------------------------           │
│                          from 206-555-0123 │
│ ========================================== │
│                                            │
└────────────────────────────────────────────┘
```

## Code Changes Made

### `app/mock_printer.py` (NEW)
- Drop-in replacement for `Printer` class
- Same async interface: `connect()`, `disconnect()`, `print_receipt()`
- Buffers ESC/POS commands and sends to dev_printer.py on localhost:9100

### `app/router.py` (MODIFIED)
- Imports both `Printer` and `MockPrinter`
- In `connect_printer()`: checks if IP is `127.0.0.1` or `localhost`
- Conditionally instantiates `MockPrinter` vs real `Printer`
- No other changes needed

## Verification

Check logs to confirm simulator mode is active:

```
INFO: Using MockPrinter (simulator mode)
INFO: Printer connected: 127.0.0.1:9100
INFO: [MOCK] Printing receipt: reminder
INFO: [MOCK] Receipt sent to simulator (542 bytes)
```

## Troubleshooting

**Q: I don't see receipts in Terminal 1**
- Make sure `dev_printer.py` is running and listening
- Check PRINTER_IP in .env is exactly `127.0.0.1`
- Logs in Terminal 2 should say "Using MockPrinter"

**Q: Connection refused errors**
- Ensure Terminal 1 is running `python dev_printer.py` first
- dev_printer.py must be running before PrintBot starts

**Q: Real printer arrives - how to switch?**
- Change `PRINTER_IP` to real printer IP (e.g., `192.168.1.50`)
- No code changes - it's automatic!
- Restart PrintBot
- Logs will show "Printer connected: 192.168.1.50:9100" (no MockPrinter message)

## What You Can Do Now

✅ Test all PrintBot functionality without hardware  
✅ Debug receipt formatting  
✅ See real-time output exactly as printer would render it  
✅ Design receipt layout  
✅ Test different intent types (reminder, url, list, question)  
✅ Ensure Ollama integration works  
✅ Verify SMS parsing works  
✅ Integration test the entire pipeline  

## Files

- `app/mock_printer.py` - The simulator adapter (NEW)
- `app/router.py` - Updated with conditional logic  
- `dev_printer.py` - Server that displays output
- `printer_simulator.py` - Core ESC/POS renderer
- `.env` - Update PRINTER_IP to 127.0.0.1

---

**Ready to test without a printer! 🎉**
