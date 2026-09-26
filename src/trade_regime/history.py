"""Append-only conviction history: every snapshot, with update flags.

The arbiter itself is nearly stateless (held conviction + persistence
counter).  History is the durable memory: it lets a restarted process
review how conviction evolved into a stress event, lets researchers
study hysteresis behavior, and gives the dashboard something to chart.

In-memory by default; pass ``path=`` for a JSONL log (one JSON object
per line, appended, never rewritten).
"""

from __future__ import annotations

import json
import os


class ConvictionHistory:
    """Append-only log of trade-regime snapshot dicts."""

    def __init__(self, path: str | None = None):
        self.path = path
        self.records: list[dict] = []
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        self.records.append(json.loads(line))

    def record(self, snapshot: dict) -> dict:
        """Append a snapshot; return the stored entry.

        The entry is a copy with ``seq`` (0-based index).  The
        snapshot's own hysteresis ``state``/``reason`` are preserved.
        """
        entry = dict(snapshot)
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

    def updates(self) -> list[dict]:
        """Entries where hysteresis released (state == 'updated')."""
        return [r for r in self.records
                if r.get("hysteresis", {}).get("state") == "updated"]
