"""
PrintBot Thermal Receipt Printer Simulator
Simulates ESC/POS output for Epson TM-T88V printer on the dev PC
"""

import sys
from typing import List, Tuple
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
    
    # Character sets
    CODE_PAGE_CP437 = 0  # Code Page 437
    CODE_PAGE_CP437_ALT = 16
    CODE_PAGE_CP850 = 2   # OEM multilingual
    CODE_PAGE_UTF8 = 255
    
    def __init__(self, width: int = 42):
        """Initialize simulator with paper width in characters"""
        self.width = width
        self.output: List[str] = []
        self.current_line = ""
        self.alignment = "left"  # left, center, right
        self.bold = False
        self.size_multiplier = 1  # 1 = normal, 2+ = larger
        self.active = False
        
    def feed(self, data: bytes) -> None:
        """Process incoming ESC/POS data stream"""
        i = 0
        while i < len(data):
            # Check for ESC/POS commands
            if data[i:i+1] == self.ESC:
                if i + 1 < len(data):
                    if data[i+1:i+2] == b'@':  # Initialize
                        self._cmd_init()
                        i += 2
                    elif data[i+1:i+2] == b'E':  # Bold
                        if i + 2 < len(data):
                            self.bold = data[i+2:i+3] == b'\x01'
                            i += 3
                        else:
                            i += 2
                    elif data[i+1:i+2] == b'a':  # Align
                        if i + 2 < len(data):
                            align_code = data[i+2:i+3]
                            if align_code == b'\x00':
                                self.alignment = "left"
                            elif align_code == b'\x01':
                                self.alignment = "center"
                            elif align_code == b'\x02':
                                self.alignment = "right"
                            i += 3
                        else:
                            i += 2
                    elif data[i+1:i+2] == b'!':  # Size
                        if i + 2 < len(data):
                            size_code = data[i+2:i+3]
                            if size_code == b'\x00':
                                self.size_multiplier = 1
                            elif size_code == b'\x11':  # Double height/width
                                self.size_multiplier = 2
                            i += 3
                        else:
                            i += 2
                    else:
                        # Unknown ESC command, skip it
                        i += 2
                else:
                    i += 1
            elif data[i:i+1] == self.GS and i + 1 < len(data):
                if data[i+1:i+2] == b'V':  # Cut
                    if i + 3 < len(data):
                        self._cmd_cut()
                        i += 4
                    else:
                        i += 2
                else:
                    i += 2
            elif data[i:i+1] == b'\n':  # Line feed
                self._flush_line()
                i += 1
            elif data[i:i+1] == b'\r':  # Carriage return (ignore)
                i += 1
            else:
                # Regular character
                try:
                    char = chr(data[i])
                    self.current_line += char
                except:
                    pass
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
    
    def _flush_line(self) -> None:
        """Process and output current line"""
        if not self.current_line and not self.output:
            return
            
        # Handle size multiplier via line duplication
        lines_to_add = []
        if self.current_line:
            line = self.current_line
            
            # Apply text formatting
            if self.bold:
                line = f"[{line}]"  # Indicate bold with brackets in simulation
            
            # Apply alignment
            line = self._apply_alignment(line)
            
            # Add line multiple times if size > 1
            for _ in range(self.size_multiplier):
                lines_to_add.append(line)
            
            self.current_line = ""
        
        self.output.extend(lines_to_add)
    
    def _apply_alignment(self, text: str) -> str:
        """Apply text alignment"""
        # Strip to visible content width (accounting for formatting)
        visible_len = len(text.replace("[", "").replace("]", ""))
        
        if self.alignment == "center":
            padding = max(0, (self.width - visible_len) // 2)
            return " " * padding + text
        elif self.alignment == "right":
            padding = max(0, self.width - visible_len)
            return " " * padding + text
        else:  # left
            return text
    
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
