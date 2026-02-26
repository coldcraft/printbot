"""
MockPrinter — Simulator adapter for development
Routes print jobs to dev_printer.py (localhost:9100) for live viewing
Drops in as a replacement for Printer class with zero code changes
"""

import asyncio
import socket
from typing import Dict
from datetime import datetime

from logger import setup_logger

logger = setup_logger(__name__)


class MockPrinter:
    """
    Mock printer that sends ESC/POS data to dev_printer.py instead of real printer.
    Compatible with the Printer class interface.
    
    Usage:
        1. Start dev_printer.py in another terminal
        2. Set PRINTER_IP=127.0.0.1 in .env
        3. Run PrintBot normally - jobs will show in dev_printer.py
    """
    
    # ESC/POS command codes (same as Printer)
    ESC = b'\x1b'
    GS = b'\x1d'
    LF = b'\n'
    
    CMD_INIT = ESC + b'@'
    CMD_CUT = GS + b'V' + b'A' + b'\x00'
    CMD_BOLD_ON = ESC + b'E' + b'\x01'
    CMD_BOLD_OFF = ESC + b'E' + b'\x00'
    CMD_ALIGN_LEFT = ESC + b'a' + b'\x00'
    CMD_ALIGN_CENTER = ESC + b'a' + b'\x01'
    CMD_ALIGN_RIGHT = ESC + b'a' + b'\x02'
    CMD_SIZE_NORMAL = ESC + b'!' + b'\x00'
    CMD_SIZE_DOUBLE = ESC + b'!' + b'\x11'
    
    def __init__(self, ip: str, port: int = 9100):
        self.ip = ip
        self.port = port
        self.connected = False
        self.buffer = bytearray()
        
    async def connect(self):
        """Simulate connection (no actual connection needed)"""
        self.connected = True
        logger.info(f"[MOCK] Connected to simulator at {self.ip}:{self.port}")
        
    async def disconnect(self):
        """Clean shutdown"""
        self.connected = False

    async def print_receipt(self, job: Dict):
        """Main print function - same interface as real Printer"""
        if not self.connected:
            raise Exception("Mock printer not connected")
        
        intent_type = job.get("intent_type", "generic")
        logger.info(f"[MOCK] Printing receipt: {intent_type}")
        
        # Reset buffer for this job
        self.buffer = bytearray()
        
        # Initialize printer
        await self._write(self.CMD_INIT)
        
        # Route based on intent (same as real printer)
        if intent_type == "reminder":
            await self._print_reminder(job)
        elif intent_type == "url":
            await self._print_url_summary(job)
        elif intent_type == "list":
            await self._print_list(job)
        elif intent_type == "question":
            await self._print_question(job)
        else:
            await self._print_generic(job)
        
        # Cut paper and finish
        await self._write(self.LF + self.LF)
        await self._write(self.CMD_CUT)
        
        # Send all buffered data to dev_printer.py in one shot
        await self._send_to_simulator()
        
        logger.info(f"[MOCK] Receipt sent to simulator ({len(self.buffer)} bytes)")

    async def _print_reminder(self, job: Dict):
        """Print reminder receipt"""
        timestamp = job.get("received_at", datetime.utcnow().isoformat())
        content = job.get("content", "")
        sender = job.get("sender", "SMS")
        
        await self._write(self.CMD_ALIGN_CENTER)
        await self._write(self.CMD_BOLD_ON)
        await self._text("★ REMINDER ★\n")
        await self._write(self.CMD_BOLD_OFF)
        
        await self._write(self.CMD_ALIGN_CENTER)
        dt = self._parse_timestamp(timestamp)
        await self._text(f"{dt.strftime('%b %d %Y  %H:%M')}\n")
        
        await self._write(self.CMD_ALIGN_LEFT)
        await self._text("\n" + "─" * 32 + "\n\n")
        
        await self._write(self.CMD_BOLD_ON)
        await self._text(content + "\n")
        await self._write(self.CMD_BOLD_OFF)
        
        await self._text("\n" + "─" * 32 + "\n")
        await self._write(self.CMD_ALIGN_CENTER)
        await self._text(f"from {sender}\n")

    async def _print_url_summary(self, job: Dict):
        """Print URL summary"""
        content = job.get("content", "")
        url = job.get("metadata", {}).get("original_url", "")
        sender = job.get("sender", "SMS")
        timestamp = job.get("received_at", datetime.utcnow().isoformat())
        
        await self._write(self.CMD_ALIGN_CENTER)
        await self._write(self.CMD_BOLD_ON)
        await self._text("★ PRINTBOT ★\n")
        await self._write(self.CMD_BOLD_OFF)
        
        dt = self._parse_timestamp(timestamp)
        await self._text(f"{dt.strftime('%b %d %Y  %H:%M')}\n")
        
        await self._text("─" * 32 + "\n")
        await self._write(self.CMD_BOLD_ON)
        await self._text("URL SUMMARY\n")
        await self._write(self.CMD_BOLD_OFF)
        
        if url:
            await self._text(f"{url[:40]}...\n" if len(url) > 40 else f"{url}\n")
        
        await self._text("\n" + content + "\n")
        await self._text("\n" + "─" * 32 + "\n")
        
        if url:
            await self._write(self.CMD_ALIGN_CENTER)
            await self._text("[QR CODE]\n")
        
        await self._text("─" * 32 + "\n")
        await self._write(self.CMD_ALIGN_RIGHT)
        await self._text("sent via SMS - printbot v0.1\n")

    async def _print_list(self, job: Dict):
        """Print list receipt"""
        content = job.get("content", "")
        timestamp = job.get("received_at", datetime.utcnow().isoformat())
        
        await self._write(self.CMD_ALIGN_CENTER)
        await self._write(self.CMD_BOLD_ON)
        await self._text("★ CHECKLIST ★\n")
        await self._write(self.CMD_BOLD_OFF)
        
        dt = self._parse_timestamp(timestamp)
        await self._text(f"{dt.strftime('%b %d %Y  %H:%M')}\n")
        await self._text("─" * 32 + "\n\n")
        
        await self._write(self.CMD_ALIGN_LEFT)
        items = content.split("\n") if isinstance(content, str) else content
        for item in items:
            if item.strip():
                await self._text(f"[ ] {item}\n")
        
        await self._text("\n" + "─" * 32 + "\n")

    async def _print_question(self, job: Dict):
        """Print Q&A receipt"""
        content = job.get("content", "")
        timestamp = job.get("received_at", datetime.utcnow().isoformat())
        
        await self._write(self.CMD_ALIGN_CENTER)
        await self._write(self.CMD_BOLD_ON)
        await self._text("QUESTION\n")
        await self._write(self.CMD_BOLD_OFF)
        
        dt = self._parse_timestamp(timestamp)
        await self._text(f"{dt.strftime('%b %d %Y  %H:%M')}\n")
        await self._text("─" * 32 + "\n\n")
        
        await self._write(self.CMD_ALIGN_LEFT)
        await self._text(content + "\n")
        await self._text("\n" + "─" * 32 + "\n")

    async def _print_generic(self, job: Dict):
        """Print generic receipt"""
        content = job.get("content", "")
        intent = job.get("intent_type", "MESSAGE")
        timestamp = job.get("received_at", datetime.utcnow().isoformat())
        
        await self._write(self.CMD_ALIGN_CENTER)
        await self._write(self.CMD_BOLD_ON)
        await self._text(f"{intent.upper()}\n")
        await self._write(self.CMD_BOLD_OFF)
        
        dt = datetime.fromisoformat(timestamp)
        await self._text(f"{dt.strftime('%b %d %Y  %H:%M')}\n")
        await self._text("─" * 32 + "\n\n")
        
        await self._write(self.CMD_ALIGN_LEFT)
        await self._text(content + "\n")
        await self._text("\n" + "─" * 32 + "\n")

    async def _text(self, text: str):
        """Write text to buffer"""
        await self._write(text.encode('utf-8', errors='replace'))

    async def _write(self, data: bytes):
        """Buffer data instead of sending to socket"""
        self.buffer.extend(data)

    async def _send_to_simulator(self):
        """Send buffered ESC/POS data to dev_printer.py"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._connect_and_send
            )
        except Exception as e:
            logger.error(f"[MOCK] Failed to send to simulator: {e}")
            raise

    def _connect_and_send(self):
        """Connect to simulator and send data (blocking)"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.ip, self.port))
            sock.sendall(bytes(self.buffer))
            sock.close()
            logger.debug(f"[MOCK] Sent {len(self.buffer)} bytes to simulator")
        except Exception as e:
            logger.error(f"[MOCK] Socket error: {e}")
            raise

    def _parse_timestamp(self, ts: str) -> datetime:
        """Parse ISO timestamps, accepting trailing Z. Fallback to now on errors."""
        try:
            if ts.endswith("Z"):
                ts = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except Exception:
            logger.warning(f"[MOCK] Invalid timestamp '{ts}', using current time")
            return datetime.utcnow()
