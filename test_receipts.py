"""
PrintBot Test Receipt Generator
Quick script to generate and display sample receipts for testing

Usage:
    python test_receipts.py               # Show all samples
    python test_receipts.py --reminder    # Show specific type
    python test_receipts.py --url         # etc
    python test_receipts.py --list
"""

from printer_simulator import PrinterSimulator
from datetime import datetime, timedelta
import sys


def test_simple_text():
    """Test basic text and alignment"""
    print("\n" + "="*50)
    print("TEST: Simple Text and Alignment")
    print("="*50)
    
    sim = PrinterSimulator(width=42)
    commands = bytearray()
    
    commands += sim.ESC + b'@'
    commands += sim.ESC + b'a' + b'\x00'  # Left
    commands += b'LEFT ALIGNED\n'
    commands += sim.ESC + b'a' + b'\x01'  # Center
    commands += b'CENTER ALIGNED\n'
    commands += sim.ESC + b'a' + b'\x02'  # Right
    commands += b'RIGHT ALIGNED\n'
    commands += b'\n'
    commands += sim.GS + b'V' + b'A' + b'\x00'
    
    sim.feed(bytes(commands))
    print(sim.render_to_string())


def test_bold_formatting():
    """Test bold text"""
    print("\n" + "="*50)
    print("TEST: Bold Text Formatting")
    print("="*50)
    
    sim = PrinterSimulator(width=42)
    commands = bytearray()
    
    commands += sim.ESC + b'@'
    commands += b'Normal text\n'
    commands += sim.ESC + b'E' + b'\x01'  # Bold on
    commands += b'BOLD TEXT HERE\n'
    commands += sim.ESC + b'E' + b'\x00'  # Bold off
    commands += b'Normal text again\n'
    commands += b'\n'
    commands += sim.GS + b'V' + b'A' + b'\x00'
    
    sim.feed(bytes(commands))
    print(sim.render_to_string())


def test_receipt_reminder():
    """Test reminder receipt"""
    print("\n" + "="*50)
    print("TEST: Reminder Receipt")
    print("="*50)
    
    sim = PrinterSimulator(width=42)
    commands = bytearray()
    
    commands += sim.ESC + b'@'
    commands += sim.ESC + b'a' + b'\x01'  # Center
    commands += sim.ESC + b'E' + b'\x01'  # Bold
    commands += b'PRINTBOT\n'
    commands += sim.ESC + b'E' + b'\x00'
    
    dt = datetime.now() + timedelta(hours=2)
    commands += dt.strftime("%b %d %Y  %H:%M").encode() + b'\n'
    
    commands += sim.ESC + b'a' + b'\x00'  # Left
    commands += b'\n' + b'-' * 40 + b'\n'
    commands += sim.ESC + b'E' + b'\x01'
    commands += b'REMINDER\n'
    commands += sim.ESC + b'E' + b'\x00'
    
    commands += b'\nCall the dentist\n'
    commands += b'Thursday at 2pm\n'
    commands += b'\nBring insurance card\n'
    
    commands += b'\n' + b'-' * 40 + b'\n'
    commands += sim.ESC + b'a' + b'\x02'  # Right
    commands += b'From: 206-555-0123\n'
    commands += b'\n\n'
    commands += sim.GS + b'V' + b'A' + b'\x00'
    
    sim.feed(bytes(commands))
    print(sim.render_to_string())


def test_receipt_url():
    """Test URL summary receipt"""
    print("\n" + "="*50)
    print("TEST: URL Summary Receipt")
    print("="*50)
    
    sim = PrinterSimulator(width=42)
    commands = bytearray()
    
    commands += sim.ESC + b'@'
    commands += sim.ESC + b'a' + b'\x01'  # Center
    commands += sim.ESC + b'E' + b'\x01'  # Bold
    commands += b'PRINTBOT\n'
    commands += sim.ESC + b'E' + b'\x00'
    
    dt = datetime.now()
    commands += dt.strftime("%b %d %Y  %H:%M").encode() + b'\n'
    commands += b'-' * 40 + b'\n'
    
    commands += sim.ESC + b'E' + b'\x01'
    commands += b'URL SUMMARY\n'
    commands += sim.ESC + b'E' + b'\x00'
    
    url = "https://github.com/example"
    commands += url.encode() + b'\n\n'
    
    commands += b'A Python library for thermal\n'
    commands += b'receipt printing and formatting.\n'
    commands += b'Great for POS systems and IoT!\n'
    
    commands += b'\n' + b'-' * 40 + b'\n'
    commands += sim.ESC + b'a' + b'\x02'  # Right
    commands += b'sent via SMS\n'
    commands += b'\n\n'
    commands += sim.GS + b'V' + b'A' + b'\x00'
    
    sim.feed(bytes(commands))
    print(sim.render_to_string())


def test_receipt_list():
    """Test checklist receipt"""
    print("\n" + "="*50)
    print("TEST: Checklist Receipt")
    print("="*50)
    
    sim = PrinterSimulator(width=42)
    commands = bytearray()
    
    commands += sim.ESC + b'@'
    commands += sim.ESC + b'a' + b'\x01'  # Center
    commands += sim.ESC + b'E' + b'\x01'  # Bold
    commands += b'SHOPPING LIST\n'
    commands += sim.ESC + b'E' + b'\x00'
    
    dt = datetime.now()
    commands += dt.strftime("%b %d %Y").encode() + b'\n'
    commands += b'-' * 40 + b'\n\n'
    
    commands += sim.ESC + b'a' + b'\x00'  # Left
    items = ['Milk', 'Bread', 'Eggs', 'Butter', 'Coffee', 'Apples', 'Chicken breast']
    for item in items:
        commands += f'[ ] {item}\n'.encode()
    
    commands += b'\n' + b'-' * 40 + b'\n'
    commands += sim.ESC + b'a' + b'\x02'  # Right
    commands += b'from: Family\n'
    commands += b'\n\n'
    commands += sim.GS + b'V' + b'A' + b'\x00'
    
    sim.feed(bytes(commands))
    print(sim.render_to_string())


def test_receipt_long_text():
    """Test receipt with text wrapping"""
    print("\n" + "="*50)
    print("TEST: Long Text Receipt")
    print("="*50)
    
    sim = PrinterSimulator(width=42)
    commands = bytearray()
    
    commands += sim.ESC + b'@'
    commands += sim.ESC + b'a' + b'\x01'  # Center
    commands += sim.ESC + b'E' + b'\x01'  # Bold
    commands += b'NOTE\n'
    commands += sim.ESC + b'E' + b'\x00'
    
    dt = datetime.now()
    commands += dt.strftime("%H:%M").encode() + b'\n\n'
    
    commands += sim.ESC + b'a' + b'\x00'  # Left
    long_text = "This is a longer message that might wrap across multiple lines on the thermal printer. The TM-T88V handles this automatically."
    commands += long_text.encode() + b'\n'
    
    commands += b'\n' + b'-' * 40 + b'\n'
    commands += sim.ESC + b'a' + b'\x02'  # Right
    commands += b'End of note\n'
    commands += b'\n\n'
    commands += sim.GS + b'V' + b'A' + b'\x00'
    
    sim.feed(bytes(commands))
    print(sim.render_to_string())


def test_receipt_mixed():
    """Test receipt with mixed formatting"""
    print("\n" + "="*50)
    print("TEST: Mixed Formatting Receipt")
    print("="*50)
    
    sim = PrinterSimulator(width=42)
    commands = bytearray()
    
    commands += sim.ESC + b'@'
    
    # Header
    commands += sim.ESC + b'a' + b'\x01'  # Center
    commands += sim.ESC + b'E' + b'\x01'  # Bold
    commands += b'COFFEE SHOP\n'
    commands += sim.ESC + b'E' + b'\x00'
    commands += b'123 Main Street\n'
    commands += b'\n'
    
    # Items
    commands += sim.ESC + b'a' + b'\x00'  # Left
    commands += b'Medium Latte   ' + b'$4.50\n'
    commands += b'Croissant      ' + b'$3.25\n'
    commands += b'\n'
    
    # Total
    commands += sim.ESC + b'a' + b'\x02'  # Right
    commands += sim.ESC + b'E' + b'\x01'  # Bold
    commands += b'Total: $7.75\n'
    commands += sim.ESC + b'E' + b'\x00'
    
    commands += b'\n' + b'=' * 40 + b'\n'
    commands += sim.ESC + b'a' + b'\x01'  # Center
    commands += b'Thank you!\n'
    commands += b'Please visit again\n'
    commands += b'\n\n'
    commands += sim.GS + b'V' + b'A' + b'\x00'
    
    sim.feed(bytes(commands))
    print(sim.render_to_string())


def main():
    """Run selected tests"""
    
    all_tests = {
        'text': test_simple_text,
        'bold': test_bold_formatting,
        'reminder': test_receipt_reminder,
        'url': test_receipt_url,
        'list': test_receipt_list,
        'long': test_receipt_long_text,
        'mixed': test_receipt_mixed,
    }
    
    if len(sys.argv) > 1:
        test_name = sys.argv[1].lstrip('--')
        if test_name in all_tests:
            all_tests[test_name]()
        else:
            print(f"Unknown test: {test_name}")
            print(f"Available: {', '.join(all_tests.keys())}")
    else:
        print("\n" + "="*50)
        print("PRINTBOT TEST RECEIPT GENERATOR")
        print("="*50)
        for test_func in all_tests.values():
            test_func()
    
    print("\n" + "="*50)
    print("All tests completed!")
    print("="*50 + "\n")


if __name__ == "__main__":
    main()
