"""Helpers for the UI's Excel copy/paste: parse tab- or comma-separated text
into 2D numeric tables and back. Pure stdlib so it works under Pyodide."""
from __future__ import annotations


def parse_grid(text: str) -> list[list[str]]:
    """Parse pasted spreadsheet text (TSV preferred, CSV fallback) into rows of
    cell strings. Blank trailing lines are ignored."""
    rows: list[list[str]] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip() == "":
            continue
        sep = "\t" if "\t" in line else ","
        rows.append([c.strip() for c in line.split(sep)])
    return rows


def parse_numeric_column(text: str) -> list[float]:
    """Parse a single pasted column of numbers (handles %, $ and commas)."""
    out: list[float] = []
    for row in parse_grid(text):
        if not row:
            continue
        out.append(_to_float(row[0]))
    return out


def _to_float(s: str) -> float:
    s = s.strip().replace("$", "").replace(",", "")
    if s.endswith("%"):
        return float(s[:-1]) / 100.0
    return float(s)


def to_tsv(rows: list[list]) -> str:
    return "\n".join("\t".join(str(c) for c in row) for row in rows)
