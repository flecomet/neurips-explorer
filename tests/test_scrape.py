import json
import pathlib

import pytest

import scrape

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "openreview_notes.json"


@pytest.fixture
def notes():
    return json.loads(FIXTURE.read_text())["notes"]


def test_parse_full_note(notes):
    p = scrape.parse_note(notes[0], "Main track")
    assert p["id"] == "AbC123xyz"
    assert p["title"] == "Sparse Attention for Long Contexts"  # whitespace collapsed
    assert p["abstract"] == "We study sparse attention. It is faster."
    assert p["authors"] == "Ada Example, Grace Sample"
    assert p["pdf_link"] == "https://openreview.net/pdf/abc123.pdf"
    assert p["forum_link"] == "https://openreview.net/forum?id=AbC123xyz"
    assert p["keywords"] == ["attention", "efficiency"]
    assert p["tldr"] == "Sparse attention is fast."
    assert p["area"] == "deep_learning_architectures"
    assert p["decision"] == "spotlight"
    assert p["track"] == "Main track"


def test_parse_minimal_note(notes):
    p = scrape.parse_note(notes[1], "Main track")
    assert p["keywords"] == [] and p["tldr"] == "" and p["area"] == ""
    assert p["pdf_link"] == ""
    assert p["decision"] == "other"  # "NeurIPS 2026 Conference" is not a presentation type


@pytest.mark.parametrize("venue,expected", [
    ("NeurIPS 2026 oral", "oral"),
    ("NeurIPS 2026 Poster", "poster"),
    ("", "other"),
    (None, "other"),
])
def test_parse_decision(venue, expected):
    assert scrape.parse_decision(venue) == expected


class FakeSession:
    """Serves `notes` page by page and records the offsets requested."""

    def __init__(self, notes, fail_first=0, status=0):
        self.notes, self.offsets, self.fail_first, self.status = notes, [], fail_first, status

    def get(self, url, params, timeout):
        class Resp:
            headers = {"Retry-After": "0", "server": "test"}
            url = "https://example.invalid/notes"
            text = "forbidden body"

            def __init__(self, status, body):
                self.status_code, self._body = status, body

            def raise_for_status(self):
                assert self.status_code < 400

            def json(self):
                return self._body

        if self.status:
            return Resp(self.status, {})
        if self.fail_first:
            self.fail_first -= 1
            return Resp(429, {})
        off, lim = params["offset"], params["limit"]
        self.offsets.append(off)
        return Resp(200, {"notes": self.notes[off : off + lim]})


def test_fetch_venue_paginates(notes, monkeypatch):
    monkeypatch.setattr(scrape, "PAGE_SIZE", 1)
    session = FakeSession(notes)
    papers = scrape.fetch_venue(session, "X/2026/Conference", "Main track")
    assert [p["id"] for p in papers] == ["AbC123xyz", "Zzz999"]
    assert session.offsets == [0, 1, 2]  # last page is empty, which ends the loop


def test_fetch_venue_retries_on_rate_limit(notes):
    session = FakeSession(notes, fail_first=2)
    assert len(scrape.fetch_venue(session, "X", "t")) == 2


def test_client_error_reports_status_and_body():
    with pytest.raises(scrape.ApiError) as err:
        scrape.fetch_venue(FakeSession([], status=403), "X", "t")
    assert "HTTP 403" in str(err.value) and "forbidden body" in str(err.value)
