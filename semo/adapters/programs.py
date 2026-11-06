"""Public program markup. Application and event periods are kept separate."""

import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from semo.adapters.http import SourceBlocked, SourceUnavailable
from semo.adapters.sejong import extract
from semo.application import MissingSnapshot
from semo.domain import CollectionBatch, digest, normalize

ROOTS = {"do": "https://do.sejong.ac.kr", "udream": "https://udream.sejong.ac.kr"}
LISTINGS = {"do": ROOTS["do"] + "/ko/program/all", "udream": ROOTS["udream"] + "/Main/default.aspx"}
UDREAM_PROGRAMS = ROOTS["udream"] + "/Career/CareerTask/ProgramList.aspx"


def time_range(element):
    times = element.select("time[datetime]") if element else []
    if len(times) != 2:
        return None, None
    start, end = (datetime.fromisoformat(t["datetime"]) for t in times)
    if start.utcoffset() is None or end.utcoffset() is None or end < start:
        raise ValueError("Invalid program time range")
    return start.isoformat(), end.isoformat()


def finish(doc):
    fields = {key: value for key, value in doc.items() if key not in ("content", "content_blocks")}
    doc["content_hash"] = digest(
        doc["title"], doc["published_at"],
        doc["content"] + "\n" + json.dumps(fields, ensure_ascii=False, sort_keys=True),
    )
    return doc


def dodream_documents(html: str, url: str) -> list[dict]:
    base = extract(html, url, "program")
    soup = BeautifulSoup(html, "html.parser")
    view = soup.select_one("#ModuleEcoProgramView")
    item = view.select_one("[data-pidx]")
    if item is None or not item["data-pidx"].isdigit():
        raise ValueError("Program ID missing")
    target = view.select_one(".title li.target span")
    department = view.select_one(".title li.department span")
    category = view.select_one(".info .category")
    rows = view.select("#ModuleEcoProgramTopicForm li.tbody")
    if not rows:
        raise ValueError("Program application rows missing; keep previous data")
    documents = []
    for row in rows:
        topic = row.select_one('input[name="tidx[]"]')
        if topic is None or not topic.get("value", "").isdigit():
            raise ValueError("Program session ID missing")
        start, end = time_range(row.select_one(".date"))
        event_start, event_end = time_range(row.select_one(".title"))
        status = normalize(row.select_one(".status").get_text(" ", strip=True)) if row.select_one(".status") else ""
        capacity = re.search(r"(\d+)\s*명?\s*/\s*(\d+)\s*명", status)
        closed = row.get("data-open") == "0" or bool(re.search(r"접수마감|모집마감|신청마감|취소|폐강", status.replace(" ", "")))
        if capacity and int(capacity[1]) >= int(capacity[2]):
            closed = True
        label = row.select_one(".title b")
        title = normalize(label.get_text(" ", strip=True)) if label else base["title"]
        target_text = normalize(target.get_text(" ", strip=True)) if target else "원문 확인 필요"
        department_text = normalize(department.get_text(" ", strip=True)) if department else "원문 확인 필요"
        header = [
            f"프로그램: {base['title']} / {title}",
            f"신청기간: {start or '확인 불가'} ~ {end or '확인 불가'}",
            f"운영기간: {event_start or '확인 불가'} ~ {event_end or '확인 불가'}",
            f"모집대상: {target_text}; 학과: {department_text}",
            f"신청현황(수집 시점): {status}; 마감/정원 제한 확인: {closed}",
            "개인별 신청 자격과 남은 정원은 원문에서 확인해야 합니다.",
        ]
        blocks = header + base["content_blocks"]
        documents.append(finish({
            "id": f"program:do:{item['data-pidx']}:{topic['value']}",
            "kind": "program", "source": "do", "title": title,
            "published_at": None, "url": url,
            "content": "\n\n".join(blocks), "content_blocks": blocks,
            "body_status": base["body_status"], "tables": base["tables"],
            "has_images": bool(base["images"]), "assets_collected": False,
            "application_start": start, "application_end": end,
            "event_start": event_start, "event_end": event_end,
            "application_closed": closed, "target": target_text,
            "department": department_text,
            "category": normalize(category.get_text(" ", strip=True)) if category else "",
        }))
    return documents


def udream_documents(html: str) -> list[dict]:
    """Only visible listing evidence; hidden/commented templates are not documents."""
    soup = BeautifulSoup(html, "html.parser")
    documents = {}
    for anchor in soup.select('a[href*="pgdx="], a[href*="rcdx="]'):
        url = urljoin(ROOTS["udream"], anchor["href"])
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != urlsplit(ROOTS["udream"]).netloc:
            continue
        query = parse_qs(parts.query)
        key = "pgdx" if "pgdx" in query else "rcdx"
        identifier = query[key][0]
        if not re.fullmatch(r"[A-Za-z0-9]+", identifier):
            continue
        title_node = anchor.select_one("p, h4")
        if title_node is None:
            continue
        title = normalize(title_node.get_text(" ", strip=True))
        evidence = normalize(anchor.get_text(" ", strip=True))
        # The list's single date is not evidence for a complete application window.
        blocks = ["유드림 공개 목록 요약(상세 본문 미수집)", evidence,
                  "신청 시작·마감 시각과 개인 자격은 확인되지 않았습니다. 원문에서 확인하세요."]
        documents[f"{key}:{identifier}"] = finish({
            "id": f"program:udream:{key}:{identifier}",
            "kind": "program", "source": "udream", "title": title,
            "published_at": None, "url": url,
            "content": "\n\n".join(blocks), "content_blocks": blocks,
            "body_status": "listing_only", "assets_collected": False,
            "application_start": None, "application_end": None,
            "event_start": None, "event_end": None,
            "application_closed": False, "category": "취업·진로",
            "target": "원문 확인 필요", "department": "원문 확인 필요",
        })
    if not documents:
        raise ValueError("No visible UDream program/recruitment links; keep previous data")
    return list(documents.values())


def udream_program_document(html: str, url: str) -> dict:
    if "오류입니다." in html and 'id="Title"' not in html:
        raise SourceUnavailable("UDream returned an error page")
    base = extract(html, url, "udream")
    soup = BeautifulSoup(html, "html.parser")
    period, target, status = (soup.select_one(selector) for selector in ("#rsDate", "#target", "#dDay"))
    if period is None or target is None or status is None:
        raise ValueError("UDream application fields missing; keep previous data")
    dates = re.findall(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", period.get_text(" ", strip=True))
    external_application = "온라인 신청불가" in period.get_text()
    if len(dates) != 2 and not external_application:
        raise ValueError("UDream application times missing; keep previous data")
    from zoneinfo import ZoneInfo

    start, end = (datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("Asia/Seoul")).isoformat() for value in dates) if len(dates) == 2 else (None, None)
    if start and end < start:
        raise ValueError("UDream application period is reversed")
    target_text = normalize(target.get_text(" ", strip=True))
    status_text = normalize(status.get_text(" ", strip=True))
    identifier = parse_qs(urlsplit(url).query)["pgdx"][0]
    blocks = [f"신청기간: {start or '확인 불가'} ~ {end or '확인 불가'}", f"참여대상: {target_text}",
              f"접수상태(수집 시점): {status_text}"] + base["content_blocks"]
    return finish({
        "id": f"program:udream:pgdx:{identifier}", "kind": "program", "source": "udream",
        "title": base["title"], "published_at": None, "url": url,
        "content": "\n\n".join(blocks), "content_blocks": blocks,
        "body_status": base["body_status"], "tables": base["tables"],
        "has_images": bool(base["images"]), "assets_collected": False,
        "application_start": start, "application_end": end,
        "event_start": None, "event_end": None,
        "application_closed": status_text != "진행중",
        "category": "취업·진로", "target": target_text,
        "department": target_text,
    })


class ProgramSource:
    def __init__(self, site: str, pages: int = 1, sample_only: bool = False):
        if site not in ROOTS or not 1 <= pages <= 10:
            raise ValueError("Unknown program source or invalid page count")
        self.site, self.pages, self.sample_only = site, pages, sample_only

    def read(self, read_html, previous):
        batch = CollectionBatch()
        try:
            if self.site == "udream":
                batch.documents = udream_documents(read_html(LISTINGS[self.site]))
                listing = BeautifulSoup(read_html(UDREAM_PROGRAMS), "html.parser")
                identifiers = list(dict.fromkeys(
                    match[1] for node in listing.select("#programZone li[onclick]")
                    if (match := re.fullmatch(r"(?:javascript:)?goView\('([A-Za-z0-9]+)'\);?", node["onclick"].strip()))
                ))
                if not identifiers:
                    raise ValueError("UDream program detail links missing; keep previous data")
                urls = [ROOTS["udream"] + "/community/Program/programView.aspx?pgdx=" + identifier for identifier in identifiers]
                if not self.sample_only:
                    urls = list(dict.fromkeys(urls + [d["url"] for d in previous
                        if d.get("source") == "udream" and d.get("body_status") != "listing_only"
                        and "/community/Program/programView.aspx?pgdx=" in d.get("url", "")]))
                for url in urls:
                    try:
                        doc = udream_program_document(read_html(url), url)
                        batch.documents = [d for d in batch.documents if d["id"] != doc["id"]]
                        batch.documents.append(doc)
                    except MissingSnapshot:
                        if not self.sample_only:
                            raise
                        batch.skipped_urls.append(url)
                    except SourceUnavailable:
                        batch.skipped_urls.append(url)
            else:
                urls = set()
                for page in range(1, self.pages + 1):
                    url = LISTINGS[self.site] + (f"/list/0/{page}" if page > 1 else "")
                    soup = BeautifulSoup(read_html(url), "html.parser")
                    for a in soup.select('a[href*="/view/"]'):
                        path = urlsplit(urljoin(url, a["href"]))
                        match = re.fullmatch(r"/ko/program/[^/]+/view/(\d+)(?:/description)?", path.path)
                        if path.scheme == "https" and path.netloc == urlsplit(ROOTS[self.site]).netloc and match:
                            urls.add(LISTINGS[self.site] + "/view/" + match[1])
                    if not urls:
                        raise ValueError("No program links; keep previous data")
                if not self.sample_only:
                    urls.update(d["url"] for d in previous if d.get("source") == "do" and d["kind"] == "program")
                for url in sorted(urls):
                    try:
                        batch.documents.extend(dodream_documents(read_html(url), url))
                    except MissingSnapshot:
                        if not self.sample_only:
                            raise
                        batch.skipped_urls.append(url)
                    except SourceUnavailable:
                        batch.skipped_urls.append(url)
            batch.source_status[self.site] = "partial" if batch.skipped_urls else "collected"
        except SourceBlocked:
            return CollectionBatch(source_status={self.site: "blocked_by_robots"})
        except SourceUnavailable:
            return CollectionBatch(source_status={self.site: "source_unavailable"})
        except MissingSnapshot as error:
            if not self.sample_only:
                raise
            batch.skipped_urls.append(error.args[0])
            batch.source_status[self.site] = "missing_sample"
        return batch
