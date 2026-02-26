"""
PrintBot Development Printer - Live Simulation
Captures ESC/POS commands and displays them in a formatted receipt

Usage:
    python dev_printer.py              # Start interactive mode
    python dev_printer.py --auto       # Demo mode with sample recipes
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import asyncio
import socket
from threading import Thread
import time


class MockPrinterServer:
    """
    Mock Epson TM-T88V printer that listens on port 9100
    and displays ESC/POS data in a readable format
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 9100):
        self.host = host
        self.port = port
        self.running = False
        self.receipts = []
        
    def start(self):
        """Start the mock printer server"""
        self.running = True
        self.server_thread = Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        print(f"✓ Mock printer listening on {self.host}:{self.port}")
        
    def _run_server(self):
        """Run the TCP server"""
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self.host, self.port))
            server_socket.listen(5)
            print(f"  Listening for print jobs...\n")
            
            while self.running:
                try:
                    client_socket, addr = server_socket.accept()
                    self._handle_client(client_socket, addr)
                except:
                    if not self.running:
                        break
                    continue
                    
        except Exception as e:
            print(f"✗ Server error: {e}")
        finally:
            try:
                server_socket.close()
            except:
                pass
    
    def _handle_client(self, client_socket, addr):
        """Handle incoming print job"""
        try:
            data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                data += chunk
            
            if data:
                self._display_receipt(data)
                client_socket.send(b"OK")
                
        except Exception as e:
            print(f"Error processing print job: {e}")
        finally:
            client_socket.close()
    
    def _display_receipt(self, data: bytes):
        """Parse and display ESC/POS data as receipt"""
        from printer_simulator import PrinterSimulator
        
        simulator = PrinterSimulator(width=42)
        simulator.feed(data)
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n[Receipt received at {timestamp}]")
        print(simulator.render_to_string())
        print()


class DevPrinter:
    """
    Development printer client - simulates sending jobs to the mock printer
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 9100):
        self.host = host
        self.port = port
        
    async def connect_and_print(self, data: bytes) -> bool:
        """Connect to mock printer and send data"""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=5
            )
            writer.write(data)
            await writer.drain()
            await asyncio.wait_for(reader.read(1024), timeout=2)
            writer.close()
            await writer.wait_closed()
            return True
        except Exception as e:
            print(f"✗ Print failed: {e}")
            return False


def build_reminder_receipt(content: str, sender: str = "SMS") -> bytes:
    """Build a reminder receipt (ESC/POS bytes)"""
    from printer_simulator import PrinterSimulator
    
    sim = PrinterSimulator()
    
    commands = bytearray()
    commands += sim.ESC + b'@'  # Init
    commands += sim.ESC + b'a' + b'\x01'  # Center
    commands += sim.ESC + b'E' + b'\x01'  # Bold
    commands += b'REMINDER\n'
    commands += sim.ESC + b'E' + b'\x00'  # Bold off
    
    dt = datetime.now()
    commands += dt.strftime("%b %d %Y  %H:%M").encode() + b'\n'
    
    commands += sim.ESC + b'a' + b'\x00'  # Left align
    commands += b'\n' + b'-' * 32 + b'\n\n'
    commands += sim.ESC + b'E' + b'\x01'  # Bold
    commands += content.encode() + b'\n'
    commands += sim.ESC + b'E' + b'\x00'  # Bold off
    
    commands += b'\n' + b'-' * 32 + b'\n'
    commands += sim.ESC + b'a' + b'\x02'  # Right align
    commands += f"from {sender}\n".encode()
    commands += b'\n\n'
    commands += sim.GS + b'V' + b'A' + b'\x00'  # Cut
    
    return bytes(commands)


def build_url_receipt(url: str, summary: str, sender: str = "SMS") -> bytes:
    """Build a URL summary receipt"""
    from printer_simulator import PrinterSimulator
    
    sim = PrinterSimulator()
    
    commands = bytearray()
    commands += sim.ESC + b'@'  # Init
    commands += sim.ESC + b'a' + b'\x01'  # Center
    commands += sim.ESC + b'E' + b'\x01'  # Bold
    commands += b'PRINTBOT\n'
    commands += sim.ESC + b'E' + b'\x00'  # Bold off
    
    dt = datetime.now()
    commands += dt.strftime("%b %d %Y  %H:%M").encode() + b'\n'
    commands += b'-' * 32 + b'\n'
    
    commands += sim.ESC + b'E' + b'\x01'  # Bold
    commands += b'URL SUMMARY\n'
    commands += sim.ESC + b'E' + b'\x00'  # Bold off
    
    url_short = url[:36] + "..." if len(url) > 36 else url
    commands += url_short.encode() + b'\n\n'
    
    commands += summary.encode() + b'\n\n'
    commands += b'-' * 32 + b'\n'
    
    commands += sim.ESC + b'a' + b'\x02'  # Right align
    commands += "sent via SMS - printbot v0.1\n".encode()
    commands += b'\n\n'
    commands += sim.GS + b'V' + b'A' + b'\x00'  # Cut
    
    return bytes(commands)


def build_list_receipt(items: list, sender: str = "SMS") -> bytes:
    """Build a checklist receipt"""
    from printer_simulator import PrinterSimulator
    
    sim = PrinterSimulator()
    
    commands = bytearray()
    commands += sim.ESC + b'@'  # Init
    commands += sim.ESC + b'a' + b'\x01'  # Center
    commands += sim.ESC + b'E' + b'\x01'  # Bold
    commands += b'CHECKLIST\n'
    commands += sim.ESC + b'E' + b'\x00'  # Bold off
    
    dt = datetime.now()
    commands += dt.strftime("%b %d %Y  %H:%M").encode() + b'\n'
    commands += b'-' * 32 + b'\n\n'
    
    commands += sim.ESC + b'a' + b'\x00'  # Left align
    for item in items:
        if item.strip():
            commands += f"[ ] {item}\n".encode()
    
    commands += b'\n' + b'-' * 32 + b'\n'
    commands += sim.ESC + b'a' + b'\x02'  # Right align
    commands += f"from {sender}\n".encode()
    commands += b'\n\n'
    commands += sim.GS + b'V' + b'A' + b'\x00'  # Cut
    
    return bytes(commands)


async def demo_mode(printer_client: DevPrinter):
    """Run demo with sample receipts"""
    
    samples = [
        ("reminder", build_reminder_receipt("Call mom on Friday", "555-01234")),
        ("url", build_url_receipt(
            "https://github.com/example/repo",
            "A cool new Python library\nfor thermal printing",
            "555-0001"
        )),
        ("checklist", build_list_receipt([
            "Milk",
            "Bread", 
            "Eggs",
            "Coffee"
        ], "555-0002")),
    ]
    
    for name, data in samples:
        print(f"Sending {name} receipt...\n")
        await printer_client.connect_and_print(data)
        await asyncio.sleep(2)


async def interactive_mode():
    """Interactive mode - let user compose receipts"""
    printer_client = DevPrinter()
    
    print("\n--- PrintBot Receipt Composer ---\n")
    
    while True:
        print("\nOptions:")
        print("  1. Reminder")
        print("  2. URL Summary")
        print("  3. Checklist")
        print("  4. Raw ESC/POS")
        print("  5. Exit")
        
        choice = input("\nChoice: ").strip()
        
        if choice == "1":
            content = input("Reminder content: ").strip()
            sender = input("Sender (default: SMS): ").strip() or "SMS"
            data = build_reminder_receipt(content, sender)
            await printer_client.connect_and_print(data)
            
        elif choice == "2":
            url = input("URL: ").strip()
            summary = input("Summary: ").strip()
            sender = input("Sender (default: SMS): ").strip() or "SMS"
            data = build_url_receipt(url, summary, sender)
            await printer_client.connect_and_print(data)
            
        elif choice == "3":
            items = []
            print("Enter items (empty line to finish):")
            while True:
                item = input(f"  Item {len(items)+1}: ").strip()
                if not item:
                    break
                items.append(item)
            sender = input("Sender (default: SMS): ").strip() or "SMS"
            data = build_list_receipt(items, sender)
            await printer_client.connect_and_print(data)
            
        elif choice == "4":
            hex_input = input("ESC/POS hex string: ").strip()
            try:
                data = bytes.fromhex(hex_input)
                await printer_client.connect_and_print(data)
            except ValueError:
                print("Invalid hex string")
                
        elif choice == "5":
            break
        else:
            print("Invalid choice")


async def main():
    """Main entry point"""
    from printer_simulator import PrinterSimulator
    
    # Start mock server
    server = MockPrinterServer()
    server.start()
    
    # Give server time to start
    await asyncio.sleep(1)
    
    printer_client = DevPrinter()
    
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--auto":
            print("Running demo mode...\n")
            await demo_mode(printer_client)
        else:
            await interactive_mode()
    except KeyboardInterrupt:
        print("\n\nShutdown...")
    finally:
        server.running = False


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("PRINTBOT DEV PRINTER - Thermal Printer Simulator")
    print("=" * 60)
    print("\nSpecs: Epson TM-T88V, 42-char thermal receipt paper")
    print("ESC/POS command set support\n")
    
    asyncio.run(main())
