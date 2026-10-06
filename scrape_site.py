"""Scrape accepted NeurIPS 2026 papers from the neurips.cc virtual site.

Writes data/neurips_2026_papers.json in the same format as scrape.py (OpenReview).
For each location (Sydney, Atlanta, Paris) it reads the listing
https://neurips.cc/virtual/2026/loc/<location>/papers.html, then fetches every paper page for
its abstract. Fields the site does not provide (keywords, TL;DR, primary area, PDF) stay empty.

    python scrape_site.py           # full scrape
    python scrape_site.py --probe   # report what the listing and one paper page contain
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import config

MAX_WORKERS = 8
MAX_RETRIES = 4
USER_AGENT = "neurips-explorer (+https://github.com/flecomet/neurips-explorer)"
# Presentation types in increasing rank; a paper listed twice keeps the highest.
RANK = {"poster": 0, "spotlight": 1, "oral": 2}
MAX_MISSING_ABSTRACTS = 0.02

EVENT_HREF = re.compile(r"/virtual/\d{4}/([a-z_\-]+)/(\d+)")


def clean(text):
    return " ".join(text.split())


def parse_listing(html, site):
    """Cards on a listing page -> [{event_id, type, url, title, authors, site}]."""
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for card in soup.select(".pp-card"):
        link = next(
            (a for a in card.find_all("a", href=True) if EVENT_HREF.search(a["href"])), None
        )
        title = card.select_one(".card-title")
        if link is None or title is None:
            continue
        kind, event_id = EVENT_HREF.search(link["href"]).groups()
        authors = [
            clean(a.get_text())
            for a in card.select(".card-subtitle a[href*='filter=author']")
        ]
        cards.append({
            "event_id": event_id,
            "type": kind,
            "url": urljoin(config.SITE_URL, link["href"]),
            "title": clean(title.get_text()),
            "authors": ", ".join(authors),
            "site": site.capitalize(),
        })
    return cards


def merge_cards(cards):
    """One record per paper: the same title can appear as several events (oral and poster)."""
    best = {}
    for c in cards:
        key = re.sub(r"\W+", " ", c["title"]).strip().lower()
        if key not in best or RANK.get(c["type"], -1) > RANK.get(best[key]["type"], -1):
            best[key] = c
    return list(best.values())


# Tried in order. The first that yields a plausible abstract wins; the name is counted so
# the scrape log shows which selector the site actually needs.
ABSTRACT_SELECTORS = [
    ("#abstractExample", lambda s: s.select_one("#abstractExample")),
    (".abstract-text-inner", lambda s: s.select_one(".abstract-text-inner")),
    (".abstract", lambda s: s.select_one(".abstract")),
    ("meta citation_abstract", lambda s: s.select_one("meta[name=citation_abstract]")),
    ("meta og:description", lambda s: s.select_one("meta[property='og:description']")),
    ("meta description", lambda s: s.select_one("meta[name=description]")),
]
MIN_ABSTRACT_CHARS = 150


def extract_abstract(html):
    """-> (abstract, how). `how` names the strategy, or is None when nothing was found."""
    soup = BeautifulSoup(html, "html.parser")
    for name, finder in ABSTRACT_SELECTORS:
        node = finder(soup)
        if node is None:
            continue
        text = clean(node.get("content", "") if node.name == "meta" else node.get_text(" "))
        text = re.sub(r"^abstract\s*:?\s*", "", text, flags=re.I)
        if len(text) >= MIN_ABSTRACT_CHARS:
            return text, name
    # Last resort: the longest paragraph on the page.
    paras = [clean(p.get_text(" ")) for p in soup.find_all("p")]
    paras = [p for p in paras if len(p) >= MIN_ABSTRACT_CHARS]
    if paras:
        return max(paras, key=len), "longest <p>"
    return "", None


def get(session, url):
    delay = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=60)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            print(f"  {url}: {exc}; retry {attempt}/{MAX_RETRIES - 1} in {delay:.0f}s")
            time.sleep(delay)
            delay *= 2


def listing_url(site):
    return f"{config.SITE_URL}/virtual/{config.SITE_YEAR}/loc/{site}/papers.html"


def fetch_listings(session):
    cards = []
    for site in config.SITE_LOCATIONS:
        found = parse_listing(get(session, listing_url(site)), site)
        print(f"{site}: {len(found)} cards")
        cards.extend(found)
    return cards


def to_paper(card, abstract):
    return {
        "id": f"nc{card['event_id']}",
        "title": card["title"],
        "authors": card["authors"],
        "abstract": abstract,
        "pdf_link": "",
        "forum_link": card["url"],
        "keywords": [],
        "tldr": "",
        "area": "",
        "decision": card["type"] if card["type"] in RANK else "other",
        "track": "",
        "site": card["site"],
    }


KNOWN_PAPER_URL = "/virtual/2026/poster/156053"  # a paper seen on the site, used as a sample
KNOWN_TITLE = "DyPSI"


def snippet(html, i, before=150, after=350):
    return clean(html[max(0, i - before) : i + after])


SCRIPT_SRC = re.compile(r"""<script[^>]+src=["']([^"']+)""")
JSON_NAME = re.compile(r"[\w/.\-]+\.json[\w?=&]*")
DATA_ASSIGN = re.compile(r"(?:var|let|const)\s+(\w+)\s*=\s*[\[{]")
LOADERS = [re.compile(p) for p in (r"fetch\(", r"getJSON\(", r"\$\.get\(", r"\$\.ajax\(", r"XMLHttpRequest")]


def diagnose_listing(html, needle=KNOWN_TITLE):
    """Say where a listing page keeps its papers when no server-rendered cards are found."""
    title = BeautifulSoup(html, "html.parser").title
    kinds = {}
    for kind, _ in EVENT_HREF.findall(html):
        kinds[kind] = kinds.get(kind, 0) + 1
    lines = [
        f"<title>: {clean(title.get_text()) if title else None}",
        f"script srcs: {SCRIPT_SRC.findall(html)[:15]}",
        f"/virtual/<year>/<type>/<id> links in raw html, by type: {kinds}",
        f"'.json' strings: {sorted(set(JSON_NAME.findall(html)))[:15]}",
    ]
    for pat in LOADERS:
        for m in list(pat.finditer(html))[:2]:
            lines.append(f"{pat.pattern} at {m.start()}: {snippet(html, m.start(), 100, 250)}")
    lines.append(f"inline data-like assignments: {DATA_ASSIGN.findall(html)[:15]}")
    i = html.find(needle)
    lines.append(
        f"first occurrence of {needle!r} at {i}: {snippet(html, i, 400, 600)}"
        if i >= 0 else f"{needle!r} does not occur in the raw html"
    )
    return lines


def report_paper_page(session, url):
    page = get(session, url)
    abstract, how = extract_abstract(page)
    print(f"paper page {url}: {len(page)} bytes; abstract via {how!r}: {abstract[:200]!r}")
    soup = BeautifulSoup(page, "html.parser")
    print("  meta names:", sorted({m.get("name") or m.get("property") for m in soup.find_all("meta")} - {None}))
    print("  ids:", sorted({t["id"] for t in soup.find_all(id=True)})[:40])
    print("  classes containing 'abstract':", sorted({c for t in soup.find_all(class_=True) for c in t["class"] if "abstract" in c.lower()}))
    if how is None:
        i = page.find("Physics sensing")  # start of the sample paper's abstract
        print("  abstract text in raw html:", snippet(page, i, 300, 300) if i >= 0 else "not found in raw html")


def probe(session):
    """Print what the site returns, to adapt the parser without guessing."""
    site = config.SITE_LOCATIONS[0]
    html = get(session, listing_url(site))
    print(f"listing {site}: {len(html)} bytes, {html.count('pp-card')} 'pp-card' strings")
    cards = parse_listing(html, site)
    print(f"parsed cards: {len(cards)}; types: { {c['type'] for c in cards} }")
    for c in cards[:2]:
        print("  sample card:", json.dumps(c)[:300])
    if not cards:
        print("No server-rendered cards. Where the page keeps its data:")
        for line in diagnose_listing(html):
            print(" ", line)
    report_paper_page(session, cards[0]["url"] if cards else config.SITE_URL + KNOWN_PAPER_URL)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true", help="inspect the site and exit")
    args = ap.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    if args.probe:
        probe(session)
        return

    cards = merge_cards(fetch_listings(session))
    if not cards:
        sys.exit("No papers found on the listing pages. Run with --probe to inspect them.")
    print(f"{len(cards)} unique papers; fetching abstracts...")

    def work(card):
        try:
            return extract_abstract(get(session, card["url"]))
        except requests.RequestException as exc:
            return "", f"error: {exc}"

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(work, cards))

    papers, how_counts, missing = [], {}, []
    for card, (abstract, how) in zip(cards, results):
        how_counts[how] = how_counts.get(how, 0) + 1
        if not abstract:
            missing.append(card["url"])
            continue
        papers.append(to_paper(card, abstract))
    print("abstract source:", how_counts)
    if len(missing) > MAX_MISSING_ABSTRACTS * len(cards):
        sys.exit(f"{len(missing)}/{len(cards)} pages gave no abstract, e.g. {missing[:3]}")
    if missing:
        print(f"skipped {len(missing)} papers without an abstract: {missing[:5]}")

    papers.sort(key=lambda p: p["id"])
    os.makedirs(os.path.dirname(config.PAPERS_PATH), exist_ok=True)
    with open(config.PAPERS_PATH, "w") as f:
        json.dump(papers, f, ensure_ascii=False)
    print(f"Wrote {len(papers)} papers to {config.PAPERS_PATH}")


if __name__ == "__main__":
    main()
