"""Fetch the accepted NeurIPS 2026 papers from the OpenReview API.

Writes data/neurips_2026_papers.json: a list of
{id, title, authors, abstract, pdf_link, forum_link, keywords, tldr, area,
 decision, track}, sorted by OpenReview id so reruns give a stable order.

Accepted papers are public on OpenReview once the authors have been notified.
Missing optional fields (keywords, TL;DR, primary area) become empty values.
"""
import argparse
import json
import os
import sys
import time

import requests

import config

PAGE_SIZE = 1000
MAX_RETRIES = 5
DECISIONS = ("oral", "spotlight", "poster")
USER_AGENT = "neurips-explorer (+https://github.com/flecomet/neurips-explorer)"


def value(content, key, default=""):
    """OpenReview API v2 wraps every field as {"value": ...}."""
    field = content.get(key)
    if isinstance(field, dict):
        field = field.get("value")
    return default if field is None else field


def parse_decision(venue):
    """'NeurIPS 2026 spotlight' -> 'spotlight'; anything unrecognised -> 'other'."""
    words = str(venue).lower().split()
    return words[-1] if words and words[-1] in DECISIONS else "other"


def parse_note(note, track):
    content = note.get("content", {})
    pdf = value(content, "pdf")
    if pdf.startswith("/"):
        pdf = config.OPENREVIEW_URL + pdf
    authors = value(content, "authors", [])
    return {
        "id": note["id"],
        "title": " ".join(str(value(content, "title")).split()),
        "authors": ", ".join(authors) if isinstance(authors, list) else str(authors),
        "abstract": " ".join(str(value(content, "abstract")).split()),
        "pdf_link": pdf,
        "forum_link": f"{config.OPENREVIEW_URL}/forum?id={note.get('forum') or note['id']}",
        "keywords": list(value(content, "keywords", [])),
        # API v2 uses "TLDR"; v1 used "TL;DR".
        "tldr": str(value(content, "TLDR") or value(content, "TL;DR")),
        "area": str(value(content, "primary_area")),
        "decision": parse_decision(value(content, "venue")),
        "track": track,
    }


class ApiError(RuntimeError):
    pass


def login(session, username, password):
    """Optional: send an OpenReview bearer token with every request."""
    resp = session.post(
        f"{config.OPENREVIEW_API}/login",
        json={"id": username, "password": password},
        timeout=60,
    )
    if resp.status_code != 200:
        raise ApiError(f"OpenReview login failed: HTTP {resp.status_code} {resp.text[:300]}")
    session.headers["Authorization"] = f"Bearer {resp.json()['token']}"
    print("Logged in to OpenReview.")


def get_json(session, url, params):
    delay = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        resp = session.get(url, params=params, timeout=60)
        if resp.status_code >= 400 and resp.status_code != 429 and resp.status_code < 500:
            # Show what the server said: a 403 can mean an unreadable venue, a blocked
            # client or a blocked network, and the body tells them apart.
            keep = ("server", "cf-ray", "www-authenticate", "content-type")
            hdrs = {k: v for k, v in resp.headers.items() if k.lower() in keep}
            raise ApiError(
                f"HTTP {resp.status_code} for {resp.url}\n"
                f"headers: {hdrs}\nbody: {resp.text[:600]!r}"
            )
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = float(resp.headers.get("Retry-After", delay))
            print(f"  HTTP {resp.status_code}, retrying in {wait:.0f}s ({attempt}/{MAX_RETRIES})")
            time.sleep(wait)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"giving up on {url} after {MAX_RETRIES} attempts")


def fetch_venue(session, venueid, track):
    notes, offset = [], 0
    while True:
        page = get_json(
            session,
            f"{config.OPENREVIEW_API}/notes",
            {"content.venueid": venueid, "limit": PAGE_SIZE, "offset": offset},
        )
        batch = page.get("notes", [])
        notes.extend(batch)
        print(f"  {track}: {len(notes)} notes")
        if len(batch) < PAGE_SIZE:
            return [parse_note(n, track) for n in notes]
        offset += PAGE_SIZE


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--venue", action="append", metavar="LABEL=VENUE_ID",
        help="override config.VENUES; repeatable",
    )
    args = ap.parse_args()
    venues = dict(v.split("=", 1) for v in args.venue) if args.venue else config.VENUES

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    user, password = os.environ.get("OPENREVIEW_USERNAME"), os.environ.get("OPENREVIEW_PASSWORD")
    if user and password:
        login(session, user, password)
    papers = {}
    for track, venueid in venues.items():
        print(f"Fetching {track} ({venueid})")
        found = fetch_venue(session, venueid, track)
        print(f"  -> {len(found)} papers")
        for p in found:
            papers[p["id"]] = p

    papers = sorted(papers.values(), key=lambda p: p["id"])
    if not papers:
        sys.exit("No papers found. Check the venue ids (see config.py).")
    bad = [p["id"] for p in papers if not p["title"] or not p["abstract"]]
    if bad:
        sys.exit(f"{len(bad)} papers lack a title or abstract, e.g. {bad[:3]}")

    os.makedirs(os.path.dirname(config.PAPERS_PATH), exist_ok=True)
    with open(config.PAPERS_PATH, "w") as f:
        json.dump(papers, f, ensure_ascii=False)
    print(f"Wrote {len(papers)} papers to {config.PAPERS_PATH}")


if __name__ == "__main__":
    main()
