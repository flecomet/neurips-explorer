"""Settings shared by every pipeline script."""

NAME = "NeurIPS 2026"
SLUG = "neurips_2026"
YEAR = 2026

PAPERS_PATH = f"data/{SLUG}_papers.json"
EMBEDDINGS_PATH = f"data/{SLUG}_specter2.npy"
LAYOUT_PATH = f"data/{SLUG}_layout.json"
SITE_DIR = "site"

# Values substituted into templates/index.html by build_site.py.
REPO_URL = "https://github.com/flecomet/neurips-explorer"
SOURCE_NAME = "neurips.cc"
SOURCE_URL = "https://neurips.cc/virtual/2026/papers.html"
STORAGE_PREFIX = "neurips-explorer"
CSV_NAME = "neurips2026-saved.csv"

# Track label -> OpenReview venue id. Accepted papers carry their venue id in
# `content.venueid`. A venue id that returns no papers is reported and skipped,
# so the second entry (a guess at the 2026 id, modelled on the 2025
# "Datasets_and_Benchmarks_Track") is harmless if it is wrong. Check the real
# id on https://openreview.net/group?id=NeurIPS.cc/2026 and override with
# `python scrape.py --venue "Label=venue/id"` if needed.
VENUES = {
    "Main track": "NeurIPS.cc/2026/Conference",
    "Evaluations & Datasets": "NeurIPS.cc/2026/Evaluations_and_Datasets_Track",
}

OPENREVIEW_API = "https://api2.openreview.net"
OPENREVIEW_URL = "https://openreview.net"

# neurips.cc virtual site (used while OpenReview has not released the 2026 papers). Its listing
# pages build their cards with JavaScript from two JSON files, which are read directly.
SITE_URL = "https://neurips.cc"
SITE_YEAR = 2026
SITE_PAPERS_JSON = f"{SITE_URL}/static/virtual/data/neurips-{SITE_YEAR}-orals-posters.json"
SITE_ABSTRACTS_JSON = f"{SITE_URL}/static/virtual/data/neurips-{SITE_YEAR}-abstracts.json"
SITE_LOCATIONS = ["Sydney", "Atlanta", "Paris"]
