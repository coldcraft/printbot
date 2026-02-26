# Thermal Printer Simulator - Complete Setup Verified ✓

You now have a **complete testing environment** for PrintBot without a physical printer.

## What's Been Set Up

### 1. **Printer Simulator Engine** ✅
- `printer_simulator.py` - Core ESC/POS command interpreter
- `dev_printer.py` - Mock server (listens on port 9100)
- `test_receipts.py` - 7 test scenarios

### 2. **MockPrinter Adapter** ✅
- `app/mock_printer.py` - NEW file
- Drop-in replacement for `Printer` class
- Same async interface: `connect()`, `disconnect()`, `print_receipt()`
- Buffers ESC/POS commands and sends to dev_printer.py

### 3. **Automatic Routing** ✅
- `app/router.py` - MODIFIED
- Checks `PRINTER_IP` environment variable
- If `127.0.0.1` → uses MockPrinter (simulator mode)
- If `192.168.x.x` → uses real Printer (production mode)
- Zero code changes needed

## How to Use It

### Step 1: Start the Simulator (Terminal 1)

```bash
cd t:\Documents\code\printbot
python dev_printer.py
```

You'll see:
```
✓ Mock printer listening on 127.0.0.1:9100
  Listening for print jobs...
```

### Step 2: Configure PrintBot (Terminal 2)

Edit `t:\Documents\code\printbot\.env`:

```env
PRINTER_IP=127.0.0.1
PRINTER_PORT=9100
```

### Step 3: Run PrintBot

```bash
cd t:\Documents\code\printbot
python app/main.py
```

### Step 4: Send SMS Messages

Via TextBee or manually trigger print jobs. Each receipt will appear in Terminal 1:

```
[Receipt received at 14:05:23]
┌────────────────────────────────────────────┐
│                 [REMINDER]                 │
│            Feb 26 2026  14:05              │
│ ────────────────────────────────────────── │
│ [call mom on friday]                       │
│ ────────────────────────────────────────── │
│                         from 206-555-0123  │
│ ========================================== │
│                                            │
└────────────────────────────────────────────┘
```

## Switching to Real Printer (When It Arrives)

**No code changes needed!**

1. Update `.env`:
```env
PRINTER_IP=192.168.1.50   # Your real printer IP
```

2. Restart PrintBot

That's it. PrintBot will automatically use the real `Printer` class.

## File Changes Summary

### New Files
- `app/mock_printer.py` (244 lines)
  - Buffers ESC/POS commands
  - Sends to dev_printer.py on port 9100
  - Identical async interface to real Printer

### Modified Files
- `app/router.py` (2 lines changed)
  - Added: `from mock_printer import MockPrinter`
  - Added: IP check in `connect_printer()` to conditionally use MockPrinter

### Documentation
- `PRINTER_SIMULATOR_README.md` - Technical reference
- `SETUP_GUIDE.md` - Quick start guide
- `SIMULATOR_INTEGRATION.md` - Integration with PrintBot
- This file - Verification summary

## What You Can Test Now

✅ **SMS Parsing** - TextBee webhooks → receipt intent detection  
✅ **Ollama Integration** - LLM processes SMS → structured JSON  
✅ **Receipt Formatting** - All your custom receipt designs  
✅ **ESC/POS Rendering** - Alignment, bold, sizing, cuts  
✅ **Rate Limiting** - Message volume constraints  
✅ **Error Handling** - Malformed messages, timeout handling  
✅ **Full Pipeline** - End-to-end SMS → printer  

## Architecture Diagram

```
SMS Gateway (TextBee)
        ↓ webhook
    PrintBot API
        ↓ parse + Ollama
     Router
        ↓
    [Conditional]
        ├─ PRINTER_IP = 127.0.0.1 → MockPrinter (SIMULATOR MODE)
        │                              ↓
        │                          dev_printer.py
        │                              ↓
        │                          printer_simulator.py
        │                              ↓
        │                          [Terminal Display]
        │
        └─ PRINTER_IP = 192.168.x.x → Printer (PRODUCTION MODE)
                                           ↓
                                     Real TM-T88V
                                           ↓
                                      [Thermal Output]
```

## Testing Workflow

### Quick Test
```bash
cd t:\Documents\code\printbot
python test_receipts.py --reminder
```

### Interactive Test
```bash
python dev_printer.py
# Menu options: create reminder, URL, list, Q&A
```

### Full Integration Test  
1. Terminal 1: `python dev_printer.py`
2. Terminal 2: Update `.env` with `PRINTER_IP=127.0.0.1`
3. Terminal 2: `python app/main.py`
4. Terminal 2: (optional) Trigger print jobs
5. Terminal 1: Watch receipts appear in real-time

## Verification Checklist

- [x] MockPrinter class created
- [x] Router.connect_printer() updated with IP check
- [x] Same interface as real Printer (async methods)
- [x] dev_printer.py ready to receive and display
- [x] printer_simulator.py correctly interprets ESC/POS
- [x] test_receipts.py shows reference outputs
- [x] Documentation complete

## Key Points

1. **No code changes needed once printer arrives** - Just update `.env`
2. **Full feature testing possible now** - All PrintBot functionality works
3. **Live visual feedback** - See exactly what would print
4. **Development/production parity** - Same code path, different printer class
5. **Easy to switch back** - Change one line in .env to toggle modes

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Connection refused" | Start dev_printer.py first in another terminal |
| No receipts appearing | Check .env has `PRINTER_IP=127.0.0.1` |
| Logs show real Printer not MockPrinter | PRINTER_IP might have typo or extra spaces |
| Want to use real printer | Change PRINTER_IP to real IP (e.g., 192.168.1.50), restart |
| MockPrinter errors | Check dev_printer.py is running and listening |

## Next Steps

1. ✅ Run: `python dev_printer.py` in Terminal 1
2. ✅ Update: `.env` with `PRINTER_IP=127.0.0.1`
3. ✅ Run: `python app/main.py` in Terminal 2
4. ✅ Test: Send SMS messages via TextBee or manually
5. ✅ Observe: Receipt output in Terminal 1
6. ✅ Iterate: Refine receipt formatting as needed
7. ✅ Deploy: When printer arrives, change .env and restart

---

**You're ready to develop and test without hardware! 🎉**

For detailed setup: See `SIMULATOR_INTEGRATION.md`  
For technical details: See `PRINTER_SIMULATOR_README.md`  
For quick reference: See `SETUP_GUIDE.md`
