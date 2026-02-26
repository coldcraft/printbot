"""
Printer — ESC/POS driver for thermal receipt printer
Handles formatting, connections, and actual printing
"""

import asyncio
import socket
from typing import Dict, Optional
from datetime import datetime

from logger import setup_logger

logger = setup_logger(__name__)

class Printer:
    # ESC/POS command codes
    ESC = b'\x1b'
    GS = b'\x1d'
    LF = b'\n'
    
    CMD_INIT = ESC + b'@'  # Initialize printer
    CMD_CUT = GS + b'V' + b'A' + b'\x00'  # Full cut
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
        self.socket = None
        self.connected = False
    
    async def connect(self):
        """Connect to network printer"""
        try:
            # Use asyncio to handle socket connection
            loop = asyncio.get_event_loop()
            self.socket = await loop.run_in_executor(
                None,
                self._create_socket
            )
            self.connected = True
            logger.info(f"Connected to printer at {self.ip}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to printer: {e}")
            self.connected = False
            raise

    def _create_socket(self) -> socket.socket:
        """Create and connect socket (run in executor)"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((self.ip, self.port))
        return sock

    async def disconnect(self):
        """Close connection"""
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                logger.error(f"Error closing socket: {e}")
            self.connected = False

    async def print_receipt(self, job: Dict):
        """
        Main print function — routes to template based on intent_type
        """
        if not self.connected or not self.socket:
            raise Exception("Printer not connected")
        
        intent_type = job.get("intent_type", "generic")
        logger.info(f"Printing receipt: {intent_type}")
        
        # Initialize printer
        await self._write(self.CMD_INIT)
        
        # Route based on intent
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
        logger.info(f"Receipt printed and cut for {intent_type}")

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
        """Print URL summary with QR code"""
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
        
        # QR code placeholder (TODO: generate real QR)
        if url:
            await self._write(self.CMD_ALIGN_CENTER)
            await self._text("[QR CODE]\n")
        
        await self._text("─" * 32 + "\n")
        await self._write(self.CMD_ALIGN_RIGHT)
        await self._text(f"sent via SMS · printbot v0.1\n")

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
        # Content should have list items, each on own line
        items = content.split("\n") if isinstance(content, str) else content
        for item in items:
            if item.strip():
                await self._text(f"☐ {item}\n")
        
        await self._text("\n" + "─" * 32 + "\n")

    async def _print_question(self, job: Dict):
        """Print Q&A receipt"""
        content = job.get("content", "")
        timestamp = job.get("received_at", datetime.utcnow().isoformat())
        
        await self._write(self.CMD_ALIGN_CENTER)
        await self._write(self.CMD_BOLD_ON)
        await self._text("❓ QUESTION\n")
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
        
        dt = self._parse_timestamp(timestamp)
        await self._text(f"{dt.strftime('%b %d %Y  %H:%M')}\n")
        await self._text("─" * 32 + "\n\n")
        
        await self._write(self.CMD_ALIGN_LEFT)
        await self._text(content + "\n")
        await self._text("\n" + "─" * 32 + "\n")

    async def _text(self, text: str):
        """Write text to printer"""
        await self._write(text.encode('utf-8', errors='replace'))

    async def _write(self, data: bytes):
        """Write data to socket"""
        if not self.connected or not self.socket:
            raise Exception("Printer not connected")
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.socket.sendall(data)
            )
        except Exception as e:
            logger.error(f"Error writing to printer: {e}")
            self.connected = False
            raise

    def _parse_timestamp(self, ts: str) -> datetime:
        """Parse ISO timestamps, accepting trailing Z. Fallback to now on errors."""
        try:
            if ts.endswith("Z"):
                ts = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except Exception:
            logger.warning(f"Invalid timestamp '{ts}', using current time")
            return datetime.utcnow()
