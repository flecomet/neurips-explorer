import pathlib

import scrape_site

ABS = "A long enough abstract. " * 10


def rec(**kw):
    base = {"id": 1, "name": "Paper One", "eventtype": "Poster", "session": "Sydney Poster Session 2"}
    base.update(kw)
    return base


# NOTE: these JSON shapes are guesses (the real files were not visible when written).

def test_find_records_handles_common_shapes():
    r = [rec()]
    assert scrape_site.find_records(r) == r
    assert scrape_site.find_records({"count": 1, "results": r}) == r
    assert scrape_site.find_records({"meta": {}, "stuff": r}) == r
    keyed = scrape_site.find_records({"7": {"name": "X"}})
    assert keyed == [{"name": "X", "id": "7"}]
    assert scrape_site.find_records("nonsense") == []


def test_abstract_map_from_dict_or_records():
    assert scrape_site.abstract_map({"1": "a", 2: "b"}) == {"1": "a", "2": "b"}
    assert scrape_site.abstract_map({"results": [{"id": 3, "abstract": " x  y "}]}) == {"3": "x y"}


def test_author_names_accepts_dicts_strings_and_text():
    assert scrape_site.author_names([{"fullname": "A B"}, {"name": "C D"}, "E F"]) == "A B, C D, E F"
    assert scrape_site.author_names("A B, C D") == "A B, C D"
    assert scrape_site.author_names(None) == ""


def test_presentation_from_type_and_decision():
    assert scrape_site.presentation(rec(eventtype="Oral")) == "oral"
    assert scrape_site.presentation(rec(eventtype="Poster", decision="Accept (spotlight)")) == "spotlight"
    assert scrape_site.presentation(rec(eventtype="Invited Talk")) == "other"


def test_parse_events_basics():
    out = scrape_site.parse_events(
        [rec(authors=[{"fullname": "A B"}], abstract=ABS)], {}
    )
    assert out == [{
        "id": "1", "title": "Paper One", "authors": "A B", "abstract": ABS.strip(),
        "kind": "poster", "site": "Sydney",
        "url": "https://neurips.cc/virtual/2026/poster/1",
    }]


def test_parse_events_takes_abstract_from_second_file_and_drops_non_papers():
    out = scrape_site.parse_events(
        [rec(), rec(id=2, name="A Workshop Talk", eventtype="Invited Talk")], {"1": "from abstracts file"}
    )
    assert [p["title"] for p in out] == ["Paper One"]
    assert out[0]["abstract"] == "from abstracts file"


def test_parse_events_merges_oral_and_poster_of_one_paper():
    out = scrape_site.parse_events(
        [rec(id=1, authors="A B"), rec(id=2, eventtype="Oral", session="", name="paper one")], {}
    )
    assert len(out) == 1
    p = out[0]
    assert p["kind"] == "oral" and p["id"] == "2"
    assert p["site"] == "Sydney" and p["authors"] == "A B"  # filled in from the poster event


def test_location_ignores_the_title():
    r = rec(name="Paris Agreement Modelling", session="Atlanta Poster Session 1")
    assert scrape_site.location(r) == "Atlanta"
    assert scrape_site.location(rec(session="", name="Paris Agreement")) == ""


def test_event_url_prefers_the_records_own_link():
    assert scrape_site.event_url(rec(url="/virtual/2026/oral/9"), "oral") == "https://neurips.cc/virtual/2026/oral/9"
    assert scrape_site.event_url(rec(), "oral") == "https://neurips.cc/virtual/2026/oral/1"


def test_extract_abstract_from_page():
    html = (pathlib.Path(__file__).parent / "fixtures" / "site_paper.html").read_text()
    text = scrape_site.extract_abstract(html)
    assert text.startswith("Physics sensing") and text.endswith("framework.")
    assert scrape_site.extract_abstract("<html><body><p>nothing</p></body></html>") == ""


def test_to_paper_matches_build_site_schema():
    p = scrape_site.parse_events([rec(abstract=ABS)], {})[0]
    paper = scrape_site.to_paper(p, p["abstract"])
    assert paper["id"] == "nc1" and paper["decision"] == "poster" and paper["site"] == "Sydney"
    for key in ("title", "authors", "abstract", "pdf_link", "forum_link", "keywords", "tldr", "area", "decision", "track"):
        assert key in paper
