# NeurIPS 2026 Explorer

A 2D semantic map of the accepted NeurIPS 2026 papers, built from
[SPECTER2](https://huggingface.co/allenai/specter2) embeddings of titles and abstracts.
Nearby points are semantically similar papers, so a cluster is a topic.

**Live site (after setup, see below): https://flecomet.github.io/neurips-explorer/**

> Derived from [flecomet/cvpr-explorer](https://github.com/flecomet/cvpr-explorer), itself a
> fork of [dataplayer12/cvpr-explorer](https://github.com/dataplayer12/cvpr-explorer). Original
> idea and design credit to [@dataplayer12](https://github.com/dataplayer12). Same license
> as upstream, see [LICENSE](LICENSE).

## Status

The code is unit-tested; the paper data has not been generated yet.

- **OpenReview** has not released the 2026 papers (the venue group has `public_submissions = false`,
  and every 2026 query returns 0 notes while 2025 returns papers). It also answers scripts running
  on GitHub's servers with a human-verification challenge. `scrape.py` (OpenReview) is kept for
  when the papers are published.
- **neurips.cc** already lists the accepted papers per location (Sydney, Atlanta, Paris). Its
  listing pages are rendered by JavaScript from two JSON files
  (`/static/virtual/data/neurips-2026-orals-posters.json` and `...-abstracts.json`), which
  `scrape_site.py` downloads. The abstract extraction from a paper page was checked against the real
  site. The layout of the two JSON files was not known when the parser was written, so field names
  are looked up from lists of likely candidates, and every run prints the structure it found.
  `python scrape_site.py --probe` prints that structure without writing anything.

## Features

- Map of all papers with topic names drawn on it; more names appear as you zoom in.
- Color by topic, location (Sydney / Atlanta / Paris), presentation type (oral / spotlight / poster, also encoded by marker size)
  or OpenReview primary area. Palette for presentation type is colorblind-safe.
- Topics list: click a topic to zoom to it and list its papers.
- Search over titles, authors, keywords, TL;DR and abstracts. Matches stay in place, the rest dim.
- Paper panel: abstract, TL;DR, keywords (click to search), PDF and OpenReview links, and the six
  most similar papers.
- Save papers to a list kept in the browser (localStorage), export as CSV or Markdown.
- Shareable URLs: `?p=<paper id>`, `?q=<search>`, `?c=<topic>`, `?color=<mode>`.
- Light and dark themes, keyboard shortcuts (`/` search, `Esc` clear), usable on a phone.
- Fast start: the map (`data.json`, a few hundred KB gzipped) loads first, abstracts
  (`details.json`) load afterwards.

## How it works

The pipeline is offline and the site is static (no backend, no API keys at serve time).

| Step | Script | Output |
|------|--------|--------|
| Fetch accepted papers from neurips.cc (or OpenReview) | `scrape_site.py` (`scrape.py`) | `data/neurips_2026_papers.json` |
| Embed title + abstract with SPECTER2 | `embed.py` | `data/neurips_2026_specter2.npy` (float16) |
| UMAP to 2D, HDBSCAN clusters, TF-IDF topic names, nearest neighbours | `layout.py` | `data/neurips_2026_layout.json` |
| Merge into the site payload | `build_site.py` | `site/data.json`, `site/details.json` |

`site/index.html` renders the payload client-side with plotly.js.

## Setup

1. Create the GitHub repository (public: GitHub Pages is free only for public repositories),
   push this code to `main`.
2. Settings, Pages, Source: **GitHub Actions**.
3. Actions tab, **Refresh data**, Run workflow with source `neurips.cc`. It runs the whole pipeline
   on a GitHub runner (embedding on CPU takes tens of minutes), commits `data/`, and starts the
   Pages deployment. The **Probe neurips.cc** step prints what the site returned; if the scrape
   step then fails, that output shows what the parser needs to change.
4. Other sources: `committed` uses `data/neurips_2026_papers.json` as it is in the repository.
   `openreview` does not work from GitHub runners (human-verification challenge). Once OpenReview
   publishes the papers, scrape from your own machine with `python scrape.py`, or from a browser:
   open https://openreview.net, paste [`tools/browser_download.js`](tools/browser_download.js) into
   the developer console, then run `python scrape.py --raw neurips2026_raw.json`. Commit the data
   and run the workflow with source `committed`. The venue ids are in [`config.py`](config.py).

## Run locally

```shell
pip install -r requirements-pipeline.txt
python scrape_site.py   # neurips.cc; for OpenReview: python scrape.py
python embed.py         # GPU recommended, CPU works
python layout.py        # --min-cluster-size 25 --n-neighbors 15
python build_site.py
python -m http.server -d site 8000   # http://localhost:8000
```

Tests: `pip install -r requirements-dev.txt && python -m pytest`.

## Notes

- `layout.py` is deterministic for fixed inputs (UMAP `random_state=42`) so reruns keep the map
  stable. Changing the embeddings or paper set changes the map.
- Roughly a third of papers can end up "unclustered" at `--min-cluster-size 25`. Lower it for
  more, smaller topics.
- Saved papers never leave the browser.
