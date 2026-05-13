"""
PrintBot Test Receipt Generator

Drives the real app/printer.py renderer with sample jobs and renders the
captured ESC/POS byte stream through printer_simulator.PrinterSimulator so
the previews match what the physical printer would actually emit.

Usage:
    python test_receipts.py                # all samples
    python test_receipts.py --reminder     # one sample
    python test_receipts.py --list
    python test_receipts.py --url
    python test_receipts.py --question
    python test_receipts.py --generic

On Windows, set PYTHONIOENCODING=utf-8 so the cp437 box-drawing glyphs in
the BANJA brand banner can render to your terminal.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from printer import Printer  # noqa: E402
from printer_simulator import PrinterSimulator  # noqa: E402


class CapturingPrinter(Printer):
    """Printer subclass that buffers ESC/POS bytes instead of sending over TCP."""

    def __init__(self):
        super().__init__(ip="127.0.0.1", port=9100)
        self.captured = bytearray()

    async def connect(self):
        self.connected = True
        self.socket = object()  # truthy sentinel for _write's guard

    async def disconnect(self):
        self.connected = False
        self.socket = None

    async def _write(self, data: bytes):
        self.captured.extend(data)


async def _render(job) -> str:
    printer = CapturingPrinter()
    await printer.print_receipt(job)
    sim = PrinterSimulator(width=Printer.CHAR_WIDTH, default_codepage=printer.codepage)
    sim.feed(bytes(printer.captured))
    return sim.render_to_string()


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


def job_reminder():
    return {
        "intent_type": "reminder",
        "content": "Cancel couples on June 12",
        "sender_display": "Sarey McBeary",
        "received_at": _iso(datetime(2026, 5, 4, 20, 24)),
    }


def job_list():
    return {
        "intent_type": "list",
        "content": "Milk, Bread, Eggs, Butter, Coffee, Apples, Chicken breast",
        "sender_display": "Family",
        "received_at": _iso(datetime(2026, 5, 13, 14, 0)),
    }


def job_url():
    return {
        "intent_type": "url",
        "content": "A Python library for thermal receipt printing and formatting. Great for POS systems and IoT projects.",
        "metadata": {"original_url": "https://github.com/example/repo"},
        "sender_display": "drew",
        "received_at": _iso(datetime(2026, 5, 12, 21, 22)),
    }


def job_question():
    return {
        "intent_type": "question",
        "content": "ANSWER: Alexander Graham Bell, patented in 1876.",
        "original_message": "who invented the telephone?",
        "metadata": {"question_text": "who invented the telephone?"},
        "sender_display": "drew",
        "received_at": _iso(datetime(2026, 5, 12, 21, 21)),
    }


def job_generic():
    return {
        "intent_type": "generic",
        "content": "Any updates, bitch?",
        "sender_display": "drew",
        "received_at": _iso(datetime(2026, 5, 12, 21, 21)),
    }


SAMPLES = {
    "reminder": ("Reminder receipt", job_reminder),
    "list": ("Checklist receipt", job_list),
    "url": ("URL summary receipt", job_url),
    "question": ("Question receipt", job_question),
    "generic": ("Generic message receipt", job_generic),
}


async def _main(selected):
    for key in selected:
        title, builder = SAMPLES[key]
        print("\n" + "=" * 50)
        print(f"SAMPLE: {title}")
        print("=" * 50)
        print(await _render(builder()))


def main():
    if len(sys.argv) > 1:
        keys = [arg.lstrip("-") for arg in sys.argv[1:]]
        unknown = [k for k in keys if k not in SAMPLES]
        if unknown:
            print(f"Unknown sample(s): {', '.join(unknown)}")
            print(f"Available: {', '.join(SAMPLES.keys())}")
            sys.exit(1)
    else:
        keys = list(SAMPLES.keys())

    asyncio.run(_main(keys))


if __name__ == "__main__":
    main()
