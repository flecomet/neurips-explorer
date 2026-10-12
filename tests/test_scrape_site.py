import json
import pathlib

import pytest

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


@pytest.mark.parametrize(('source', 'expected'), [
    ('https://openreview.net/group?id=NeurIPS.cc/2026/Conference', 'Main'),
    ('https://openreview.net/group?id=NeurIPS.cc%2F2026%2FEvaluations_and_Datasets_Track', 'E&D'),
    ('https://openreview.net/group?id=NeurIPS.cc/2026/Position_Paper_Track', 'Position'),
    ('journal-track/NeurIPS_2026-Posters_TMLR.xlsx', 'Journal'),
    ('journal-track/NeurIPS_2026-Posters_JMLR.xlsx', 'Journal'),
    ('journal-track/NeurIPS_2026-Posters_AoS.xlsx', 'Journal'),
    ('https://example.org/group?id=NeurIPS.cc/2026/Conference', ''),
    ('https://openreview.net/group?id=NeurIPS.cc/2025/Conference', ''),
    (None, ''),
])
def test_listing_track_reaches_paper_metadata(source, expected):
    event = scrape_site.parse_events([rec(sourceurl=source)], {})[0]
    assert scrape_site.to_paper(event, ABS)['track'] == expected


def test_duplicate_events_keep_track_from_either_presentation():
    poster = rec(sourceurl='https://openreview.net/group?id=NeurIPS.cc/2026/Conference')
    oral = rec(id=2, eventtype='Oral')
    for records in ([poster, oral], [oral, poster]):
        event = scrape_site.parse_events(records, {})[0]
        assert scrape_site.to_paper(event, ABS)['track'] == 'Main'


def test_refresh_keeps_verified_track_when_listing_omits_it(tmp_path):
    path = tmp_path / 'papers.json'
    path.write_text(json.dumps([
        {'id': 'nc1', 'title': 'Paper One', 'authors': 'A', 'track': 'E&D'},
    ]))
    merged = scrape_site.keep_previous([
        {'id': 'nc2', 'title': 'Paper One', 'authors': 'A', 'track': ''},
    ], str(path))
    assert merged[0]['track'] == 'E&D'

    merged = scrape_site.keep_previous([
        {'id': 'nc2', 'title': 'Paper One', 'authors': 'A', 'track': 'Main'},
    ], str(path))
    assert merged[0]['track'] == 'Main'


def test_track_enrichment_preserves_content_and_rejects_ambiguous_matches():
    papers = [
        {'id': 'nc1', 'title': 'Paper One', 'authors': 'A', 'track': '', 'abstract': ABS},
        {'id': 'nc2', 'title': 'Paper Two', 'authors': 'B', 'track': ''},
        {'id': 'nc3', 'title': 'Paper Three', 'authors': 'C', 'track': ''},
        {'id': 'nc4', 'title': 'Paper Four', 'authors': 'D', 'track': ''},
        {'id': 'nc5', 'title': 'Paper Five', 'authors': 'E', 'track': 'Main'},
        {'id': 'nc6', 'aliases': ['nc60'], 'title': 'Paper Six', 'authors': 'F', 'track': ''},
    ]
    main = 'https://openreview.net/group?id=NeurIPS.cc/2026/Conference'
    ed = 'https://openreview.net/group?id=NeurIPS.cc/2026/Evaluations_and_Datasets_Track'
    records = [
        rec(sourceurl=main, authors='different author transcription'),
        rec(id=22, name='Paper Two', authors='B', sourceurl=ed),
        rec(id=33, name='Paper Three', authors='Different person', sourceurl=main),
        rec(id=4, name='Paper Four', authors='D', sourceurl=main),
        rec(id=4, name='Paper Four', authors='D', sourceurl=ed),
        rec(id=6, name='Unrelated title', authors='F', sourceurl=main),
        rec(id=60, name='Paper Six', authors='Other transcription', sourceurl=ed),
    ]
    original = json.loads(json.dumps(papers))
    enriched = scrape_site.enrich_tracks(papers, records)
    assert [p['track'] for p in enriched] == ['Main', 'E&D', '', '', 'Main', 'E&D']
    assert papers == original
    assert [{k: v for k, v in p.items() if k != 'track'} for p in enriched] == [
        {k: v for k, v in p.items() if k != 'track'} for p in original
    ]


def test_track_enrichment_cli_combines_snapshots_without_fetching_pages(tmp_path, monkeypatch):
    import sys

    path = tmp_path / 'papers.json'
    path.write_text(json.dumps([
        {'id': 'nc1', 'title': 'Paper One', 'authors': 'A', 'track': ''},
        {'id': 'nc2', 'title': 'Paper Two', 'authors': 'B', 'track': ''},
    ]))
    snapshots = []
    for i, venue in enumerate(('Conference', 'Position_Paper_Track'), 1):
        snapshot = tmp_path / f'source{i}.json'
        snapshot.write_text(json.dumps({'results': [rec(
            id=i, name=f'Paper {"One" if i == 1 else "Two"}',
            sourceurl=f'https://openreview.net/group?id=NeurIPS.cc/2026/{venue}',
        )]}))
        snapshots.extend(['--enrich-tracks', str(snapshot)])
    monkeypatch.setattr(scrape_site.config, 'PAPERS_PATH', str(path))
    monkeypatch.setattr(sys, 'argv', ['scrape_site.py', *snapshots])

    def no_network():
        raise AssertionError('offline enrichment must not create a network session')

    monkeypatch.setattr(scrape_site.requests, 'Session', no_network)
    scrape_site.main()
    assert [p['track'] for p in json.loads(path.read_text())] == ['Main', 'Position']


def test_enrich_author_identities_preserves_existing_paper_content():
    papers = [
        {'id': 'nc1', 'title': 'Paper One', 'authors': "A O'Neil, B", 'abstract': 'unchanged'},
        {'id': 'nc2', 'title': 'Paper Two', 'authors': 'A', 'abstract': 'also unchanged'},
    ]
    records = [rec(authors=[
        {'id': 101, 'fullname': 'A O&amp;#x27;Neil', 'institution': 'University A'},
        {'id': 202, 'fullname': 'B', 'institution': 'University B'},
    ])]
    enriched = scrape_site.enrich_authors(papers, records)
    assert enriched[0]['author_details'] == [
        {'id': 'neurips:101', 'name': "A O'Neil", 'institution': 'University A'},
        {'id': 'neurips:202', 'name': 'B', 'institution': 'University B'},
    ]
    assert [{k: v for k, v in p.items() if k != 'author_details'} for p in enriched] == papers
    assert enriched[1] == papers[1]


def test_enrichment_rejects_changed_author_lists_and_conflicting_identities():
    paper = {'id': 'nc1', 'title': 'Paper One', 'authors': 'A, B'}
    a = {'id': 101, 'fullname': 'A', 'institution': 'University A'}
    b = {'id': 202, 'fullname': 'B', 'institution': 'University B'}
    assert scrape_site.enrich_authors([paper], [rec(authors=[b, a])]) == [paper]
    conflicting = [rec(authors=[a, b]), rec(id=2, authors=[{**a, 'id': 303}, b])]
    assert scrape_site.enrich_authors([paper], conflicting) == [paper]


def test_future_scrapes_retain_author_identity_through_event_merge():
    records = [rec(authors=[{'id': 101, 'fullname': 'A B', 'institution': 'University A'}]),
               rec(id=2, eventtype='Oral', authors='')]
    event = scrape_site.parse_events(records, {})[0]
    paper = scrape_site.to_paper(event, ABS)
    assert paper['author_details'] == [
        {'id': 'neurips:101', 'name': 'A B', 'institution': 'University A'},
    ]


def test_enrichment_cli_uses_snapshot_without_fetching_pages(tmp_path, monkeypatch):
    import sys

    papers = [{'id': 'nc1', 'title': 'Paper One', 'authors': 'A', 'abstract': ABS}]
    path = tmp_path / 'papers.json'
    path.write_text(json.dumps(papers))
    snapshot = tmp_path / 'source.json'
    snapshot.write_text(json.dumps({'results': [rec(authors=[{'id': 101, 'fullname': 'A'}])]}))
    monkeypatch.setattr(scrape_site.config, 'PAPERS_PATH', str(path))
    monkeypatch.setattr(sys, 'argv', ['scrape_site.py', '--enrich-authors', str(snapshot)])

    def no_network():
        raise AssertionError('offline enrichment must not create a network session')

    monkeypatch.setattr(scrape_site.requests, 'Session', no_network)
    scrape_site.main()
    enriched = json.loads(path.read_text())
    assert enriched[0]['author_details'][0]['id'] == 'neurips:101'
    assert {k: v for k, v in enriched[0].items() if k != 'author_details'} == papers[0]


def test_verified_previous_page_preserves_identity_only_when_authors_agree(tmp_path, monkeypatch):
    path = tmp_path / 'papers.json'
    details = [{'id': 'neurips:101', 'name': 'Alice', 'institution': 'University A'}]
    path.write_text(json.dumps([
        {'id': 'nc1', 'title': 'Same authors', 'authors': 'Alice', 'author_details': details},
        {'id': 'nc2', 'title': 'Changed authors', 'authors': 'Alice', 'author_details': details},
    ]))

    def page(session, url):
        title, name = ('Same authors', 'Alice') if url.endswith('/1') else ('Changed authors', 'Bob')
        return (f'<div class="hero-card poster"><h1>{title}</h1><div>{name}</div></div>'
                f'<div class="abstract-text-inner">{ABS}</div>')

    monkeypatch.setattr(scrape_site, 'get', page)
    merged = scrape_site.keep_previous([], str(path), session=object())
    assert merged[0]['author_details'] == details
    assert 'author_details' not in merged[1]


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
        "track": "",
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


def test_parse_paper_page_reads_title_authors_kind_and_site():
    html = (pathlib.Path(__file__).parent / "fixtures" / "site_paper_card.html").read_text()
    info = scrape_site.parse_paper_page(html)
    assert info["title"] == "AgentAbstain: Do LLM Agents Know When Not to Act?"
    assert info["authors"].startswith("Xun Liu, Yi Evie Zhang, Vira Kasprova")
    assert info["authors"].endswith("Varun Chandrasekaran")
    assert info["kind"] == "oral" and info["site"] == "Atlanta"
    assert scrape_site.parse_paper_page("<html><body><p>not a paper</p></body></html>") == {}


def test_title_key_ignores_case_and_punctuation():
    assert scrape_site.title_key("Hello,  World!") == scrape_site.title_key("hello world")


def test_id_gaps_fills_holes_inside_runs_only():
    assert scrape_site.id_gaps(["10", "12", "13", "20000"]) == ["11"]
    assert scrape_site.id_gaps(["5", "6"]) == []


def test_parse_paper_page_rejects_pages_without_presentation_type():
    html = (pathlib.Path(__file__).parent / "fixtures" / "site_paper_card.html").read_text()
    talk = html.replace('class="hero-card oral"', 'class="hero-card talk"')
    assert scrape_site.parse_paper_page(talk) == {}


def test_keep_previous_merges_old_identifiers_without_duplicate_titles(tmp_path):
    path = tmp_path / "papers.json"
    path.write_text(json.dumps([
        {"id": "nc1", "title": "Paper One!", "aliases": ["nc0"]},
        {"id": "nc2", "title": "paper one"},
    ]))
    merged = scrape_site.keep_previous([{"id": "nc3", "title": "Paper One"}], str(path))
    assert merged == [{"id": "nc3", "title": "Paper One", "aliases": ["nc0", "nc1", "nc2"]}]


def test_keep_previous_drops_unverified_missing_titles(tmp_path):
    path = tmp_path / "papers.json"
    path.write_text(json.dumps([{"id": "nc1", "title": "Old paper"}]))
    assert scrape_site.keep_previous([{"id": "nc2", "title": "New paper"}], str(path)) == [
        {"id": "nc2", "title": "New paper"},
    ]


def test_keep_previous_verifies_missing_pages_and_rejects_changed_titles(tmp_path, monkeypatch):
    path = tmp_path / "papers.json"
    path.write_text(json.dumps([
        {"id": "nc1", "title": "Still available", "abstract": "outdated"},
        {"id": "nc2", "title": "Unavailable"},
        {"id": "nc3", "title": "Reused identifier"},
    ]))

    def page(session, url):
        rid = url.rsplit("/", 1)[-1]
        if rid == "2":
            raise scrape_site.requests.HTTPError("404 Not Found")
        title = "Still available" if rid == "1" else "A different paper"
        return (f'<div class="hero-card poster"><h1>{title}</h1><div>Alice ⋅ Bob</div>'
                f'<div>Hall C1</div></div><div class="abstract-text-inner">{ABS}</div>')

    monkeypatch.setattr(scrape_site, "get", page)
    merged = scrape_site.keep_previous([], str(path), session=object())
    assert len(merged) == 1
    assert merged[0]["id"] == "nc1" and merged[0]["title"] == "Still available"
    assert merged[0]["abstract"] == ABS.strip()
    assert merged[0]["authors"] == "Alice, Bob"
    assert merged[0]["site"] == "Atlanta"
