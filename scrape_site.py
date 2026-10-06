"""Read the accepted NeurIPS 2026 papers from the neurips.cc virtual site.

Writes data/neurips_2026_papers.json in the same format as scrape.py (OpenReview). The site's
listing pages are rendered by JavaScript from two JSON files (papers and abstracts), which this
script downloads directly. Fields the site does not provide (keywords, TL;DR, primary area,
PDF) stay empty. The JSON layout was not known when this was written, so field names are
looked up from lists of likely candidates and the structure is printed on every run.

    python scrape_site.py           # full scrape
    python scrape_site.py --probe   # print the structure of the JSON files and one paper page
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter
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
MIN_ABSTRACT_CHARS = 150

ID_KEYS = ["id", "eventmedia_id", "event_id", "uid"]
TITLE_KEYS = ["name", "title"]
AUTHOR_KEYS = ["authors", "author", "speakers"]
ABSTRACT_KEYS = ["abstract", "description"]
TYPE_KEYS = ["eventtype", "event_type", "type"]
DECISION_KEYS = ["decision"]
URL_KEYS = ["virtualsite_url", "url", "paper_url", "sourceurl"]
# Fields that may name the location, tried in this order (titles are not searched: a paper
# can mention Paris without being presented there).
LOCATION_KEYS = ["location", "loc", "site", "session", "session_name", "room_name", "room", "venue"]


def clean(text):
    return " ".join(str(text).split())


def first(rec, keys):
    for k in keys:
        v = rec.get(k)
        if v not in (None, "", [], {}):
            return v
    return ""


def find_records(data):
    """The list of paper-like dicts in a JSON document of unknown shape."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("results", "papers", "events", "items", "data"):
            if isinstance(data.get(key), list):
                return find_records(data[key])
        lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if lists:
            return max(lists, key=len)
        vals = list(data.values())
        if vals and all(isinstance(v, dict) for v in vals):
            return [dict(v, id=v.get("id", k)) for k, v in data.items()]
    return []


def abstract_map(data):
    """id -> abstract, from a file that is either {id: text} or a list of records."""
    if isinstance(data, dict) and data and all(isinstance(v, str) for v in data.values()):
        return {str(k): v for k, v in data.items()}
    out = {}
    for rec in find_records(data):
        text, rid = first(rec, ABSTRACT_KEYS), first(rec, ID_KEYS)
        if text and rid != "":
            out[str(rid)] = clean(text)
    return out


def author_names(value):
    if isinstance(value, str):
        return clean(value)
    names = []
    for a in value or []:
        if isinstance(a, dict):
            a = first(a, ["fullname", "full_name", "name", "author"])
        if a:
            names.append(clean(a))
    return ", ".join(names)


def presentation(rec):
    """'oral' | 'spotlight' | 'poster' | 'other' from the event type and decision text."""
    text = f"{first(rec, TYPE_KEYS)} {first(rec, DECISION_KEYS)}".lower()
    for kind in ("oral", "spotlight", "poster"):
        if kind in text:
            return kind
    return "other"


def location(rec):
    for key in LOCATION_KEYS:
        value = str(rec.get(key) or "")
        for name in config.SITE_LOCATIONS:
            if re.search(rf"\b{name}\b", value, re.I):
                return name
    return ""


def event_url(rec, kind):
    url = str(first(rec, URL_KEYS))
    if url.startswith("/virtual/") or "neurips.cc" in url:
        return urljoin(config.SITE_URL, url)
    return f"{config.SITE_URL}/virtual/{config.SITE_YEAR}/{kind if kind in RANK else 'poster'}/{first(rec, ID_KEYS)}"


def parse_events(records, abstracts):
    """Papers JSON records -> [{id, title, authors, abstract, kind, site, url}], one per paper.
    Non-paper events (talks, workshops) are dropped; a paper listed as both an oral and a poster
    keeps the highest presentation."""
    best = {}
    for rec in records:
        title, rid = clean(first(rec, TITLE_KEYS)), first(rec, ID_KEYS)
        kind = presentation(rec)
        has_type = first(rec, TYPE_KEYS) or first(rec, DECISION_KEYS)
        if not title or rid == "" or (has_type and kind == "other"):
            continue
        cand = {
            "id": str(rid),
            "title": title,
            "authors": author_names(first(rec, AUTHOR_KEYS)),
            "abstract": clean(first(rec, ABSTRACT_KEYS)) or abstracts.get(str(rid), ""),
            "kind": kind if has_type else "poster",
            "site": location(rec),
            "url": event_url(rec, kind),
        }
        key = re.sub(r"\W+", " ", title).strip().lower()
        old = best.get(key)
        if old is None or RANK.get(cand["kind"], -1) > RANK.get(old["kind"], -1):
            for field in ("site", "authors", "abstract"):  # keep what the other event knew
                cand[field] = cand[field] or (old or {}).get(field, "")
            best[key] = cand
        else:
            for field in ("site", "authors", "abstract"):
                old[field] = old[field] or cand[field]
    return list(best.values())


ABSTRACT_SELECTORS = [
    ".abstract-text-inner", "#abstractExample", ".abstract-text", ".abstract-content", ".abstract",
]


def extract_abstract(html):
    """Abstract text from a paper page, or "" ('.abstract-text-inner' on the real site)."""
    soup = BeautifulSoup(html, "html.parser")
    for sel in ABSTRACT_SELECTORS:
        node = soup.select_one(sel)
        if node is not None:
            text = re.sub(r"^abstract\s*:?\s*", "", clean(node.get_text(" ")), flags=re.I)
            if len(text) >= MIN_ABSTRACT_CHARS:
                return text
    return ""


def get(session, url, as_json=False):
    delay = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=120)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json() if as_json else resp.text
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            print(f"  {url}: {exc}; retry {attempt}/{MAX_RETRIES - 1} in {delay:.0f}s")
            time.sleep(delay)
            delay *= 2


def describe(name, data):
    """Print the layout of a JSON document, so a mismatch with the parser is visible."""
    recs = find_records(data)
    print(f"{name}: {type(data).__name__}"
          + (f", top-level keys {list(data)[:12]}" if isinstance(data, dict) else "")
          + f", {len(recs)} records")
    if recs:
        print("  fields (records having each):", dict(Counter(k for r in recs for k in r).most_common(30)))
        print("  first record:", json.dumps(recs[0], ensure_ascii=False)[:900])
    elif isinstance(data, dict):
        k = next(iter(data), None)
        print("  first entry:", json.dumps({k: data.get(k)}, ensure_ascii=False)[:500])


def probe(session):
    """Print what the site returns, to adapt the parser without guessing."""
    papers = get(session, config.SITE_PAPERS_JSON, as_json=True)
    describe("papers json", papers)
    try:
        describe("abstracts json", get(session, config.SITE_ABSTRACTS_JSON, as_json=True))
    except requests.RequestException as exc:
        print("abstracts json:", exc)
    parsed = parse_events(find_records(papers), {})
    print(f"parse_events: {len(parsed)} papers;",
          "kinds", dict(Counter(p["kind"] for p in parsed)),
          "| sites", dict(Counter(p["site"] for p in parsed)),
          "| with abstract", sum(bool(p["abstract"]) for p in parsed),
          "| with authors", sum(bool(p["authors"]) for p in parsed))
    if parsed:
        print("  sample:", json.dumps(parsed[0], ensure_ascii=False)[:500])
        page = get(session, parsed[0]["url"])
        print(f"paper page {parsed[0]['url']}: abstract found: {bool(extract_abstract(page))}")


def to_paper(p, abstract):
    return {
        "id": f"nc{p['id']}",
        "title": p["title"],
        "authors": p["authors"],
        "abstract": abstract,
        "pdf_link": "",
        "forum_link": p["url"],
        "keywords": [],
        "tldr": "",
        "area": "",
        "decision": p["kind"],
        "track": "",
        "site": p["site"],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true", help="inspect the site and exit")
    args = ap.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    if args.probe:
        probe(session)
        return

    raw = get(session, config.SITE_PAPERS_JSON, as_json=True)
    describe("papers json", raw)
    try:
        abstracts = abstract_map(get(session, config.SITE_ABSTRACTS_JSON, as_json=True))
    except requests.RequestException as exc:
        print("abstracts json unavailable:", exc)
        abstracts = {}
    print(f"{len(abstracts)} abstracts in the abstracts file")

    papers = parse_events(find_records(raw), abstracts)
    if not papers:
        sys.exit("No papers recognised in the papers JSON. The structure printed above shows why.")
    print(f"{len(papers)} papers;", dict(Counter(p["kind"] for p in papers)),
          "| sites", dict(Counter(p["site"] for p in papers)))

    # Abstracts missing from both JSON files come from the paper page.
    todo = [p for p in papers if not p["abstract"]]
    if todo:
        print(f"fetching {len(todo)} abstracts from paper pages...")

        def work(p):
            try:
                return extract_abstract(get(session, p["url"]))
            except requests.RequestException:
                return ""

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for p, text in zip(todo, pool.map(work, todo)):
                p["abstract"] = text

    missing = [p["url"] for p in papers if not p["abstract"]]
    if len(missing) > MAX_MISSING_ABSTRACTS * len(papers):
        sys.exit(f"{len(missing)}/{len(papers)} papers have no abstract, e.g. {missing[:3]}")
    if missing:
        print(f"skipped {len(missing)} papers without an abstract: {missing[:5]}")

    out = sorted((to_paper(p, p["abstract"]) for p in papers if p["abstract"]), key=lambda p: p["id"])
    os.makedirs(os.path.dirname(config.PAPERS_PATH), exist_ok=True)
    with open(config.PAPERS_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"Wrote {len(out)} papers to {config.PAPERS_PATH}")


if __name__ == "__main__":
    main()
