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

The code is written and unit-tested; the paper data has not been generated yet. The scraper reads
the public [OpenReview](https://openreview.net) API, which was not reachable from the environment
that wrote this repository, so it has not been run against the live NeurIPS 2026 data. Expect to
check the venue ids in [`config.py`](config.py) on the first run (see Setup).

## Features

- Map of all papers with topic names drawn on it; more names appear as you zoom in.
- Color by topic, presentation type (oral / spotlight / poster, also encoded by marker size)
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
| Fetch accepted papers from OpenReview | `scrape.py` | `data/neurips_2026_papers.json` |
| Embed title + abstract with SPECTER2 | `embed.py` | `data/neurips_2026_specter2.npy` (float16) |
| UMAP to 2D, HDBSCAN clusters, TF-IDF topic names, nearest neighbours | `layout.py` | `data/neurips_2026_layout.json` |
| Merge into the site payload | `build_site.py` | `site/data.json`, `site/details.json` |

`site/index.html` renders the payload client-side with plotly.js.

## Setup

1. Create the GitHub repository (public: GitHub Pages is free only for public repositories),
   push this code to `main`.
2. Settings, Pages, Source: **GitHub Actions**.
3. Actions tab, **Refresh data**, Run workflow. It runs the whole pipeline on a GitHub runner
   (embedding on CPU takes tens of minutes), commits `data/`, and starts the Pages deployment.
4. If `scrape.py` fails with HTTP 403, the log shows the server's reply, and the **Probe OpenReview**
   step before it shows whether the 2025 venue is also refused (blocked client or network) or only
   2026. As a fallback, add repository secrets `OPENREVIEW_USERNAME` and `OPENREVIEW_PASSWORD`
   (an OpenReview account); the scraper then logs in before querying.
5. If `scrape.py` reports 0 papers for a track, look up the venue id on
   `https://openreview.net/group?id=NeurIPS.cc/2026`, fix `VENUES` in `config.py`, and rerun.

## Run locally

```shell
pip install -r requirements-pipeline.txt
python scrape.py        # or: python scrape.py --venue "Main track=NeurIPS.cc/2026/Conference"
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
