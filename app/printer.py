"""
Printer — ESC/POS driver for thermal receipt printer
Handles formatting, connections, and actual printing
"""

import asyncio
import socket
import struct
import os
import re
import textwrap
from typing import Dict, Optional, List
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from logger import setup_logger

logger = setup_logger(__name__)

class Printer:
    CHAR_WIDTH = 42
    LIST_ITEM_PREFIX = "[ ] "
    LIST_CONTINUATION_PREFIX = "    "
    LIST_HEADER_PATTERN = re.compile(
        r"^\s*(?:check\s*list|checklist|list|to-?do|todo|task(?:s)?|task\s*list)\s*[:\-]\s*",
        re.IGNORECASE,
    )

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
    CODEPAGE_COMMANDS = {
        "cp437": 0,
        "pc437": 0,
        "cp850": 2,
        "cp860": 3,
        "cp863": 4,
        "cp865": 5,
        "cp1252": 16,
    }

    CODEPAGE_ENCODINGS = {
        "cp437": "cp437",
        "pc437": "cp437",
        "cp850": "cp850",
        "cp860": "cp860",
        "cp863": "cp863",
        "cp865": "cp865",
        "cp1252": "cp1252",
    }
    
    def __init__(self, ip: str, port: int = 9100):
        self.ip = ip
        self.port = port
        self.socket = None
        self.connected = False
        requested_codepage = os.getenv("PRINTER_CODEPAGE", "cp437").strip().lower()
        if requested_codepage not in self.CODEPAGE_COMMANDS:
            logger.warning(f"Unsupported PRINTER_CODEPAGE '{requested_codepage}', falling back to cp437")
            requested_codepage = "cp437"
        self.codepage = requested_codepage
        self.text_encoding = self.CODEPAGE_ENCODINGS[self.codepage]
        self.cmd_codepage = self.ESC + b't' + bytes([self.CODEPAGE_COMMANDS[self.codepage]])
        self.display_tz = self._load_display_timezone()
    
    async def connect(self):
        """Connect to network printer"""
        # Close any existing socket first to avoid leaking stale connections.
        # Run in executor since SO_LINGER can make close() block for seconds.
        if self.socket:
            stale = self.socket
            self.socket = None
            self.connected = False
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, stale.close)
            except Exception:
                pass
        try:
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
        # Block close() until all queued bytes have been ACKed (or 2s elapse).
        # Without this, large prints (photos) can race the FIN packet and lose
        # the trailing footer/cut commands. 2s is enough headroom for a photo
        # raster to drain; 10s introduced multi-second stalls in normal flow.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 2))
        sock.connect((self.ip, self.port))
        return sock

    async def disconnect(self):
        """Close connection. Runs in executor since SO_LINGER can block for seconds."""
        if self.socket:
            stale = self.socket
            self.socket = None
            self.connected = False
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, stale.close)
            except Exception as e:
                logger.error(f"Error closing socket: {e}")

    async def print_receipt(self, job: Dict):
        """
        Main print function — routes to template based on intent_type.
        Connects fresh for each job to avoid stale socket issues.
        """
        await self.connect()
        try:
            intent_type = job.get("intent_type", "generic")
            logger.info(f"Printing receipt: {intent_type}")

            # Initialize printer
            await self._write(self.CMD_INIT)
            await self._write(self.cmd_codepage)

            # Route based on intent
            if intent_type == "reminder":
                await self._print_reminder(job)
            elif intent_type == "url":
                await self._print_url_summary(job)
            elif intent_type == "list":
                await self._print_list(job)
            elif intent_type == "question":
                await self._print_question(job)
            elif intent_type == "photo":
                await self._print_photo(job)
            else:
                await self._print_generic(job)

            # Cut paper and finish
            await self._write(self.LF + self.LF)
            await self._write(self.CMD_CUT)
            # Give the printer firmware a beat to actually process the trailing
            # bytes — TCP ACK only confirms receipt, not ESC/POS execution.
            # Without this, large prints can be torn down mid-cut.
            await asyncio.sleep(1.5 if intent_type == "photo" else 0.3)
            logger.info(f"Receipt printed and cut for {intent_type}")
        finally:
            await self.disconnect()

    async def _print_reminder(self, job: Dict):
        """Print reminder receipt"""
        timestamp = job.get("received_at", datetime.utcnow().isoformat())
        content = job.get("content", "")
        sender = self._sender_label(job)

        await self._print_brand()
        await self._print_header("REMINDER", self._parse_timestamp(timestamp))
        await self._print_divider()

        await self._write(self.CMD_BOLD_ON)
        for line in self._wrap_body(content):
            await self._text(line + "\n")
        await self._write(self.CMD_BOLD_OFF)

        await self._print_footer(sender)

    async def _print_url_summary(self, job: Dict):
        """Print URL summary with QR code"""
        content = job.get("content", "")
        url = job.get("metadata", {}).get("original_url", "")
        sender = self._sender_label(job)
        timestamp = job.get("received_at", datetime.utcnow().isoformat())

        await self._print_brand()
        await self._print_header(None, self._parse_timestamp(timestamp))
        await self._print_divider()

        await self._write(self.CMD_ALIGN_CENTER)
        await self._write(self.CMD_BOLD_ON)
        await self._text("URL SUMMARY\n")
        await self._write(self.CMD_BOLD_OFF)

        if url:
            display_url = url if len(url) <= self.CHAR_WIDTH else f"{url[:self.CHAR_WIDTH - 3]}..."
            await self._text(f"{display_url}\n")

        await self._write(self.CMD_ALIGN_LEFT)
        await self._text("\n")
        for line in self._wrap_body(content):
            await self._text(line + "\n")

        if url:
            await self._text("\n")
            await self._write(self.CMD_ALIGN_CENTER)
            await self._print_qr_code(url)
            await self._text("\n")

        await self._print_footer(sender)

    async def _print_list(self, job: Dict):
        """Print list receipt"""
        content = job.get("content", "")
        timestamp = job.get("received_at", datetime.utcnow().isoformat())
        sender = self._sender_label(job)

        await self._print_brand()
        await self._print_header("CHECKLIST", self._parse_timestamp(timestamp))
        await self._print_divider()

        await self._write(self.CMD_ALIGN_LEFT)
        list_items = self._split_list_items(content)
        if not list_items:
            await self._text("(no list items provided)\n")
        else:
            for item in list_items:
                wrapped_lines = self._wrap_list_item(item)
                if not wrapped_lines:
                    continue
                await self._text(f"{self.LIST_ITEM_PREFIX}{wrapped_lines[0]}\n")
                for continuation in wrapped_lines[1:]:
                    await self._text(f"{self.LIST_CONTINUATION_PREFIX}{continuation}\n")

        await self._print_footer(sender)

    def _split_list_items(self, content) -> List[str]:
        text = ""
        if isinstance(content, list):
            raw_items = content
        else:
            text = str(content or "")
            normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
            normalized = self._strip_list_header(normalized)
            if "\n" in normalized:
                raw_items = normalized.split("\n")
            elif any(sep in normalized for sep in [";", ",", "•", "- "]):
                raw_items = re.split(r"[;,•\u2022]+", normalized)
            else:
                raw_items = [normalized] if normalized else []

        items: List[str] = []
        for raw in raw_items:
            cleaned = str(raw or "").strip()
            cleaned = self._strip_list_header(cleaned)
            cleaned = re.sub(r"^\s*(?:[-*•\u2022]+|\d+[.)])\s*", "", cleaned)
            cleaned = " ".join(cleaned.split())
            if cleaned:
                items.append(cleaned)

        if not items and text:
            return [text.strip()]

        return items

    def _strip_list_header(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        return self.LIST_HEADER_PATTERN.sub("", text, count=1)

    def _wrap_list_item(self, item: str) -> List[str]:
        normalized = " ".join(str(item or "").split())
        if not normalized:
            return []

        available_width = max(8, self.CHAR_WIDTH - len(self.LIST_ITEM_PREFIX))
        wrapped = textwrap.wrap(
            normalized,
            width=available_width,
            break_long_words=False,
            drop_whitespace=True,
        )
        return wrapped or [normalized]

    async def _print_question(self, job: Dict):
        """Print Q&A receipt"""
        content = job.get("content", "")
        metadata = job.get("metadata", {}) if isinstance(job.get("metadata"), dict) else {}
        question_text_raw = str(
            metadata.get("question_text")
            or job.get("original_message", "")
        )
        question_text = question_text_raw.strip()
        answer_text_raw = str(content or "")
        answer_text = answer_text_raw.strip()
        timestamp = job.get("received_at", datetime.utcnow().isoformat())
        sender = self._sender_label(job)

        await self._print_brand()
        await self._print_header("QUESTION", self._parse_timestamp(timestamp))
        await self._print_divider()

        await self._write(self.CMD_ALIGN_LEFT)
        condensed_q = re.sub(r"\s+", " ", question_text_raw).strip().casefold()
        condensed_a = re.sub(r"\s+", " ", answer_text_raw).strip().casefold()
        answers_differ = bool(answer_text) and (not condensed_q or condensed_a != condensed_q)
        logger.debug(
            "Question print job: sender=%s q_len=%d a_len=%d answers_differ=%s",
            sender,
            len(question_text),
            len(answer_text),
            answers_differ,
        )

        if question_text:
            await self._text("Q:\n")
            for line in self._wrap_body(question_text):
                await self._text(line + "\n")
            await self._text("\n")
        elif answers_differ and answer_text:
            logger.warning("Question job missing question_text; using answer only")

        if not answers_differ and answer_text:
            logger.warning(
                "Question answer identical to question; suppressing duplicate block for %s",
                sender,
            )

        if answers_differ and answer_text:
            answer_display = answer_text
            prefix_match = re.match(r"^(answer\s*:)(.*)$", answer_text.strip(), re.IGNORECASE)
            if prefix_match:
                answer_display = prefix_match.group(2).lstrip() or answer_text
            await self._text("A:\n")
            for line in self._wrap_body(answer_display):
                await self._text(line + "\n")

        await self._print_footer(sender)

    async def _print_generic(self, job: Dict):
        """Print generic receipt — no intent label, just the message."""
        content = job.get("content", "")
        timestamp = job.get("received_at", datetime.utcnow().isoformat())
        sender = self._sender_label(job)

        await self._print_brand()
        await self._print_header(None, self._parse_timestamp(timestamp))
        await self._print_divider()

        await self._write(self.CMD_ALIGN_LEFT)
        for line in self._wrap_body(content):
            await self._text(line + "\n")

        await self._print_footer(sender)

    def _divider(self) -> str:
        return "-" * self.CHAR_WIDTH

    BRAND_BANNER = (
        "██████╗ ██████╗ ███╗   ██╗██████╗ ",
        "██╔══██╗██╔══██╗████╗  ██║██╔══██╗",
        "██████╔╝██████╔╝██╔██╗ ██║██████╔╝",
        "██╔══██╗██╔══██╗██║╚██╗██║██╔══██╗",
        "██████╔╝██║  ██║██║ ╚████║██║  ██║",
        "╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝",
    )

    async def _print_brand(self):
        """Print the BURNR brand banner at the top of a receipt."""
        await self._write(self.CMD_ALIGN_CENTER)
        for line in self.BRAND_BANNER:
            await self._text(line + "\n")
        await self._write(self.CMD_ALIGN_LEFT)

    async def _print_header(self, title: Optional[str], dt: datetime):
        """Optional bold centered title + centered timestamp."""
        await self._write(self.CMD_ALIGN_CENTER)
        if title:
            await self._write(self.CMD_BOLD_ON)
            await self._text(f"{title}\n")
            await self._write(self.CMD_BOLD_OFF)
        await self._text(f"{self._format_timestamp(dt)}\n")

    def _format_timestamp(self, dt: datetime) -> str:
        """Human-friendly receipt timestamp, e.g. 'Tue Apr 28 - 4:11 PM'."""
        weekday_month = dt.strftime("%a %b")
        day = dt.day
        time_part = dt.strftime("%I:%M %p").lstrip("0")
        return f"{weekday_month} {day} · {time_part}"

    async def _print_divider(self):
        """Left-aligned full-width divider with one blank line above and below."""
        await self._write(self.CMD_ALIGN_LEFT)
        await self._text("\n" + self._divider() + "\n\n")

    def _wrap_paragraph(self, line: str) -> List[str]:
        """Wrap a single line/paragraph to the printer width without splitting words."""
        text = (line or "").rstrip()
        if not text:
            return [""]
        wrapped = textwrap.wrap(
            text,
            width=self.CHAR_WIDTH,
            break_long_words=False,
            break_on_hyphens=False,
            drop_whitespace=True,
        )
        return wrapped or [text]

    def _wrap_body(self, content) -> List[str]:
        """Wrap content for the receipt body, preserving paragraph breaks."""
        if isinstance(content, list):
            content = "\n".join(str(part) for part in content)
        text = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            return []

        out: List[str] = []
        paragraphs = text.split("\n\n")
        for p_idx, para in enumerate(paragraphs):
            for raw_line in para.split("\n"):
                if raw_line.strip():
                    out.extend(self._wrap_paragraph(raw_line))
                else:
                    out.append("")
            if p_idx < len(paragraphs) - 1:
                out.append("")  # blank line between paragraphs
        return out

    async def _print_footer(self, sender: str):
        """Standard receipt footer used across all intent types."""
        await self._write(self.CMD_ALIGN_LEFT)
        await self._text("\n" + self._divider() + "\n")
        await self._write(self.CMD_ALIGN_CENTER)
        await self._text(f"from {sender}\n")
        await self._text("sent via SMS\n")
        await self._write(self.CMD_ALIGN_LEFT)

    async def _text(self, text: str):
        """Write text to printer"""
        await self._write(self._encode_text(text))

    def _encode_text(self, text: str) -> bytes:
        replacements = {
            "★": "*",
            "─": "-",
            "☐": "[ ]",
            "❓": "?",
            "·": "-",
            "“": '"',
            "”": '"',
            "’": "'",
            "–": "-",
            "—": "-",
        }
        cleaned = text
        for source, target in replacements.items():
            cleaned = cleaned.replace(source, target)
        return cleaned.encode(self.text_encoding, errors="replace")

    PHOTO_WIDTH_DOTS = 384  # safe sub-print-head width with margin
    PHOTO_MAX_HEIGHT_DOTS = 1200  # cap so older firmware doesn't choke on huge rasters

    async def _print_photo(self, job: Dict):
        """Print an image as a 1-bit Floyd-Steinberg-dithered raster (ESC/POS GS v 0)."""
        try:
            from PIL import Image
        except ImportError:
            logger.error("Pillow not installed; cannot print photo")
            return

        from io import BytesIO

        image_bytes = job.get("image_bytes")
        image_path = job.get("image_path")

        if image_bytes:
            src = BytesIO(image_bytes if isinstance(image_bytes, (bytes, bytearray)) else bytes(image_bytes))
        elif image_path:
            src = image_path
        else:
            logger.error("Photo job missing image_bytes / image_path")
            return

        try:
            img = Image.open(src)
            orig_size = img.size
            img = img.convert("L")
        except Exception as e:
            logger.error(f"Failed to decode photo: {e}")
            return

        if img.width != self.PHOTO_WIDTH_DOTS:
            scale = self.PHOTO_WIDTH_DOTS / img.width
            new_height = max(1, int(img.height * scale))
            img = img.resize((self.PHOTO_WIDTH_DOTS, new_height), Image.LANCZOS)

        if img.height > self.PHOTO_MAX_HEIGHT_DOTS:
            img = img.crop((0, 0, img.width, self.PHOTO_MAX_HEIGHT_DOTS))

        img = img.convert("1", dither=Image.FLOYDSTEINBERG)
        logger.info(
            f"Photo prepared: orig={orig_size[0]}x{orig_size[1]} -> printed={img.width}x{img.height} "
            f"(bands={(img.height + self.PHOTO_BAND_HEIGHT - 1) // self.PHOTO_BAND_HEIGHT})"
        )

        timestamp = job.get("received_at", datetime.utcnow().isoformat())
        sender = self._sender_label(job)
        caption = job.get("content", "")

        await self._print_brand()
        await self._print_header("PHOTO", self._parse_timestamp(timestamp))
        await self._print_divider()

        raster = self._image_to_raster(img)
        await self._write(self.CMD_ALIGN_CENTER)
        await self._write(raster)
        await self._write(self.CMD_ALIGN_LEFT)

        if caption:
            await self._text("\n")
            for line in self._wrap_body(caption):
                await self._text(line + "\n")

        await self._print_footer(sender)

    PHOTO_BAND_HEIGHT = 24  # rows per GS v 0 command — keeps each command small

    def _image_to_raster(self, img) -> bytes:
        """Pack a PIL '1'-mode image into ESC/POS GS v 0 raster commands.

        Tall images are split into horizontal bands so each command stays short
        and the printer gets natural sync points, avoiding buffer/height limits
        that can leave the printer stuck mid-stream.
        """
        width, height = img.size
        width_bytes = (width + 7) // 8
        pixels = img.load()
        xL = width_bytes & 0xFF
        xH = (width_bytes >> 8) & 0xFF

        out = bytearray()
        for band_start in range(0, height, self.PHOTO_BAND_HEIGHT):
            band_end = min(band_start + self.PHOTO_BAND_HEIGHT, height)
            band_h = band_end - band_start
            yL = band_h & 0xFF
            yH = (band_h >> 8) & 0xFF
            out.extend(self.GS + b'v0' + bytes([0, xL, xH, yL, yH]))
            for y in range(band_start, band_end):
                byte = 0
                for x in range(width):
                    if pixels[x, y] == 0:  # PIL '1': 0=black; ESC/POS: bit=1 prints
                        byte |= 1 << (7 - (x & 7))
                    if (x & 7) == 7:
                        out.append(byte)
                        byte = 0
                if width & 7:
                    out.append(byte)

        return bytes(out)

    async def _print_qr_code(self, data: str):
        payload = data.encode("utf-8", errors="replace")
        if not payload:
            return

        if len(payload) > 7089:
            payload = payload[:7089]

        pL = (len(payload) + 3) & 0xFF
        pH = ((len(payload) + 3) >> 8) & 0xFF

        await self._write(self.GS + b'(k' + bytes([4, 0, 49, 65, 50, 0]))
        await self._write(self.GS + b'(k' + bytes([3, 0, 49, 67, 6]))
        await self._write(self.GS + b'(k' + bytes([3, 0, 49, 69, 49]))
        await self._write(self.GS + b'(k' + bytes([pL, pH, 49, 80, 48]) + payload)
        await self._write(self.GS + b'(k' + bytes([3, 0, 49, 81, 48]))

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
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(self.display_tz)
        except Exception:
            logger.warning(f"Invalid timestamp '{ts}', using current time")
            now = datetime.now(timezone.utc)
            return now.astimezone(self.display_tz)

    def _load_display_timezone(self):
        tz_name = os.getenv("PRINTER_TIMEZONE", "").strip()
        if tz_name and ZoneInfo:
            try:
                tz = ZoneInfo(tz_name)
                logger.info(f"Printer timestamps will use {tz_name}")
                return tz
            except Exception:
                logger.warning(f"Invalid PRINTER_TIMEZONE '{tz_name}', falling back to system zone")

        try:
            local_tz = datetime.now().astimezone().tzinfo
            if local_tz:
                return local_tz
        except Exception:
            logger.warning("Could not determine system timezone; defaulting to UTC")

        return timezone.utc

    def _sender_label(self, job: Dict) -> str:
        label = str(job.get("sender_display") or job.get("sender") or "SMS").strip()
        return label or "SMS"
