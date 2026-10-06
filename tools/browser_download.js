// Fallback for when scrape.py is refused with "ChallengeRequiredError".
// 1. Open https://openreview.net in a normal browser tab and let the page load
//    (that is what passes the bot check).
// 2. Open the developer console (F12), paste this whole file, press Enter.
// 3. A file neurips2026_raw.json is downloaded. Move it into this repository and run
//        python scrape.py --raw neurips2026_raw.json
(async () => {
  const venues = {
    "Main track": "NeurIPS.cc/2026/Conference",
    "Evaluations & Datasets": "NeurIPS.cc/2026/Evaluations_and_Datasets_Track",
  };
  const PAGE = 1000;
  const out = [];
  for (const [track, id] of Object.entries(venues)) {
    for (let offset = 0; ; offset += PAGE) {
      const url = "https://api2.openreview.net/notes?content.venueid=" +
        encodeURIComponent(id) + "&limit=" + PAGE + "&offset=" + offset;
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) { console.error(track, r.status, await r.text()); break; }
      const { notes } = await r.json();
      notes.forEach(note => out.push({ track, note }));
      console.log(track, out.length, "notes so far");
      if (notes.length < PAGE) break;
    }
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out)], { type: "application/json" }));
  a.download = "neurips2026_raw.json";
  a.click();
  console.log("done:", out.length, "notes");
})();
