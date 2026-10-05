"""CSV inside a ZIP (IBGE census aggregates): download, save raw, filter to one municipality.

The ZIP is saved to the raw directory BEFORE it is parsed and described (url, HTTP status,
bytes, sha256) for run.json. Only rows whose key starts with the municipality code are kept,
and only the configured columns. Values are kept as text: census files use codes such as
"X" (suppressed) and "." that must never become numbers; see `parse_value`.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

from .wfs import WFSError, _get, _save

NUMBER = re.compile(r"^-?\d+([.,]\d+)?$")


def parse_value(raw: str | None, decimal: str = ".") -> tuple[float | None, str]:
    """(value, status). status: "ok", "suppressed" ("X"), "not_available" ("."), "empty", "invalid"."""
    if raw is None or raw.strip() == "":
        return None, "empty"
    v = raw.strip()
    if v == "X":
        return None, "suppressed"
    if v == ".":
        return None, "not_available"
    if not NUMBER.match(v):
        return None, "invalid"
    if (decimal == "," and "." in v) or (decimal == "." and "," in v):
        return None, "invalid"  # wrong decimal mark for this file: never guess
    return float(v.replace(",", ".")), "ok"


def fetch_csv_zip(session, source: dict, raw_dir: Path, municipality_code: str, timeout: float, retries: int) -> dict:
    """Returns {"file": metadata, "member": name, "columns": [...], "rows": {key: {col: text}},
    "rows_in_file": int}."""
    spec = source["csv"]
    r = _get(session, source["endpoint_url"], timeout, retries)
    meta = _save(raw_dir / Path(source["endpoint_url"]).name, r)
    if r.status_code != 200:
        raise WFSError(f"Download returned HTTP {r.status_code}")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        if spec["member"] not in z.namelist():
            raise WFSError(f"{spec['member']} not in ZIP (members: {z.namelist()})")
        text = z.read(spec["member"]).decode(spec["encoding"])
    reader = csv.DictReader(io.StringIO(text), delimiter=spec["delimiter"])
    missing = [c for c in [spec["key"], *spec["columns"]] if c not in (reader.fieldnames or [])]
    if missing:
        raise WFSError(f"Columns not in {spec['member']}: {missing}")
    rows, total = {}, 0
    for row in reader:
        total += 1
        key = row[spec["key"]]
        if key.startswith(municipality_code):
            rows[key] = {c: row[c] for c in spec["columns"]}
    return {"file": meta, "member": spec["member"], "columns": spec["columns"], "rows": rows, "rows_in_file": total}
