"""Optional explicit CSV export from either local repository."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Protocol, Any


class RecordSource(Protocol):
    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]: ...


def export_recent_csv(repository: RecordSource, destination: Path, limit: int = 10000) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "qr_data", "raw_digits", "numeric_value", "confidence", "captured_at", "created_at"]
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=destination.parent, delete=False) as file:
            temporary = file.name
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(repository.list_recent(limit))
        os.replace(temporary, destination)
    finally:
        if temporary is not None and Path(temporary).exists():
            Path(temporary).unlink()
    return destination
