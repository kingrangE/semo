"""Sejong-specific markup and URLs. No HTTP, filesystem, or database access."""

import json
import re
from datetime import date
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from semo.application import HtmlReader, MissingSnapshot
from semo.content import table_blocks
from semo.domain import CollectionBatch, digest, normalize

ROOT = "https://www.sejong.ac.kr"
CALENDAR = ROOT + "/kor/academics/academic-calendar.do"
BOARDS = [ROOT + "/kor/intro/notice1.do", ROOT + "/kor/intro/notice3.do"]


def extract(html, url, kind):
    soup = BeautifulSoup(html, "html.parser")
    if kind == "official":
        title = soup.select_one(".b-title")
        date = soup.select_one(".b-info .b-date")
        body = soup.select_one(".b-content-box")
        assets_root = soup.select_one(".board") or body
    else:
        title = soup.select_one("#ModuleEcoProgramView .title h4")
        date = None  # Application/event times are not publication timestamps.
        body = soup.select_one("#ModuleEcoProgramView .description")
        assets_root = soup.select_one("#ModuleEcoProgramView")
    if title is None or body is None:
        raise ValueError(
            "Expected public title/body not found; possible login page or changed markup"
        )
    images = []
    for node in assets_root.select("img[src], [style]"):
        src = node.get("src") if node.name == "img" else None
        if not src:
            match = re.search(
                r"background-image\s*:\s*url\(['\"]?([^)'\"]+)", node.get("style", "")
            )
            src = match[1] if match else None
        if src:
            images.append({"url": urljoin(url, src), "alt": node.get("alt", "")})
    attachments = []
    for anchor in assets_root.select("a[href]"):
        href = anchor["href"]
        if re.search(
            r"mode=download|/attachment/download/|\.(?:pdf|hwp|hwpx|docx?|xlsx?|zip)(?:[?#]|$)",
            href,
            re.I,
        ):
            attachments.append(
                {
                    "url": urljoin(url, href),
                    "name": normalize(anchor.get_text(" ", strip=True)),
                }
            )
    tables = []
    rendered_tables = {}
    for table in [
        node for node in body.select("table") if node.find_parent("table") is None
    ]:
        rows = []
        for row in table.select("tr"):
            if row.find_parent("table") is not table:
                continue
            rows.append(
                [
                    {
                        "text": normalize(cell.get_text(" ", strip=True)),
                        "rowspan": cell.get("rowspan", "1"),
                        "colspan": cell.get("colspan", "1"),
                    }
                    for cell in row.find_all(["td", "th"], recursive=False)
                ]
            )
        tables.append(rows)
        marker = f"__SEMO_TABLE_{len(tables)}__"
        first_row = table.find("tr")
        rendered_tables[marker] = table_blocks(
            rows, len(tables), bool(first_row and first_row.find("th"))
        )
        table.replace_with("\n\n" + marker + "\n\n")
    for node in body.select("script, style"):
        node.decompose()
    for br in body.find_all("br"):
        br.replace_with("\n\n")
    for block in body.find_all(
        ["p", "div", "li", "section", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"]
    ):
        block.append("\n\n")
    blocks = []
    for paragraph in re.split(r"\n\s*\n", body.get_text()):
        paragraph = normalize(paragraph)
        if paragraph:
            blocks.extend(rendered_tables.get(paragraph, [paragraph]))
    content = "\n\n".join(blocks)
    title_text = normalize(title.get_text(" ", strip=True))
    published = normalize(date.get_text(" ", strip=True)) if date else None
    return {
        "url": url,
        "title": title_text,
        "published_at": published,
        "content": content,
        "content_blocks": blocks,
        "tables": tables,
        "body_status": "text_extracted"
        if normalize(content)
        else "image_only"
        if images
        else "empty",
        "images": list({x["url"]: x for x in images}.values()),
        "attachments": list({x["url"]: x for x in attachments}.values()),
        "text_hash": digest(title_text, published, content),
        "hash_complete": not images and not attachments,
    }


def calendar_documents(html):
    soup = BeautifulSoup(html, "html.parser")
    selected = soup.select_one("#tabYear option[selected]")
    if selected is None:
        raise ValueError("Calendar year not found")
    year = int(selected["value"])
    documents = []
    for month in soup.select(".b-calendar-annual .b-month-wrap"):
        heading = normalize(
            month.select_one(".b-month-title").get_text(" ", strip=True)
        )
        explicit_year = re.search(r"(\d{4})년", heading)
        if explicit_year:
            year = int(explicit_year[1])
        for item in month.select(".b-schedule-item"):
            title = normalize(
                item.select_one(".b-schedule-content").get_text(" ", strip=True)
            )
            raw_date = normalize(
                item.select_one(".b-schedule-date").get_text(" ", strip=True)
            )
            match = re.fullmatch(
                r"(\d{2})\.(\d{2})(?:\s*~\s*(\d{2})\.(\d{2}))?", raw_date
            )
            if not match:
                raise ValueError(f"Unrecognized calendar date: {raw_date}")
            start = date(year, int(match[1]), int(match[2]))
            end = (
                date(year + (int(match[3]) < start.month), int(match[3]), int(match[4]))
                if match[3]
                else start
            )
            content = f"{start.isoformat()} ~ {end.isoformat()} | {title}"
            documents.append(
                {
                    "id": f"calendar:{start}:{end}:{title}",
                    "kind": "calendar",
                    "title": title,
                    "published_at": None,
                    "content": content,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "url": CALENDAR,
                    "content_hash": digest(title, None, content),
                }
            )
    if not documents:
        raise ValueError("Calendar has no events; keeping existing data")
    return list({doc["id"]: doc for doc in documents}.values())


def notice_document(html, url):
    doc = extract(html, url, "official")
    # Keep table structure in the hashed content; merged cells can change meaning.
    content = json.dumps(
        {"text": normalize(doc["content"]), "tables": doc["tables"]},
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "id": f"notice:{parse_qs(urlsplit(url).query)['articleNo'][0]}",
        "kind": "notice",
        "title": doc["title"],
        "published_at": doc["published_at"],
        "content": doc["content"],
        "content_blocks": doc["content_blocks"],
        "tables": doc["tables"],
        "body_status": doc["body_status"],
        "url": url,
        "has_images": bool(doc["images"]),
        "assets_collected": False,
        "content_hash": digest(doc["title"], doc["published_at"], content),
    }


class CalendarSource:
    def read(self, read_html: HtmlReader, previous: list[dict]) -> CollectionBatch:
        return CollectionBatch(
            documents=calendar_documents(read_html(CALENDAR)),
            replace_kinds={"calendar"},
        )


class NoticeSource:
    def __init__(self, pages: int = 1, sample_only: bool = False):
        if not 1 <= pages <= 10:
            raise ValueError("pages must be between 1 and 10")
        self.pages = pages
        self.sample_only = sample_only

    def read(self, read_html: HtmlReader, previous: list[dict]) -> CollectionBatch:
        urls = {}
        for board in BOARDS:
            for page in range(self.pages):
                html = read_html(f"{board}?article.offset={page * 10}&articleLimit=10")
                links = BeautifulSoup(html, "html.parser").select(
                    '.board a[href*="mode=view"]'
                )
                if not links:
                    raise ValueError(f"No notice links found: {board}")
                for link in links:
                    article = parse_qs(urlsplit(link["href"]).query).get(
                        "articleNo", [None]
                    )[0]
                    if article and article.isdigit():
                        urls[f"notice:{article}"] = (
                            f"{board}?mode=view&articleNo={article}"
                        )
        if not self.sample_only:
            # shortcut: recheck all stored notices, bound retention when daily runs grow too long.
            for old in previous:
                if old["kind"] == "notice":
                    urls.setdefault(old["id"], old["url"])
        batch = CollectionBatch()
        for url in urls.values():
            try:
                html = read_html(url)
            except MissingSnapshot:
                if not self.sample_only:
                    raise
                batch.skipped_urls.append(url)
                continue
            batch.documents.append(notice_document(html, url))
        return batch
