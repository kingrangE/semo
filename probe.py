"""Small public-page feasibility probe; no login, AI calls, or vector ingestion."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from semo.adapters.http import Robots, fetch
from semo.adapters.sejong import extract
from semo.domain import normalize

ROOTS = [
    "https://www.sejong.ac.kr",
    "https://do.sejong.ac.kr",
    "https://udream.sejong.ac.kr",
]
TARGETS = ["/kor/intro/notice1.do", "/ko/program/all", "/Main/default.aspx"]


def live(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "sites": []}
    for index, (root, path) in enumerate(zip(ROOTS, TARGETS)):
        robot_file = output / f"robots-{index}.txt"
        robot_fetch = fetch(root + "/robots.txt", robot_file)
        policy = Robots(
            robot_file.read_text(errors="replace") if robot_fetch["ok"] else ""
        )
        site = {
            "root": root,
            "robots": robot_fetch,
            "rules": policy.rules,
            "crawl_delay": policy.delay,
            "target": root + path,
            "requests": [],
            "documents": [],
        }
        report["sites"].append(site)
        if not robot_fetch["ok"] or not policy.allowed(root + path):
            site["status"] = (
                "blocked_by_robots" if policy.valid else "robots_unavailable"
            )
            continue
        time.sleep(max(policy.delay, 1))
        listing = output / f"listing-{index}.html"
        response = fetch(root + path, listing)
        site["requests"].append(response)
        if not response["ok"]:
            site["status"] = "fetch_failed"
            continue
        soup = BeautifulSoup(listing.read_text(errors="replace"), "html.parser")
        # shortcut: only the official-board adapter is live-tested, add adapters after source access is agreed.
        if index != 0:
            site["status"] = "adapter_not_implemented"
            continue
        links = list(
            dict.fromkeys(
                urljoin(root + path, a["href"])
                for a in soup.select('.board a[href*="mode=view"]')
            )
        )
        site["discovered_links"] = links
        for number, url in enumerate(links[:3]):
            if urlsplit(url).netloc != urlsplit(root).netloc or not policy.allowed(url):
                continue
            time.sleep(max(policy.delay, 1))
            file = output / f"detail-{index}-{number}.html"
            detail = fetch(url, file)
            site["requests"].append(detail)
            if detail["ok"]:
                try:
                    document = extract(
                        file.read_text(errors="replace"), url, "official"
                    )
                    for asset in document["images"] + document["attachments"]:
                        asset["robots_allowed"] = urlsplit(
                            asset["url"]
                        ).netloc == urlsplit(root).netloc and policy.allowed(
                            asset["url"]
                        )
                        asset["download_status"] = (
                            "not_tested"
                            if asset["robots_allowed"]
                            else "blocked_by_robots"
                        )
                    site["documents"].append(document)
                except ValueError as error:
                    detail["extraction_error"] = str(error)
        site["status"] = (
            "public_html_extracted" if site["documents"] else "no_documents_extracted"
        )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    for site in report["sites"]:
        print(
            site["root"],
            site["status"],
            f"documents={len(site['documents'])}",
            flush=True,
        )


def replay(samples, output):
    """Inspect saved feasibility samples without making any network requests."""
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "mode": "offline_saved_samples",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Initial samples were fetched before robots review. No additional restricted requests were made after review.",
        "sites": [],
        "documents": [],
    }
    for index, name in enumerate(["www", "do", "udream"]):
        policy = Robots((samples / f"{name}-robots.txt").read_text())
        site = {
            "root": ROOTS[index],
            "target": ROOTS[index] + TARGETS[index],
            "robots_allowed": policy.allowed(ROOTS[index] + TARGETS[index]),
            "crawl_delay": policy.delay,
            "robots_file": str(samples / f"{name}-robots.txt"),
        }
        report["sites"].append(site)
    for file, url, kind in [
        (
            "main_detail.html",
            ROOTS[0] + "/kor/intro/notice1.do?mode=view&articleNo=895312",
            "official",
        ),
        (
            "main_recruit.html",
            ROOTS[0] + "/kor/intro/notice1.do?mode=view&articleNo=894982",
            "official",
        ),
        (
            "main_construction.html",
            ROOTS[0] + "/kor/intro/notice1.do?mode=view&articleNo=893803",
            "official",
        ),
        ("do_detail.html", ROOTS[1] + "/ko/program/all/view/4395", "program"),
    ]:
        doc = extract((samples / file).read_text(), url, kind)
        site_index = 0 if kind == "official" else 1
        policy = Robots(Path(report["sites"][site_index]["robots_file"]).read_text())
        doc["robots_allowed"] = policy.allowed(url)
        doc["html_file"] = str(samples / file)
        for asset in doc["images"] + doc["attachments"]:
            asset["robots_allowed"] = urlsplit(asset["url"]).netloc == urlsplit(
                url
            ).netloc and policy.allowed(asset["url"])
            asset["download_status"] = (
                "not_tested" if asset["robots_allowed"] else "blocked_by_robots"
            )
        report["documents"].append(doc)
    listing = BeautifulSoup((samples / "udream_main.html").read_text(), "html.parser")
    report["udream_listing_samples"] = [
        {
            "title": normalize(a.select_one("p").get_text(" ", strip=True)),
            "url": urljoin(ROOTS[2], a["href"]),
            "detail_tested": False,
        }
        for a in listing.select(".tab-content a[href]")
        if a.select_one("p")
    ]
    report["udream_frame"] = "/Main/default.aspx"
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    for i, doc in enumerate(report["documents"]):
        (output / f"document-{i}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2)
        )
        print(
            doc["title"],
            f"chars={len(doc['content'])} tables={len(doc['tables'])} images={len(doc['images'])} attachments={len(doc['attachments'])}",
        )
    print(f"udream_listing_items={len(report['udream_listing_samples'])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/live"))
    parser.add_argument(
        "--replay",
        type=Path,
        help="Analyze previously saved HTML/robots samples offline",
    )
    args = parser.parse_args()
    if args.replay:
        replay(args.replay, args.output)
    else:
        live(args.output)
