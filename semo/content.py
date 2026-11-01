"""Readable table rows and paragraph-sized search chunks; no HTML or SDK dependency."""

import textwrap

from semo.domain import normalize


def table_blocks(
    rows: list[list[dict]], number: int, has_header: bool = False
) -> list[str]:
    grid = {}
    for row_number, cells in enumerate(rows):
        column = 0
        for cell in cells:
            while (row_number, column) in grid:
                column += 1
            height, width = int(cell["rowspan"]), int(cell["colspan"])
            if not 1 <= height <= 1000 or not 1 <= width <= 100:
                raise ValueError("Unsupported table span")
            origin = (row_number, column)
            for row in range(row_number, min(row_number + height, len(rows))):
                for col in range(column, column + width):
                    grid[row, col] = (origin, normalize(cell["text"]))
                    if len(grid) > 100000:
                        raise ValueError("Table exceeds supported size")
            column += width
    grouped_rows = {}
    for (row, column), cell in sorted(grid.items()):
        grouped_rows.setdefault(row, []).append(cell)
    rendered = []
    for row in range(len(rows)):
        seen, values = set(), []
        for origin, value in grouped_rows.get(row, []):
            if origin not in seen:
                seen.add(origin)
                values.append(value)
        rendered.append(" | ".join(values))
    header = rendered[0] if has_header and rendered else ""
    return [
        f"[표 {number}] {header + ' — ' if header else ''}{row}"
        for row in rendered[1 if header else 0 :]
        if row.strip(" |")
    ]


def paragraph_chunks(blocks: list[str]) -> list[str]:
    chunks, current = [], ""
    for block in blocks:
        # Split oversized paragraphs at word boundaries; ordinary rows remain intact.
        for part in textwrap.wrap(normalize(block), width=1600, break_on_hyphens=False):
            if current and len(current) + len(part) + 2 > 1600:
                chunks.append(current)
                current = ""
            current = current + "\n\n" + part if current else part
    if current:
        chunks.append(current)
    return chunks
