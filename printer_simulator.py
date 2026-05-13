"""
PrintBot Thermal Receipt Printer Simulator
Simulates ESC/POS output for Epson TM-T88V printer on the dev PC
"""

import sys
from typing import List, Optional, Tuple
from datetime import datetime


class PrinterSimulator:
    """
    Simulates an Epson TM-T88V thermal receipt printer.
    
    Specs:
    - 42 or 80 character width (using 42 for standard thermal receipt)
    - ESC/POS command set
    - Thermal printing with optional cutting
    """
    
    # ESC/POS command codes
    ESC = b'\x1b'
    GS = b'\x1d'
    LF = b'\n'
    
    # Command definitions
    CMD_INIT = ESC + b'@'
    CMD_CUT = GS + b'V' + b'A' + b'\x00'
    CMD_BOLD_ON = ESC + b'E' + b'\x01'
    CMD_BOLD_OFF = ESC + b'E' + b'\x00'
    CMD_ALIGN_LEFT = ESC + b'a' + b'\x00'
    CMD_ALIGN_CENTER = ESC + b'a' + b'\x01'
    CMD_ALIGN_RIGHT = ESC + b'a' + b'\x02'
    CMD_SIZE_NORMAL = ESC + b'!' + b'\x00'
    CMD_SIZE_DOUBLE = ESC + b'!' + b'\x11'
    
    # ESC/POS codepage selector (ESC t N) → Python codec
    CODEPAGE_TABLE = {
        0: "cp437",
        2: "cp850",
        3: "cp860",
        4: "cp863",
        5: "cp865",
        16: "cp1252",
    }

    def __init__(self, width: int = 42, default_codepage: str = "cp437"):
        """Initialize simulator with paper width in characters"""
        self.width = width
        self.output: List[str] = []
        self.current_bytes = bytearray()
        self.alignment = "left"  # left, center, right
        self.bold = False
        self.size_multiplier = 1  # 1 = normal, 2+ = larger
        self.active = False
        self.codepage = default_codepage
        
    def feed(self, data: bytes) -> None:
        """Process incoming ESC/POS data stream"""
        i = 0
        n = len(data)
        self._pending_qr_data: Optional[str] = getattr(self, "_pending_qr_data", None)
        while i < n:
            b = data[i:i+1]
            if b == self.ESC and i + 1 < n:
                op = data[i+1:i+2]
                if op == b'@':  # Initialize
                    self._cmd_init()
                    i += 2
                elif op == b'E' and i + 2 < n:  # Bold
                    self.bold = data[i+2:i+3] == b'\x01'
                    i += 3
                elif op == b'a' and i + 2 < n:  # Align
                    code = data[i+2:i+3]
                    self.alignment = {b'\x00': "left", b'\x01': "center", b'\x02': "right"}.get(code, self.alignment)
                    i += 3
                elif op == b'!' and i + 2 < n:  # Size
                    self.size_multiplier = 2 if data[i+2:i+3] == b'\x11' else 1
                    i += 3
                elif op == b't' and i + 2 < n:  # Codepage select: ESC t N
                    cp_id = data[i+2]
                    self.codepage = self.CODEPAGE_TABLE.get(cp_id, self.codepage)
                    i += 3
                else:
                    # Unknown ESC command, skip ESC + op
                    i += 2
            elif b == self.GS and i + 1 < n:
                op = data[i+1:i+2]
                if op == b'V':  # Paper cut: GS V m [n]
                    # GS V A 0x00 (function A) is 4 bytes; older "GS V m" is 3.
                    if i + 2 < n and data[i+2:i+3] == b'A':
                        i += 4 if i + 3 < n else 3
                    else:
                        i += 3
                    self._cmd_cut()
                elif op == b'(' and i + 2 < n and data[i+2:i+3] == b'k':
                    # GS ( k pL pH cn fn [data...]  — used for QR codes
                    if i + 4 < n:
                        pL = data[i+3]
                        pH = data[i+4]
                        param_len = pL + (pH << 8)
                        block_end = i + 5 + param_len
                        if block_end <= n:
                            cn = data[i+5] if i + 5 < n else 0
                            fn = data[i+6] if i + 6 < n else 0
                            # QR "store symbol data" → fn = 0x50 ('P')
                            if cn == 49 and fn == 80 and i + 8 <= block_end:
                                qr_payload = bytes(data[i+8:block_end])
                                try:
                                    self._pending_qr_data = qr_payload.decode(self.codepage, errors="replace")
                                except Exception:
                                    self._pending_qr_data = qr_payload.decode("ascii", errors="replace")
                            # QR "print symbol data" → fn = 0x51 ('Q')
                            elif cn == 49 and fn == 81:
                                self._emit_qr_placeholder()
                            i = block_end
                        else:
                            i = n  # truncated; bail
                    else:
                        i = n
                elif op == b'v' and i + 2 < n and data[i+2:i+3] == b'0':
                    # GS v 0 m xL xH yL yH d1...dk  — raster bit image
                    if i + 7 < n:
                        xL, xH = data[i+4], data[i+5]
                        yL, yH = data[i+6], data[i+7]
                        x_bytes = xL + (xH << 8)
                        y = yL + (yH << 8)
                        payload = x_bytes * y
                        block_end = i + 8 + payload
                        if block_end <= n:
                            self._emit_photo_placeholder(x_bytes * 8, y)
                            i = block_end
                        else:
                            i = n
                    else:
                        i = n
                else:
                    # Unknown GS command — skip GS + op only
                    i += 2
            elif b == b'\n':  # Line feed
                self._flush_line()
                i += 1
            elif b == b'\r':  # Carriage return (ignore)
                i += 1
            else:
                self.current_bytes.append(data[i])
                i += 1
    
    def _cmd_init(self) -> None:
        """Initialize printer (clear buffer)"""
        self._flush_line()
        self.active = True
        self.alignment = "left"
        self.bold = False
        self.size_multiplier = 1

    def _cmd_cut(self) -> None:
        """Cut paper - add visual separator"""
        self._flush_line()
        self.output.append("=" * self.width)
        self.output.append("")

    def _decode_current(self) -> str:
        if not self.current_bytes:
            return ""
        try:
            return self.current_bytes.decode(self.codepage, errors="replace")
        except LookupError:
            return self.current_bytes.decode("cp437", errors="replace")

    def _flush_line(self) -> None:
        """Process and output current line"""
        text = self._decode_current()
        self.current_bytes = bytearray()
        if not text and not self.output:
            return
        if not text:
            self.output.append("")
            return

        line = self._apply_alignment(text)
        for _ in range(self.size_multiplier):
            self.output.append(line)

    def _apply_alignment(self, text: str) -> str:
        """Apply text alignment"""
        visible_len = len(text)
        if self.alignment == "center":
            padding = max(0, (self.width - visible_len) // 2)
            return " " * padding + text
        elif self.alignment == "right":
            padding = max(0, self.width - visible_len)
            return " " * padding + text
        else:  # left
            return text

    def _emit_qr_placeholder(self) -> None:
        self._flush_line()
        data = self._pending_qr_data or ""
        self._pending_qr_data = None
        label = "[QR CODE]"
        if data:
            shown = data if len(data) <= self.width - 2 else data[:self.width - 5] + "..."
            self.output.append(self._apply_alignment(label))
            self.output.append(self._apply_alignment(shown))
        else:
            self.output.append(self._apply_alignment(label))

    def _emit_photo_placeholder(self, width_dots: int, height_dots: int) -> None:
        self._flush_line()
        self.output.append(self._apply_alignment(f"[PHOTO {width_dots}x{height_dots}]"))
    
    # Candidate monospace fonts with cp437/box-drawing coverage.
    IMAGE_FONT_CANDIDATES = (
        "consola.ttf",       # Windows: Consolas
        "consolab.ttf",      # Windows: Consolas Bold
        "DejaVuSansMono.ttf",
        "Menlo.ttc",
        "Courier New.ttf",
        "cour.ttf",
    )

    def render_to_image(
        self,
        font_size: int = 18,
        margin: int = 24,
        line_spacing: int = 4,
        paper_color=(252, 250, 244),
        ink_color=(28, 28, 30),
        font_path: Optional[str] = None,
    ):
        """Render the captured receipt to a PIL Image that resembles a thermal print.

        Requires Pillow. Box-drawing characters (the brand banner) come out
        cleanest with a Unicode-aware monospace font — Consolas on Windows,
        DejaVu Sans Mono elsewhere — and one of those is picked automatically
        unless ``font_path`` is provided explicitly.
        """
        from PIL import Image, ImageDraw, ImageFont

        self._flush_line()

        font = None
        if font_path:
            font = ImageFont.truetype(font_path, font_size)
        else:
            for candidate in self.IMAGE_FONT_CANDIDATES:
                try:
                    font = ImageFont.truetype(candidate, font_size)
                    break
                except (OSError, IOError):
                    continue
        if font is None:
            font = ImageFont.load_default()

        # Measure the natural cell width for the receipt's max line width.
        sample = "M" * self.width
        bbox = font.getbbox(sample)
        content_width = bbox[2] - bbox[0]

        ascent, descent = font.getmetrics()
        line_height = ascent + descent + line_spacing

        img_width = content_width + 2 * margin
        img_height = max(1, len(self.output)) * line_height + 2 * margin

        img = Image.new("RGB", (img_width, img_height), paper_color)
        draw = ImageDraw.Draw(img)

        y = margin
        for line in self.output:
            if line:
                draw.text((margin, y), line, font=font, fill=ink_color)
            y += line_height

        return img

    def render_to_string(self) -> str:
        """Return formatted printer output as string"""
        self._flush_line()  # Flush any remaining content
        
        output_text = "\n".join(self.output)
        
        # Create a nice display frame
        header = "┌" + "─" * (self.width + 2) + "┐"
        footer = "└" + "─" * (self.width + 2) + "┘"
        
        framed_output = header + "\n"
        for line in self.output:
            framed_output += "│ " + line.ljust(self.width) + " │\n"
        framed_output += footer
        
        return framed_output
    
    def render_to_plain(self) -> str:
        """Return plain printer output without frame"""
        self._flush_line()  # Flush any remaining content
        return "\n".join(self.output)


class ESCPOSParser:
    """Parse and execute ESC/POS command stream"""
    
    def __init__(self, simulator: PrinterSimulator):
        self.simulator = simulator
    
    def execute(self, data: bytes) -> None:
        """Parse and execute ESC/POS data"""
        self.simulator.feed(data)


# Example usage and test functions
def test_printer_simulation():
    """Test the printer simulator with various ESC/POS commands"""
    
    simulator = PrinterSimulator(width=42)
    
    # Simulate a reminder receipt
    commands = bytearray()
    
    # Initialize
    commands += simulator.ESC + b'@'
    
    # Align center and bold header
    commands += simulator.ESC + b'a' + b'\x01'  # Center
    commands += simulator.ESC + b'E' + b'\x01'  # Bold on
    commands += b'PRINTBOT\n'
    commands += simulator.ESC + b'E' + b'\x00'  # Bold off
    
    # Timestamp
    timestamp = datetime.now().strftime("%b %d %Y  %H:%M")
    commands += timestamp.encode() + b'\n'
    
    # Left align and divider
    commands += simulator.ESC + b'a' + b'\x00'  # Left
    commands += b'\n'
    commands += b'-' * 32 + b'\n'
    
    # Content
    commands += simulator.ESC + b'E' + b'\x01'  # Bold on
    commands += b'Your reminder message\n'
    commands += b'arrives here on the\n'
    commands += b'thermal printer!\n'
    commands += simulator.ESC + b'E' + b'\x00'  # Bold off
    
    # Footer
    commands += b'\n'
    commands += b'-' * 32 + b'\n'
    commands += simulator.ESC + b'a' + b'\x02'  # Right align
    commands += b'from SMS\n'
    
    # Cut
    commands += b'\n\n'
    commands += simulator.GS + b'V' + b'A' + b'\x00'
    
    # Process commands
    simulator.feed(bytes(commands))
    
    return simulator


def test_with_sample_json():
    """Test with sample JSON job"""
    import json
    from datetime import datetime
    
    simulator = PrinterSimulator(width=42)
    
    # Sample job from printbot
    job = {
        "intent_type": "reminder",
        "content": "Call mom on Friday",
        "sender": "2055551234",
        "received_at": datetime.now().isoformat()
    }
    
    # Build ESC/POS commands
    commands = bytearray()
    commands += simulator.ESC + b'@'
    commands += simulator.ESC + b'a' + b'\x01'
    commands += simulator.ESC + b'E' + b'\x01'
    commands += b'REMINDER\n'
    commands += simulator.ESC + b'E' + b'\x00'
    
    dt = datetime.fromisoformat(job["received_at"])
    commands += dt.strftime("%b %d %Y  %H:%M").encode() + b'\n'
    
    commands += simulator.ESC + b'a' + b'\x00'
    commands += b'\n' + b'-' * 32 + b'\n\n'
    commands += simulator.ESC + b'E' + b'\x01'
    commands += job["content"].encode() + b'\n'
    commands += simulator.ESC + b'E' + b'\x00'
    commands += b'\n' + b'-' * 32 + b'\n'
    commands += simulator.ESC + b'a' + b'\x02'
    commands += f"from {job['sender']}\n".encode()
    commands += b'\n\n'
    commands += simulator.GS + b'V' + b'A' + b'\x00'
    
    simulator.feed(bytes(commands))
    return simulator


if __name__ == "__main__":
    print("\n" + "="*50)
    print("EPSON TM-T88V THERMAL PRINTER SIMULATOR")
    print("="*50 + "\n")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--sample":
        print("Test 1: Sample JSON Job\n")
        sim = test_with_sample_json()
    else:
        print("Test 1: Basic Receipt\n")
        sim = test_printer_simulation()
    
    print(sim.render_to_string())
    print("\n" + "="*50)
    print("SIMULATION COMPLETE")
    print("="*50 + "\n")
