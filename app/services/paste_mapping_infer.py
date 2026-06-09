import re
from html.parser import HTMLParser
from typing import Any

from app.services.paste_parse_config import config_to_yaml

MD_DATE_REGEX = r"(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])"


def _norm_header(header: str) -> str:
    return header.strip().lower()


def _find_header(template_headers: list[str], *candidates: str) -> str | None:
    by_norm = {_norm_header(header): header for header in template_headers}
    for candidate in candidates:
        key = candidate.lower()
        if key in by_norm:
            return by_norm[key]
    return None


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] = []
        self._cell_parts: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        if tag in {"td", "th"}:
            self._cell_parts = []
            self._in_cell = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            cell_text = "".join(self._cell_parts).strip()
            self._current_row.append(cell_text)
            self._cell_parts = []
            self._in_cell = False
        if tag == "tr":
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)


def _extract_markdown_row(text: str) -> list[str] | None:
    lines = [line.strip() for line in text.splitlines() if "|" in line]
    if not lines:
        return None

    def is_separator(line: str) -> bool:
        stripped = line.strip().strip("|")
        if not stripped:
            return True
        return all(ch in "-: " for ch in stripped)

    candidates = [line for line in lines if not is_separator(line)]
    if not candidates:
        return None
    row_line = candidates[1] if len(candidates) >= 2 else candidates[0]
    cells = [cell.strip() for cell in row_line.strip().strip("|").split("|")]
    return [cell for cell in cells if cell or len(cells) > 1]


def _extract_html_row(text: str) -> list[str] | None:
    if "<table" not in text.lower() and "<tr" not in text.lower():
        return None
    parser = _HtmlTableParser()
    parser.feed(text)
    if not parser.rows:
        return None
    data_rows = [row for row in parser.rows if any(cell.strip() for cell in row)]
    if len(data_rows) >= 2:
        return data_rows[1]
    return data_rows[0]


def extract_sample_line(raw_text: str) -> str:
    for line in raw_text.splitlines():
        if "\t" in line and line.strip():
            return line.strip()
    row = _extract_markdown_row(raw_text)
    if row:
        return "\t".join(row)
    row = _extract_html_row(raw_text)
    if row:
        return "\t".join(row)
    return next((line.strip() for line in raw_text.splitlines() if line.strip()), "")


def _classify_columns(parts: list[str]) -> dict[str, list[int]]:
    buckets: dict[str, list[int]] = {
        "po": [],
        "container": [],
        "md_date": [],
        "description": [],
        "text": [],
    }
    for idx, value in enumerate(parts):
        text = value.strip()
        if not text:
            continue
        if re.fullmatch(r"\d{4,8}", text):
            buckets["po"].append(idx)
        if re.fullmatch(r"[A-Z]{4}\d{7,10}", text) or (
            re.fullmatch(r"[A-Z0-9]{8,15}", text)
            and any(ch.isalpha() for ch in text)
            and any(ch.isdigit() for ch in text)
        ):
            buckets["container"].append(idx)
        if re.search(MD_DATE_REGEX, text):
            buckets["md_date"].append(idx)
        if len(text) > 35:
            buckets["description"].append(idx)
        elif len(text) > 3:
            buckets["text"].append(idx)
    return buckets


def infer_paste_mapping(sample_line: str, template_headers: list[str]) -> dict[str, Any]:
    parts = sample_line.split("\t")
    if len(parts) < 2:
        raise ValueError("Sample line needs at least 2 tab-separated columns")
    buckets = _classify_columns(parts)
    used: set[int] = set()
    config: dict[str, Any] = {"determiner": "tab"}

    po_header = _find_header(template_headers, "P.O. No.", "PO", "P.O.No.")
    if po_header and buckets["po"]:
        col = buckets["po"][0]
        used.add(col)
        config[po_header] = [{"filed": "PO", "index": col, "ID": True}]

    container_header = _find_header(template_headers, "Container No.", "Container No")
    if container_header and buckets["container"]:
        col = next((c for c in buckets["container"] if c not in used), buckets["container"][0])
        used.add(col)
        config[container_header] = [{"filed": "Container#", "index": col}]

    wants_date = any(_norm_header(h) in {"mm", "dd", "yy", "receiving date"} for h in template_headers)
    if wants_date and buckets["md_date"]:
        col = buckets["md_date"][-1]
        if col not in used:
            used.add(col)
            mm_target = _find_header(template_headers, "MM") or "MM"
            dd_target = _find_header(template_headers, "DD") or "DD"
            recv_target = _find_header(template_headers, "Receiving Date") or "Receiving Date"
            config[mm_target] = [
                {"filed": "recv. date", "index": col, "regex": r"(\d{1,2})(?=\/\d{1,2})"}
            ]
            config[dd_target] = [
                {"filed": "recv. date", "index": col, "regex": r"(?:\d{1,2}/)(\d{1,2})"}
            ]
            config[recv_target] = [
                {"filed": "recv. date", "index": col, "regex": r"(\d{1,2}\/\d{1,2})"}
            ]

    product_header = _find_header(template_headers, "Product Description", "Product")
    if product_header and buckets["description"]:
        col = next((c for c in buckets["description"] if c not in used), None)
        if col is not None:
            used.add(col)
            config[product_header] = [{"filed": "Product", "index": col}]

    supplier_header = _find_header(template_headers, "Supplier")
    if supplier_header:
        col = next((c for c in buckets["text"] if c not in used), None)
        if col is not None:
            used.add(col)
            config[supplier_header] = [{"filed": "Supplier", "index": col}]

    if len(config) <= 1:
        raise ValueError("Could not infer any mapping from sample; edit YAML manually")
    return config


def infer_paste_mapping_yaml(sample_line: str, template_headers: list[str]) -> str:
    return config_to_yaml(infer_paste_mapping(sample_line, template_headers))
