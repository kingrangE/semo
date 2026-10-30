"""Robots-aware HTTP and offline HTML readers."""

import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from semo.application import MissingSnapshot
from semo.domain import digest

UA = "SemoFeasibilityProbe/0.1"


class Robots:
    """Handle these sites' wildcard/end-anchor rules (urllib.robotparser does not)."""

    def __init__(self, text):
        self.groups = []
        agents, rules, delay = [], [], 0
        directives_started = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if directives_started:
                    self.groups.append((agents, rules, delay))
                    agents, rules, delay = [], [], 0
                agents.append(value.lower())
                directives_started = False
            elif agents:
                directives_started = True
                if key in ("allow", "disallow") and value:
                    rules.append((key, value))
                elif key == "crawl-delay":
                    try:
                        delay = max(0, float(value))
                    except ValueError:
                        pass
        if agents:
            self.groups.append((agents, rules, delay))
        specific = [
            g for g in self.groups if any(a != "*" and a in UA.lower() for a in g[0])
        ]
        selected = specific or [g for g in self.groups if "*" in g[0]]
        self.rules = [rule for _, rules, _ in selected for rule in rules]
        self.delay = max((g[2] for g in selected), default=0)
        self.valid = bool(self.groups)

    def allowed(self, url):
        parts = urlsplit(url)
        target = parts.path + ("?" + parts.query if parts.query else "")
        matches = []
        for action, pattern in self.rules:
            anchored = pattern.endswith("$")
            literal = pattern[:-1] if anchored else pattern
            regex = (
                "^"
                + re.escape(literal).replace(r"\*", ".*")
                + ("$" if anchored else "")
            )
            if re.search(regex, target):
                matches.append((len(literal.replace("*", "")), action == "allow"))
        return self.valid and (max(matches)[1] if matches else True)


def fetch(url, destination):
    # Redirects fail closed so a permitted URL cannot redirect into a restricted path.
    result = subprocess.run(
        [
            "curl",
            "-L",
            "--compressed",
            "--max-redirs",
            "0",
            "--max-time",
            "30",
            "--max-filesize",
            "10485760",
            "-sS",
            "-A",
            UA,
            "-o",
            str(destination),
            "-w",
            "%{http_code} %{content_type}",
            url,
        ],
        capture_output=True,
        text=True,
    )
    status, _, content_type = result.stdout.partition(" ")
    return {
        "url": url,
        "http_status": int(status or 0),
        "content_type": content_type,
        "ok": result.returncode == 0 and status == "200",
        "error": result.stderr.strip() or None,
    }


def network_reader(root: str, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    response = fetch(root + "/robots.txt", output / "robots.txt")
    if not response["ok"]:
        raise RuntimeError(f"robots.txt unavailable: {response}")
    policy = Robots((output / "robots.txt").read_text())
    last_request = time.monotonic()

    def read_html(url):
        nonlocal last_request
        if urlsplit(url).netloc != urlsplit(root).netloc or not policy.allowed(url):
            raise ValueError(f"URL not allowed: {url}")
        time.sleep(max(0, max(1, policy.delay) - (time.monotonic() - last_request)))
        destination = output / (digest(url, None, "") + ".html")
        response = fetch(url, destination)
        last_request = time.monotonic()
        if not response["ok"] or "text/html" not in response["content_type"]:
            raise RuntimeError(f"HTML fetch failed: {response}")
        return destination.read_text(encoding="utf-8")

    return read_html


class SnapshotReader:
    def __init__(self, directory: Path):
        self.directory = directory
        self.manifest = json.loads(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )

    def __call__(self, url: str) -> str:
        if url not in self.manifest:
            raise MissingSnapshot(url)
        path = (self.directory / self.manifest[url]).resolve()
        if not path.is_relative_to(self.directory.resolve()):
            raise ValueError(f"Snapshot path escapes directory: {path}")
        return path.read_text(encoding="utf-8")
