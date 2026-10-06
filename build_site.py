"""Build the static site payload.

Merges the papers and layout files into two column-oriented JSON files in site/:
  data.json     what the map needs to draw and navigate (loads first)
  details.json  abstracts, authors, keywords, links (loaded afterwards, used by
                search and the paper panel)
Run after the pipeline (scrape.py, embed.py, layout.py).
"""
import json
import os
import statistics

import config

# Presentation levels in display order; anything else is "other".
DECISION_ORDER = ["oral", "spotlight", "poster", "other"]


def intern(values):
    """Replace repeated strings by indices into a table, to keep the payload small."""
    table = sorted(set(values))
    index = {v: i for i, v in enumerate(table)}
    return table, [index[v] for v in values]


def build(papers, layout):
    points = layout["points"]
    assert len(points) == len(papers), f"{len(points)} points != {len(papers)} papers"
    assert len(layout["neighbors"]) == len(papers), "neighbor count != paper count"

    x = [round(p["x"], 3) for p in points]
    y = [round(p["y"], 3) for p in points]
    c = [p["cluster"] for p in points]

    clusters = {}
    for cid, name in layout["clusters"].items():
        idx = [i for i, ci in enumerate(c) if ci == int(cid)]
        if not idx:
            continue
        clusters[cid] = {
            "name": name,
            "n": len(idx),
            # Median, not mean: robust to the stray points UMAP leaves around a cluster.
            "cx": round(statistics.median(x[i] for i in idx), 3),
            "cy": round(statistics.median(y[i] for i in idx), 3),
        }

    dec = [p["decision"] if p["decision"] in DECISION_ORDER else "other" for p in papers]
    decisions = [d for d in DECISION_ORDER if d in dec]
    decision_idx = [decisions.index(d) for d in dec]
    areas, area_idx = intern([p["area"] for p in papers])
    tracks, track_idx = intern([p["track"] for p in papers])

    core = {
        "meta": {"name": config.NAME, "n": len(papers)},
        "clusters": clusters,
        "decisions": decisions,
        "areas": areas,
        "tracks": tracks,
        "id": [p["id"] for p in papers],
        "x": x,
        "y": y,
        "c": c,
        "dec": decision_idx,
        "area": area_idx,
        "track": track_idx,
        "title": [p["title"] for p in papers],
        "nn": layout["neighbors"],
    }
    details = {
        "authors": [p["authors"] for p in papers],
        "abstract": [p["abstract"] for p in papers],
        "tldr": [p["tldr"] for p in papers],
        "kw": [p["keywords"] for p in papers],
        "pdf": [p["pdf_link"] for p in papers],
        "forum": [p["forum_link"] for p in papers],
    }
    return core, details


def main():
    with open(config.PAPERS_PATH) as f:
        papers = json.load(f)
    with open(config.LAYOUT_PATH) as f:
        layout = json.load(f)
    core, details = build(papers, layout)

    os.makedirs(config.SITE_DIR, exist_ok=True)
    for name, payload in (("data.json", core), ("details.json", details)):
        path = os.path.join(config.SITE_DIR, name)
        with open(path, "w") as f:
            json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
        print(f"wrote {path}: {os.path.getsize(path) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
