import pathlib

import scrape_site

FIX = pathlib.Path(__file__).parent / "fixtures"


def read(name):
    return (FIX / name).read_text()


def test_parse_listing_reads_the_real_card_markup():
    cards = scrape_site.parse_listing(read("site_listing.html"), "sydney")
    assert len(cards) == 3
    c = cards[0]
    assert c["event_id"] == "156053" and c["type"] == "poster"
    assert c["url"] == "https://neurips.cc/virtual/2026/poster/156053"
    assert c["title"].startswith("DyPSI: Dynamic Physics Sensing")
    assert "\n" not in c["title"] and c["title"] == c["title"].strip()
    assert c["authors"] == "Yizhou Zhang, Panqi Chen"
    assert c["site"] == "Sydney"


def test_merge_keeps_highest_presentation_and_collapses_duplicates():
    cards = scrape_site.parse_listing(read("site_listing.html"), "sydney")
    cards.append(dict(cards[1], event_id="1", type="oral", title=cards[0]["title"].upper()))
    merged = scrape_site.merge_cards(cards)
    assert len(merged) == 2  # the poster/oral pair of the first paper became one
    first = next(c for c in merged if c["title"].lower().startswith("dypsi"))
    assert first["type"] == "oral"


def test_abstract_from_dedicated_element():
    text, how = scrape_site.extract_abstract(read("site_paper.html"))
    assert how == "#abstractExample"
    assert text.startswith("Physics sensing") and not text.lower().startswith("abstract")


def test_abstract_from_meta_when_no_element():
    text, how = scrape_site.extract_abstract(read("site_paper_meta.html"))
    assert how == "meta og:description" and text.startswith("Physics sensing")


def test_abstract_falls_back_to_longest_paragraph():
    html = "<html><body><p>nav</p><p>" + "word " * 60 + "</p></body></html>"
    text, how = scrape_site.extract_abstract(html)
    assert how == "longest <p>" and len(text) > 150


def test_no_abstract_found():
    assert scrape_site.extract_abstract(read("site_paper_none.html")) == ("", None)


def test_to_paper_matches_build_site_schema():
    card = scrape_site.parse_listing(read("site_listing.html"), "paris")[1]
    p = scrape_site.to_paper(card, "abs")
    assert p["id"] == "nc156054" and p["decision"] == "oral" and p["site"] == "Paris"
    for key in ("title", "authors", "abstract", "pdf_link", "forum_link", "keywords", "tldr", "area", "decision", "track"):
        assert key in p


def test_diagnose_listing_finds_inline_data_and_endpoints():
    html = (
        "<html><head><title>NeurIPS 2026 Papers</title>"
        '<script src="/static/virtual/js/virtual.js"></script></head><body>'
        "<script>const papers = [{\"name\": \"DyPSI: x\", \"url\": \"/virtual/2026/poster/5\"}];"
        "fetch('/static/virtual/data/neurips-2026-orals-posters.json')</script></body></html>"
    )
    text = "\n".join(scrape_site.diagnose_listing(html))
    assert "/static/virtual/js/virtual.js" in text
    assert "{'poster': 1}" in text
    assert "neurips-2026-orals-posters.json" in text
    assert "papers" in text  # inline assignment
    assert "DyPSI: x" in text
    assert "does not occur" in "\n".join(scrape_site.diagnose_listing("<html></html>"))
