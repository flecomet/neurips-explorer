#!/usr/bin/env node
// Records docs/img/demo.gif from the built site in site/ and writes the
// opening frame to docs/img/map.png, which the README shows above the GIF.
// Needs Node 22+, ffmpeg, and a Chromium binary (set CHROMIUM to override "chromium").
// Build the site first with build_site.py so the recording matches templates/index.html.

import { spawn } from "node:child_process";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const siteDir = join(repo, "site");
const output = join(repo, "docs", "img", "demo.gif");
const stillOutput = join(repo, "docs", "img", "map.png");
const chromium = process.env.CHROMIUM || "chromium";
const workdir = await mkdtemp(join(process.env.DEMO_TMP || tmpdir(), "demo-"));

// Large enough that the map and the side panel are readable at README width.
const WIDTH = 1920;
const HEIGHT = 1200;
const HTTP_PORT = 8765;
const DEBUG_PORT = 9333;
const QUERY = "diffusion";
const START_MS = 1200; // initial full map before typing
const TYPE_GAP_MS = 160; // pause after each typed character
const HOLD_MS = 2500; // highlighted result shown before the loop restarts
const FPS = 12;

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

async function waitFor(check, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await check()) return;
    await sleep(200);
  }
  throw new Error(`timed out waiting for ${label}`);
}

// Minimal DevTools protocol client; Node 22 provides WebSocket globally.
function connect(url) {
  return new Promise((resolveConnect, rejectConnect) => {
    const ws = new WebSocket(url);
    const pending = new Map();
    let nextId = 0;
    ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !pending.has(message.id)) return;
      const { resolve: ok, reject: fail } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) fail(new Error(message.error.message));
      else ok(message.result);
    });
    ws.addEventListener("error", rejectConnect);
    ws.addEventListener("open", () =>
      resolveConnect({
        send(method, params = {}) {
          return new Promise((ok, fail) => {
            nextId += 1;
            pending.set(nextId, { resolve: ok, reject: fail });
            ws.send(JSON.stringify({ id: nextId, method, params }));
          });
        },
        close: () => ws.close(),
      }),
    );
  });
}

const servers = [];
const frames = [];
let cdp = null;

try {
  servers.push(
    spawn("python3", ["-m", "http.server", String(HTTP_PORT), "--bind", "127.0.0.1", "--directory", siteDir], {
      stdio: "ignore",
    }),
  );
  await waitFor(
    () => fetch(`http://127.0.0.1:${HTTP_PORT}/index.html`).then((r) => r.ok, () => false),
    15000,
    "the local site server",
  );

  servers.push(
    spawn(
      chromium,
      [
        "--headless=new",
        "--no-sandbox",
        "--hide-scrollbars",
        `--window-size=${WIDTH},${HEIGHT}`,
        `--remote-debugging-port=${DEBUG_PORT}`,
        `--user-data-dir=${join(workdir, "profile")}`,
        "about:blank",
      ],
      { stdio: "ignore" },
    ),
  );
  await waitFor(
    () => fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`).then((r) => r.ok, () => false),
    30000,
    "Chromium DevTools endpoint",
  );
  const targets = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`)).json();
  const page = targets.find((target) => target.type === "page");
  cdp = await connect(page.webSocketDebuggerUrl);

  await cdp.send("Page.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: WIDTH,
    height: HEIGHT,
    deviceScaleFactor: 1,
    mobile: false,
  });
  // The page picks its theme from this preference when no theme is saved.
  await cdp.send("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-color-scheme", value: "dark" }],
  });
  await cdp.send("Page.navigate", { url: `http://127.0.0.1:${HTTP_PORT}/index.html` });

  const evaluate = async (expression) =>
    (await cdp.send("Runtime.evaluate", { expression, returnByValue: true })).result.value;

  // The search box is disabled until the data and the plot have loaded.
  await waitFor(
    () => evaluate("!!document.getElementById('search') && !document.getElementById('search').disabled"),
    60000,
    "the search box to enable",
  );
  await sleep(500);

  const recordStart = Date.now();
  async function capture() {
    // PNG keeps every frame in one format, since ffmpeg's concat input decodes all frames as the first frame's format.
    const { data } = await cdp.send("Page.captureScreenshot", { format: "png" });
    const name = `f${String(frames.length).padStart(4, "0")}.png`;
    await writeFile(join(workdir, name), Buffer.from(data, "base64"));
    frames.push({ name, at: (Date.now() - recordStart) / 1000 });
  }
  // Screenshots take whatever time they take, so each frame keeps its real timestamp.
  async function recordFor(ms) {
    const end = Date.now() + ms;
    do await capture();
    while (Date.now() < end);
  }

  // The README still and the GIF's first frame are the same PNG, so the GIF opens on the image above it.
  const still = Buffer.from((await cdp.send("Page.captureScreenshot", { format: "png" })).data, "base64");
  await writeFile(stillOutput, still);
  await writeFile(join(workdir, "f0000.png"), still);
  frames.push({ name: "f0000.png", at: 0 });
  await sleep(START_MS);
  await evaluate("document.getElementById('search').focus()");
  for (const character of QUERY) {
    await cdp.send("Input.insertText", { text: character });
    await recordFor(TYPE_GAP_MS);
  }
  await recordFor(HOLD_MS);

  const typed = await evaluate("document.getElementById('search').value");
  const highlighted = await evaluate("document.getElementById('filter-count').textContent");
  if (typed !== QUERY) throw new Error(`search box holds "${typed}", expected "${QUERY}"`);
  console.log(`typed "${typed}", page reports: ${highlighted}`);
  console.log(`captured ${frames.length} frames in ${((Date.now() - recordStart) / 1000).toFixed(1)} s`);

  // Each frame is shown until the next one starts; the last frame is shown for one average interval.
  const averageGap = frames.at(-1).at / (frames.length - 1);
  const lines = frames.map((frame, i) => {
    const next = frames[i + 1];
    const duration = next ? next.at - frame.at : averageGap;
    return `file '${frame.name}'\nduration ${duration.toFixed(3)}`;
  });
  lines.push(`file '${frames.at(-1).name}'`);
  await writeFile(join(workdir, "frames.txt"), lines.join("\n") + "\n");

  const ffmpeg = (args) =>
    new Promise((ok, fail) => {
      const child = spawn("ffmpeg", ["-v", "error", "-y", ...args], { stdio: "inherit" });
      child.on("exit", (code) => (code === 0 ? ok() : fail(new Error(`ffmpeg exited with ${code}`))));
    });
  const scale = `fps=${FPS},scale=${WIDTH}:-1:flags=lanczos`;
  const concat = ["-f", "concat", "-safe", "0", "-i", join(workdir, "frames.txt")];
  await ffmpeg([...concat, "-vf", `${scale},palettegen=stats_mode=diff`, join(workdir, "palette.png")]);
  await ffmpeg([
    ...concat,
    "-i",
    join(workdir, "palette.png"),
    "-lavfi",
    `${scale}[frames];[frames][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle`,
    "-loop",
    "0",
    output,
  ]);
  console.log(`wrote ${output}`);
} finally {
  cdp?.close();
  for (const child of servers) child.kill();
  if (!process.env.DEMO_KEEP_FRAMES) await rm(workdir, { recursive: true, force: true });
}
