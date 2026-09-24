"""Append-only regime history: every assessment, with transition flags.

The arbiter itself is nearly stateless (stance only).  History is the
durable memory: it lets a restarted process rebuild stance, lets
researchers study how conviction evolved into a crisis, and gives the
dashboard something to chart.

In-memory by default; pass ``path=`` for a JSONL log (one JSON object
per line, appended, never rewritten).
"""

from __future__ import annotations

import json
import os


class RegimeHistory:
    """Append-only log of RegimeState dicts."""

    def __init__(self, path: str | None = None):
        self.path = path
        self.records: list[dict] = []
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        self.records.append(json.loads(line))

    def record(self, state: dict) -> dict:
        """Append a RegimeState; return the stored entry.

        The entry is a copy with ``seq`` (0-based index).  The state's
        own ``transition`` flag (set by the arbiter) is preserved.
        """
        entry = dict(state)
        entry["seq"] = len(self.records)
        self.records.append(entry)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        return entry

    def __len__(self) -> int:
        return len(self.records)

    def latest(self) -> dict | None:
        """Most recent entry, or None."""
        return self.records[-1] if self.records else None

    def transitions(self) -> list[dict]:
        """Entries where the stance changed."""
        return [r for r in self.records if r.get("transition")]

    def stance_at(self, seq: int) -> int | None:
        """Rebuild stance memory: stance of entry ``seq``."""
        if 0 <= seq < len(self.records):
            return self.records[seq]["stance"]
        return None

    def to_jsonl(self, path: str) -> int:
        """Dump all records to a JSONL file; returns record count."""
        with open(path, "w", encoding="utf-8") as fh:
            for r in self.records:
                fh.write(json.dumps(r) + "\n")
        return len(self.records)
