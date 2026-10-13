"""Delimiter-detecting, quote-aware parsing of a pasted/uploaded position sheet."""
import csv
import io
from typing import List, Tuple

_CANDIDATE_DELIMITERS = ["\t", ",", ";"]


def detect_delimiter(text: str) -> str:
    first_line = text.splitlines()[0] if text.splitlines() else ""
    best = _CANDIDATE_DELIMITERS[0]
    best_count = -1
    for d in _CANDIDATE_DELIMITERS:
        count = first_line.count(d)
        if count > best_count:
            best_count = count
            best = d
    return best


def split_delimited(text: str, delimiter: str) -> List[List[str]]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [row for row in reader if any(cell.strip() for cell in row)]


def parse_pasted_text(text: str, has_header: bool) -> Tuple[List[str], List[List[str]]]:
    delimiter = detect_delimiter(text)
    rows = split_delimited(text, delimiter)
    if not rows:
        return [], []
    if has_header:
        headers = rows[0]
        data_rows = rows[1:]
    else:
        headers = [f"Column {i + 1}" for i in range(len(rows[0]))]
        data_rows = rows
    return headers, data_rows
