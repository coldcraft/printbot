# PrintBot Printer Simulator

A development tool for simulating Epson TM-T88V thermal receipt printer output on your dev PC. Test receipt formatting, alignment, and ESC/POS commands without a physical printer.

## Files

- **`printer_simulator.py`** - Core printer simulator that interprets ESC/POS commands and formats output
- **`dev_printer.py`** - Interactive server and client for testing complete print jobs
- **`README_SIMULATOR.md` (this file)** - Usage documentation

## Features

✓ ESC/POS command interpretation (real thermal printer protocol)  
✓ Text alignment (left, center, right)  
✓ Text formatting (bold on/off)  
✓ Font sizing (normal, double)  
✓ Paper cuts  
✓ Authentic 42-character thermal receipt paper simulation  
✓ Visual frame around output for clarity  

## Quick Start

### Option 1: Simple Simulation Test

```bash
cd t:\Documents\code\printbot
python printer_simulator.py
```

This runs a demo that shows how the simulator handles formatting.

**Output:**
```
==================================================
EPSON TM-T88V THERMAL PRINTER SIMULATOR
==================================================

Test 1: Basic Receipt

┌────────────────────────────────────────────┐
│                  [PRINTBOT]                │
│             Feb 26 2026  14:00             │
│ --------------------------------           │
│ [Your reminder message]                    │
│ [arrives here on the]                      │
│ [thermal printer!]                         │
│ --------------------------------           │
│                                   from SMS │
│ ========================================== │
│                                            │
└────────────────────────────────────────────┘

==================================================
SIMULATION COMPLETE
==================================================
```

### Option 2: Interactive Receipt Composer

```bash
python dev_printer.py
```

Menu options:
- Create reminders, URLs, checklists
- View real-time rendering in the mock printer
- Send custom ESC/POS hex commands

### Option 3: Auto Demo

```bash
python dev_printer.py --auto
```

Sends three sample receipts through the mock server automatically:
1. Reminder receipt
2. URL summary receipt  
3. Checklist receipt

## ESC/POS Command Support

The simulator supports these ESC/POS commands:

| Command | Description |
|---------|-------------|
| `ESC @ ` | Initialize printer (reset formatting) |
| `ESC E on/off` | Bold text on/off |
| `ESC a 0/1/2` | Alignment: 0=left, 1=center, 2=right |
| `ESC ! size` | Text size: 0x00=normal, 0x11=double |
| `GS V A NUL` | Cut paper (shows as separator line) |
| `\n` | Line feed / newline |

## How It Works

### Command Flow

```
Raw ESC/POS bytes
       ↓
PrinterSimulator.feed(data)
       ↓
Parse commands & build text lines
       ↓
Apply formatting (alignment, bold, size)
       ↓
Output formatted text
       ↓
render_to_string()  →  Display with frame
render_to_plain()   →  Display without frame
```

### Display Format

- **`[text]`** = Bold text (wrapped in brackets for visibility)
- **Spacing** = Center/right align achieved via leading spaces
- **`====`** = Paper cut marker
- **Frame** = Visual border showing 42-character width

## Example: Creating a Receipt

Here's how to create a reminder receipt using the simulator:

```python
from printer_simulator import PrinterSimulator
from datetime import datetime

sim = PrinterSimulator(width=42)

commands = bytearray()

# Initialize  
commands += sim.ESC + b'@'

# Centered bold header
commands += sim.ESC + b'a' + b'\x01'  # Center
commands += sim.ESC + b'E' + b'\x01'  # Bold on
commands += b'REMINDER\n'
commands += sim.ESC + b'E' + b'\x00'  # Bold off

# Timestamp
dt = datetime.now()
commands += dt.strftime("%b %d %Y  %H:%M").encode() + b'\n'

# Left-aligned content
commands += sim.ESC + b'a' + b'\x00'  # Left align
commands += b'\n-------------------------------------------\n\n'
commands += b'Call mom on Friday\n'
commands += b'\n-------------------------------------------\n'

# Right-aligned footer
commands += sim.ESC + b'a' + b'\x02'  # Right align
commands += b'from SMS\n'

# Cut paper
commands += b'\n\n'
commands += sim.GS + b'V' + b'A' + b'\x00'

# Process and display
sim.feed(bytes(commands))
print(sim.render_to_string())
```

## Character Set

The TM-T88V supports:
- **ASCII (0x00-0x7F)** - Standard letters, numbers, symbols
- **Code Page 437** - Extended ASCII with box drawing characters
- **Unicode** - Via UTF-8 encoding (emulated in simulator)

Characters used in receipts:
- `─` = Horizontal line (box drawing)
- `│` = Vertical line (frame)
- `├`, `┤`, `┌`, `└`, etc. = Corner/junction characters
- `☐` or `[ ]` = Checkbox for lists
- `★` = Star/decoration

## Printer Specifications (Simulated)

```
Printer Model:        Epson TM-T88V
Paper Width:          42 characters (standard thermal receipt)
Default Resolution:   203 DPI
Print Speed:          300mm/sec
Cut Types:           Full cut (simulated)
Interface:           Network Ethernet (port 9100)
Character Encoding:  ASCII, UTF-8
```

## Integration with PrintBot

The simulator integrates with the main PrintBot application:

1. **For development**: Run `dev_printer.py` to capture what your real printer would produce
2. **For testing**: Use `printer_simulator.py` to test receipt formatting before deployment
3. **For debugging**: Inspect the `output` list in PrinterSimulator to see what gets rendered

### Connecting the Dev Printer

The dev printer server listens on `http://127.0.0.1:9100` (same port as real thermal printers).

If you modify your PrintBot configuration to use `127.0.0.1` instead of the real printer IP, you can test locally:

```env
# .env
PRINTER_HOST=127.0.0.1
PRINTER_PORT=9100
```

Then run:
```bash
python dev_printer.py  # Start the mock printer server
# In another terminal:
python app/main.py     # Start PrintBot normally
```

All print jobs will now display in the simulator instead of going to the physical printer.

## Troubleshooting

**Issue: Characters appear garbled**
- Ensure text is UTF-8 encoded before sending
- Use `.encode()` on Python strings

**Issue: Cut command not recognized**
- Must send exactly: `\x1d` `V` `A` `\x00` (4 bytes)
- Check byte order and length

**Issue: Alignment not working**
- Alignment commands must come BEFORE the text
- Set alignment with `ESC a [code]` then print text

**Issue: Print failed errors in dev_printer.py**
- These are expected if server and client don't connect immediately
- The receipts still print to console even if connection fails
- This won't affect actual PrintBot usage with a real printer

## Next Steps

1. **Modify receipts**: Edit `build_reminder_receipt()` etc. in `dev_printer.py`
2. **Test edge cases**: Try very long text, special characters, unusual alignment
3. **Deploy to printer**: Once satisfied with simulator output, point PrintBot to real printer IP
4. **Refine timing**: Adjust `asyncio.sleep()` in demo_mode for slower/faster feedback

## Resources

- ESC/POS Reference: https://files.support.epson.com/htmldocs/escp_ref/
- Thermal Printer Basics: TM-T88V manual available from Epson Support
- Character Sets: Code Page 437, Code Page 850 documentation

## License

Part of PrintBot project
