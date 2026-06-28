"""
chunker.py — Strategic warranty-aware chunking (tiktoken + layout detection).

Strategies by content type:
  - vehicle_export: coverage tables (U-codes, Months/Miles rows) — one row or
    packed row groups per chunk; VIN/chassis header prepended when known
  - policy_section: numbered clauses (e.g. "23. GLASS:") — one section per chunk
    when possible, else recursive split inside the section only
  - prose: paragraph / sentence recursive split (default)

Config: 700 target tokens, 1024 max, 50 min, 100 overlap (~15%).
"""

from __future__ import annotations

import logging
import re

import tiktoken

logger = logging.getLogger("strategic_chunker")

# Coverage claim rows: U050 | Driveline: ... | 36 Months/350,000 Miles
COVERAGE_ROW_RE = re.compile(
    r"^(?:U\d{3,4}[A-Z]?|D\d{4}|ET\d{3}|E\d{3,4}|G\d{2,3}|HAC\d{2,3}|TOW\d+|Z\d{3,4})\s*[\|]",
    re.MULTILINE | re.IGNORECASE,
)
# Lines starting with any known code prefix (fallback for non-pipe OCR output)
_ANY_CODE_LINE_RE = re.compile(
    r"^(?:U\d{3,4}[A-Z]?|D\d{4}|ET\d{3}|E\d{3,4}|G\d{2,3}|HAC\d{2,3}|TOW\d+|Z\d{3,4})\b",
    re.IGNORECASE,
)
# Alternate table lines with embedded months/miles
COVERAGE_LINE_RE = re.compile(
    r"\d+\s*Months\s*/\s*[\d,]+\s*Miles",
    re.IGNORECASE,
)
# Numbered warranty clauses: "23. GLASS:" or "4.2 Powertrain"
NUMBERED_SECTION_RE = re.compile(
    r"^\d{1,2}(?:\.\d+)?\.\s+[A-Z]",
    re.MULTILINE,
)
VEHICLE_HEADER_RE = re.compile(
    r"\b(VIN|Chassis\s*ID|Brand|Marketing\s*type|Reg\.\s*No)\b",
    re.IGNORECASE,
)

# --- VIN / Chassis parsing (used by pipeline_orchestrator for payload enrichment) ---

_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
_CHASSIS_RE = re.compile(
    r"(?:Chassis|Unit)\s*(?:ID)?\s*(?:NR?\.?\s*)(\d{5,6})",
    re.IGNORECASE,
)


def parse_vin_chassis_from_text(text: str) -> dict:
    """Extract VIN and chassis ID from raw OCR text using regex.

    Returns dict with keys 'vin' (str|None) and 'chassis_id' (str|None).
    VIN: any 17-char alphanumeric (excluding I, O, Q per ISO 3779).
    Chassis: 5-6 digit number following 'Chassis ID' or 'Unit' label.
    """
    result: dict = {"vin": None, "chassis_id": None}

    vin_match = _VIN_RE.search(text[:3000])  # VIN typically in first pages
    if vin_match:
        result["vin"] = vin_match.group(1)

    chassis_match = _CHASSIS_RE.search(text[:3000])
    if chassis_match:
        result["chassis_id"] = chassis_match.group(1)

    return result


class TiktokenChunker:
    SEPARATORS = ["\n\n", "\n", ". ", ", ", " "]

    def __init__(
        self,
        target_tokens: int = 700,
        max_tokens: int = 1024,
        min_tokens: int = 50,
        overlap_tokens: int = 100,
        table_target_tokens: int = 550,
        max_rows_per_chunk: int = 12,
    ):
        self.encoder = tiktoken.get_encoding("cl100k_base")
        self.target = target_tokens
        self.table_target = table_target_tokens
        self.max_rows = max_rows_per_chunk
        self.max = max_tokens
        self.min = min_tokens
        self.overlap = overlap_tokens

    def count_tokens(self, text: str) -> int:
        return len(self.encoder.encode(text))

    def chunk_pages(self, pages: list[dict]) -> list[dict]:
        """
        Chunk OCR pages using layout-aware strategy per page.

        Returns chunk dicts with chunkIndex, pageNumber, sectionHeading,
        chunkText, tokenCount, chunkType, coverageCodes (optional).
        """
        vehicle_header = _extract_vehicle_header(pages)
        all_chunks: list[dict] = []
        chunk_idx = 0

        for page_item in pages:
            page_num = int(page_item.get("page", 1))
            text = (page_item.get("text") or "").strip()
            if not text or self.count_tokens(text) < self.min:
                continue

            mode = _detect_page_mode(text)
            if mode == "table":
                page_chunks = self._chunk_table_page(
                    text, page_num, vehicle_header
                )
            elif mode == "policy":
                page_chunks = self._chunk_policy_page(text, page_num)
            else:
                page_chunks = self._chunk_prose_page(text, page_num)

            for c in page_chunks:
                c["chunkIndex"] = chunk_idx
                chunk_idx += 1
                all_chunks.append(c)

        logger.info(
            "Strategic chunk: %d pages → %d chunks (types: %s)",
            len(pages),
            len(all_chunks),
            _summarize_types(all_chunks),
        )
        return all_chunks

    # ── Table / vehicle export pages ────────────────────────────

    def _chunk_table_page(
        self, text: str, page_num: int, vehicle_header: str
    ) -> list[dict]:
        rows = _extract_coverage_rows(text)
        if not rows:
            return self._chunk_prose_page(text, page_num, chunk_type="prose")

        prefix = ""
        if vehicle_header and VEHICLE_HEADER_RE.search(vehicle_header):
            prefix = f"[Vehicle context]\n{vehicle_header.strip()}\n\n"

        units: list[str] = []
        for row in rows:
            units.append(row)

        packed = self._pack_units(
            units,
            target=self.table_target,
            prefix=prefix,
            joiner="\n",
        )

        chunks: list[dict] = []
        for block in packed:
            codes = _extract_u_codes(block)
            heading = codes[0] if codes else _infer_heading(block)
            chunks.append(
                _make_chunk(
                    block,
                    page_num,
                    heading=heading,
                    chunk_type="coverage_table",
                    coverage_codes=codes,
                )
            )
        return chunks

    # ── Numbered policy sections ────────────────────────────────

    def _chunk_policy_page(self, text: str, page_num: int) -> list[dict]:
        sections = _split_numbered_sections(text)
        if len(sections) <= 1:
            return self._chunk_prose_page(text, page_num, chunk_type="policy_prose")

        sections = _merge_small_sections(sections, self.min, self.target, self.count_tokens)

        chunks: list[dict] = []
        for heading, body in sections:
            body = body.strip()
            if not body:
                continue
            section_text = f"{heading}\n{body}" if heading else body
            token_count = self.count_tokens(section_text)

            if token_count <= self.target:
                if token_count >= self.min:
                    chunks.append(
                        _make_chunk(
                            section_text,
                            page_num,
                            heading=heading or _infer_heading(section_text),
                            chunk_type="policy_section",
                        )
                    )
                continue

            # Section too large — split inside section only (keep heading on first)
            parts = self._recursive_split(body)
            parts = self._add_overlap(parts)
            for i, part in enumerate(parts):
                part_text = f"{heading}\n{part}" if i == 0 and heading else part
                if self.count_tokens(part_text) >= self.min:
                    chunks.append(
                        _make_chunk(
                            part_text,
                            page_num,
                            heading=heading or _infer_heading(part_text),
                            chunk_type="policy_section",
                        )
                    )
        return chunks

    # ── Generic prose ───────────────────────────────────────────

    def _chunk_prose_page(
        self, text: str, page_num: int, chunk_type: str = "prose"
    ) -> list[dict]:
        raw = self._recursive_split(text)
        overlapped = self._add_overlap(raw)
        chunks: list[dict] = []
        for chunk_text in overlapped:
            if self.count_tokens(chunk_text) < self.min:
                continue
            chunks.append(
                _make_chunk(
                    chunk_text.strip(),
                    page_num,
                    heading=_infer_heading(chunk_text),
                    chunk_type=chunk_type,
                )
            )
        return chunks

    # ── Pack row/list units into token-bounded chunks ─────────────

    def _pack_units(
        self,
        units: list[str],
        *,
        target: int,
        prefix: str = "",
        joiner: str = "\n",
        max_units: int | None = None,
    ) -> list[str]:
        if not units:
            return []

        max_units = max_units or self.max_rows
        blocks: list[str] = []
        batch: list[str] = []

        def flush():
            if not batch:
                return
            body = joiner.join(batch)
            text = f"{prefix}{body}" if prefix else body
            if self.count_tokens(text) >= self.min:
                blocks.append(text.strip())
            batch.clear()

        for unit in units:
            if len(batch) >= max_units:
                flush()
            trial = joiner.join(batch + [unit])
            trial_text = f"{prefix}{trial}" if prefix else trial
            if batch and self.count_tokens(trial_text) > target:
                flush()
            batch.append(unit)

        flush()

        # Oversized single unit — fall back to recursive split
        final: list[str] = []
        for block in blocks:
            if self.count_tokens(block) > self.max:
                final.extend(self._recursive_split(block))
            else:
                final.append(block)
        return final

    # ── Recursive split (unchanged core) ────────────────────────

    def _recursive_split(self, text: str) -> list[str]:
        token_count = self.count_tokens(text)
        if token_count <= self.target:
            return [text] if token_count >= self.min else []

        sep = self._find_separator(text)
        if sep is None:
            tokens = self.encoder.encode(text)
            return [self.encoder.decode(tokens[: self.target])]

        parts = text.split(sep)
        chunks: list[str] = []
        buffer: list[str] = []
        buffer_tokens = 0

        for part in parts:
            part_tokens = self.count_tokens(part)
            would_be = buffer_tokens + part_tokens + (
                self.count_tokens(sep) if buffer else 0
            )

            if would_be > self.target and buffer:
                chunk_text = sep.join(buffer)
                if self.count_tokens(chunk_text) > self.max:
                    chunks.extend(self._recursive_split(chunk_text))
                else:
                    chunks.append(chunk_text)
                buffer = []
                buffer_tokens = 0

            if part_tokens > self.target:
                if buffer:
                    chunks.append(sep.join(buffer))
                    buffer = []
                    buffer_tokens = 0
                chunks.extend(self._recursive_split(part))
            else:
                buffer.append(part)
                buffer_tokens = self.count_tokens(sep.join(buffer))

        if buffer:
            remainder = sep.join(buffer)
            if self.count_tokens(remainder) >= self.min:
                chunks.append(remainder)
            elif chunks:
                merged = chunks[-1] + sep + remainder
                if self.count_tokens(merged) <= self.max:
                    chunks[-1] = merged
                else:
                    chunks.append(remainder)

        return chunks

    def _add_overlap(self, chunks: list[str]) -> list[str]:
        if len(chunks) <= 1 or self.overlap <= 0:
            return chunks

        result: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tokens = self.encoder.encode(chunks[i - 1])
            overlap_text = self.encoder.decode(prev_tokens[-self.overlap :]).strip()
            merged = overlap_text + "\n" + chunks[i]
            result.append(merged if self.count_tokens(merged) <= self.max else chunks[i])
        return result

    def _find_separator(self, text: str) -> str | None:
        for sep in self.SEPARATORS:
            if sep in text:
                return sep
        return None


# ── Helpers ─────────────────────────────────────────────────────


def _make_chunk(
    text: str,
    page_num: int,
    *,
    heading: str,
    chunk_type: str,
    coverage_codes: list[str] | None = None,
) -> dict:
    enc = tiktoken.get_encoding("cl100k_base")
    return {
        "pageNumber": page_num,
        "sectionHeading": (heading or "Unknown")[:120],
        "chunkText": text.strip(),
        "tokenCount": len(enc.encode(text)),
        "chunkType": chunk_type,
        "coverageCodes": coverage_codes or [],
    }


def _detect_page_mode(text: str) -> str:
    """Classify page layout for chunk strategy selection."""
    coverage_rows = len(COVERAGE_ROW_RE.findall(text))
    coverage_lines = sum(1 for ln in text.splitlines() if COVERAGE_LINE_RE.search(ln))
    numbered = len(NUMBERED_SECTION_RE.findall(text))

    if "Coverage Information" in text and (coverage_rows >= 1 or coverage_lines >= 2):
        return "table"
    if coverage_rows >= 2 or (coverage_rows >= 1 and coverage_lines >= 3):
        return "table"
    if numbered >= 2:
        return "policy"
    if numbered >= 1 and coverage_rows == 0 and "LIMITATION" in text.upper():
        return "policy"
    return "prose"


def _extract_coverage_rows(text: str) -> list[str]:
    """Pull intact coverage table rows from OCR text."""
    rows: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if COVERAGE_ROW_RE.match(line) or _ANY_CODE_LINE_RE.match(line) or (
            COVERAGE_LINE_RE.search(line) and "|" in line
        ):
            rows.append(line)
        elif rows and COVERAGE_LINE_RE.search(line) and not NUMBERED_SECTION_RE.match(line):
            # continuation line glued to previous row
            rows[-1] = rows[-1] + " " + line
    return rows


def _merge_small_sections(
    sections: list[tuple[str, str]],
    min_tokens: int,
    target: int,
    count_tokens,
) -> list[tuple[str, str]]:
    """Combine adjacent short clauses until each chunk meets min_tokens."""
    if not sections:
        return sections

    merged: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush():
        if not buf:
            return
        text = "\n\n".join(buf)
        merged.append((_infer_heading(text), text))

    for heading, body in sections:
        block = f"{heading}\n{body}".strip() if heading else (body or "").strip()
        if not block:
            continue
        if not buf:
            buf = [block]
            continue
        trial = "\n\n".join(buf + [block])
        if count_tokens(trial) > target and count_tokens("\n\n".join(buf)) >= min_tokens:
            flush()
            buf = [block]
        else:
            buf.append(block)

    flush()

    if not merged:
        all_text = "\n\n".join(
            f"{h}\n{b}".strip() if h else b for h, b in sections if (h or b)
        ).strip()
        if all_text:
            return [(_infer_heading(all_text), all_text)]
    return merged


def _split_numbered_sections(text: str) -> list[tuple[str, str]]:
    """Split policy text into (heading, body) per numbered clause."""
    parts = re.split(r"(?m)(?=^\d{1,2}(?:\.\d+)?\.\s+[A-Z])", text)
    sections: list[tuple[str, str]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.splitlines()
        first = lines[0].strip()
        if NUMBERED_SECTION_RE.match(first):
            heading = first[:120]
            body = "\n".join(lines[1:]).strip()
            sections.append((heading, body or part))
        elif sections:
            # preamble before first numbered item
            sections.append(("", part))
        else:
            sections.append(("", part))
    return sections


def _extract_vehicle_header(pages: list[dict]) -> str:
    """Collect VIN / chassis / brand block from early pages (vehicle exports)."""
    lines: list[str] = []
    for page in pages[:3]:
        text = page.get("text") or ""
        if not VEHICLE_HEADER_RE.search(text) and "Coverage Information" not in text:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if VEHICLE_HEADER_RE.search(line) or line.startswith("Brand"):
                lines.append(line)
            elif lines and COVERAGE_ROW_RE.match(line):
                break
            elif lines and len(lines) < 20 and len(line) < 120:
                lines.append(line)
    # De-duplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for ln in lines:
        if ln not in seen:
            seen.add(ln)
            unique.append(ln)
    return "\n".join(unique[:18])


def _extract_u_codes(text: str) -> list[str]:
    """Extract all warranty coverage codes (U, D, ET, E, G, HAC, TOW, Z)."""
    patterns = [
        r"\bU\d{3,4}[A-Z]?\b",
        r"\bD\d{4}\b",
        r"\bET\d{3}\b",
        r"\bE\d{3,4}\b",
        r"\bG\d{2,3}\b",
        r"\bHAC\d{2,3}\b",
        r"\bTOW\d+\b",
        r"\bZ\d{3,4}\b",
    ]
    codes: set[str] = set()
    for pat in patterns:
        codes.update(re.findall(pat, text, flags=re.IGNORECASE))
    return sorted(codes, key=str.upper)


def _infer_heading(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines[:8]:
        if len(line) > 100:
            continue
        if NUMBERED_SECTION_RE.match(line):
            return line[:120]
        if COVERAGE_ROW_RE.match(line):
            return line.split("|", 2)[1].strip()[:120] if "|" in line else line[:120]
        letters = sum(1 for c in line if c.isalpha())
        upper = sum(1 for c in line if c.isupper())
        if letters >= 4 and upper / max(letters, 1) >= 0.6:
            return line[:120]
    return lines[0][:80] if lines else "Unknown"


def _summarize_types(chunks: list[dict]) -> str:
    counts: dict[str, int] = {}
    for c in chunks:
        t = c.get("chunkType", "prose")
        counts[t] = counts.get(t, 0) + 1
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
