# PrintBot Thermal Printer Simulator - Setup Summary

You now have a complete thermal printer simulator for the **Epson TM-T88V** on your dev PC!

## What You Have

### 1. **printer_simulator.py** (Core Engine)
The heart of the simulator - interprets ESC/POS thermal printer commands.

**Use it for:**
- Testing receipt formatting before deployment
- Running unit tests
- Experimenting with ESC/POS commands

**Example:**
```bash
python printer_simulator.py
```

### 2. **dev_printer.py** (Interactive Server)
A mock printer server + client for testing complete print jobs.

**Use it for:**
- Interactive receipt composition  
- Testing integration with PrintBot
- Demo/showcase mode

**Modes:**
```bash
python dev_printer.py              # Interactive menu
python dev_printer.py --auto       # Auto demo with 3 samples
```

### 3. **test_receipts.py** (Test Suite)
Pre-built test cases for various receipt types.

**Use it for:**
- Quick sample generation
- Testing edge cases
- Reference receipt formatting

**Examples:**
```bash
python test_receipts.py            # Run all tests
python test_receipts.py --reminder # Show reminder receipt only
python test_receipts.py --list     # Show checklist receipt
python test_receipts.py --mixed    # Show mixed formatting
```

### 4. **PRINTER_SIMULATOR_README.md**
Comprehensive documentation (reference guide).

## Quick Start

### See Some Output Now
```bash
cd t:\Documents\code\printbot
python test_receipts.py --reminder
```

### Interactive Testing  
```bash
python dev_printer.py
# Follow menu prompts to create receipts
```

### Auto Demo
```bash
python dev_printer.py --auto
# Watch 3 sample receipts print automatically
```

## Specifications

| Property | Value |
|----------|-------|
| Printer Model | Epson TM-T88V |
| Paper Width | 42 characters |
| Character Set | ASCII + Extended (Code Page 437) |
| Commands Supported | ESC/POS (Initialization, Alignment, Bold, Sizing, Cutting) |
| Interface | Network Ethernet (Port 9100) |
| Output Format | Console display with frame |

## Key Features

✅ **ESC/POS Command Parsing** - Interprets real thermal printer protocol  
✅ **Text Formatting** - Bold, alignment (left/center/right), sizing  
✅ **Paper Cuts** - Visual separator showing where paper would cut  
✅ **42-Char Width** - Authentic thermal receipt width  
✅ **Frame Display** - Visual border showing actual print width  
✅ **Real-like Output** - Uses actual character codes and formatting  

## Supported ESC/POS Commands

```
ESC @          → Initialize/Reset printer
ESC E on/off   → Toggle bold (0x01=on, 0x00=off)
ESC a align    → Set alignment (0x00=left, 0x01=center, 0x02=right)
ESC ! size     → Set text size (0x00=normal, 0x11=double)
GS V A NUL     → Cut paper (displays as separator)
\n             → Line feed
```

## Example Workflow

### 1. Develop Receipt Format
Use `test_receipts.py` to see examples of different receipt types.

### 2. Modify Receipt Builder
Edit functions in `dev_printer.py` like `build_reminder_receipt()` to match your format.

### 3. Test Formatting
Run your modified code with the simulator to verify output before deployment.

### 4. Deploy to Real Printer
Once happy with simulation, point PrintBot to your real TM-T88V printer IP address.

## Integrating with PrintBot

### Option A: Point PrintBot to Simulator (Development)
```env
# In printbot/.env
PRINTER_HOST=127.0.0.1
PRINTER_PORT=9100
```

Then:
```bash
# Terminal 1: Start mock printer
python dev_printer.py

# Terminal 2: Start PrintBot (it will print to simulator)
python app/main.py
```

### Option B: Point PrintBot to Real Printer (Production)
```env
# In printbot/.env
PRINTER_HOST=192.168.1.50        # Real printer IP
PRINTER_PORT=9100
```

## Display Format Explanation

```
┌────────────────────────────────────────────┐  ← Frame showing width=42 chars
│                [REMINDER]                  │  ← [bold text] = bold indication
│             Feb 26 2026  14:00             │  ← Center aligned text
│ --------------------------------           │  ← Left aligned divider
│ [Your reminder message]                    │  ← Bold message
│ --------------------------------           │  ← Divider
│                             from SMS       │  ← Right aligned footer
│ ========================================== │  ← Paper cut line
│                                            │  ← Blank line after cut
└────────────────────────────────────────────┘
```

## Printer Characteristics (Real TM-T88V)

- **Print Width**: 203 DPI (80 dots per inch equiv.) → ~40-42 chars per line
- **Paper Sizes**: 58mm, 80mm (we simulate 42-char = nominal 80mm width)
- **Character Sets**: ASCII, OEM, Code Page 850, ISO/IEC 8859-1
- **Max Print Speed**: 300mm/sec (~20 lines/sec)
- **Cutting**: Full cut (what we simulate)
- **Interface**: Network (Ethernet) on port 9100
- **Temperature**: Thermal printing (no ink required)

## Troubleshooting

**Q: Why is text showing as `[text]` with brackets?**  
A: The brackets indicate bold formatting in the simulator. On real printer, bold appears darker.

**Q: Why is alignment off?**  
A: Alignment commands must come BEFORE the text. Example:
```python
commands += sim.ESC + b'a' + b'\x02'  # Right align FIRST
commands += b'Aligned text\n'         # Then text
```

**Q: Why do I see extra characters?**  
A: Usually means a cut command or formatting didn't parse correctly. Check byte sequences match exactly.

**Q: Can I use this on a real printer?**  
A: The simulator is display-only. For real printing, use the Printer class in `app/printer.py` instead.

## Advanced Usage

### Creating Custom Receipts
```python
from printer_simulator import PrinterSimulator

sim = PrinterSimulator(width=42)
commands = bytearray()

# Add commands here
commands += sim.ESC + b'@'              # Init
commands += sim.ESC + b'a' + b'\x01'    # Center
commands += b'MY RECEIPT\n'

sim.feed(bytes(commands))
print(sim.render_to_string())
```

### Getting Plain Output (No Frame)
```python
print(sim.render_to_plain())  # No borders, just content
```

### Testing Edge Cases
- Very long lines (will wrap on real printer)
- Unicode/special characters (test with different encodings)
- Rapid alignment changes (state is maintained)
- Empty lines and spacing

## Resources

- **ESC/POS Reference**: See links in PRINTER_SIMULATOR_README.md
- **Thermal Printer Info**: https://epson.com/Products/Printers/POS/TM-T88V
- **Code Page 437**: Box drawing and extended ASCII references

## Next Steps

1. ✅ Run: `python test_receipts.py` to see all example types
2. ✅ Try: `python dev_printer.py` for interactive testing
3. ✅ Modify: `dev_printer.py` functions to match your actual receipt format
4. ✅ Deploy: Change printer IP in PrintBot .env to real printer when ready

---

**Happy printing! 🖨️**

For detailed documentation, see: `PRINTER_SIMULATOR_README.md`
