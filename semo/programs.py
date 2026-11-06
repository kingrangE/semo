"""Select recruitment candidates by verified application times, never event dates."""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
MAX_AGE = timedelta(hours=36)
NOTICE = "신청 기간에 포함되는 후보입니다. 개인별 자격·잔여 정원·변경 사항은 원문에서 확인하세요."


class ProgramCatalogUnavailable(RuntimeError):
    pass


def is_open_program_question(question: str) -> bool:
    compact = re.sub(r"\s+", "", question)
    return bool(
        re.search(r"활동|프로그램|비교과|취업|진로", compact)
        and re.search(r"지금|현재|오늘|신청가능|모집중|접수중|신청할수", compact)
        or re.search(r"(?:지금|오늘|현재).*(?:뭐|무엇).*할", compact)
    )


def open_programs(documents: list[dict], at: datetime) -> dict:
    if at.utcoffset() is None:
        raise ValueError("Reference time must include a timezone")
    items, fresh = [], 0
    for doc in documents:
        if doc.get("kind") != "program" or not all(
            isinstance(doc.get(key), str) and doc[key].strip()
            for key in ("id", "title", "source", "url", "target", "department")
        ):
            continue
        try:
            checked = datetime.fromisoformat(doc["checked_at"])
            if checked.utcoffset() is None or not timedelta(0) <= at - checked <= MAX_AGE:
                continue
            fresh += 1
            start = datetime.fromisoformat(doc["application_start"])
            end = datetime.fromisoformat(doc["application_end"])
            if start.utcoffset() is None or end.utcoffset() is None or end < start:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if start <= at <= end and doc.get("application_closed") is False:
            items.append(doc)
    items.sort(key=lambda d: (datetime.fromisoformat(d["application_end"]), d["id"]))
    return {
        "items": items[:20], "total": len(items), "as_of": at.isoformat(),
        "reason": None if items else "no_verified_open_programs" if fresh else "stale_or_missing_program_data",
        "notice": NOTICE,
    }


def program_hits(selection: dict) -> list[dict]:
    hits = []
    for doc in selection["items"]:
        # Structured evidence is enough to list candidates; full details remain in vector search.
        text = "\n".join([
            f"프로그램: {doc['title']}",
            f"신청기간: {doc['application_start']} ~ {doc['application_end']}",
            f"운영기간(신청기간과 다름): {doc.get('event_start')} ~ {doc.get('event_end')}",
            f"대상: {doc.get('target', '원문 확인 필요')}; 학과: {doc.get('department', '원문 확인 필요')}",
            f"분류: {doc.get('category', '')}",
            f"수집 확인 시각: {doc['checked_at']}; 조회 기준 시각: {selection['as_of']}",
            f"후보 총 {selection['total']}건 중 마감이 빠른 최대 20건을 제공했습니다.",
            NOTICE,
            "참여 자격과 신청 방법의 원문 근거(상단 요약과 다르면 본문 제한도 확인):",
            doc.get("content", "")[:6000],
        ])
        hits.append({"text": text, "metadata": {
            "document_id": doc["id"], "title": doc["title"], "url": doc["url"],
            "published_at": doc.get("published_at") or "", "kind": "program",
        }})
    return hits
