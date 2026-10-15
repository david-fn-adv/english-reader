// jsdom render test, driven by tools/qa.py. Prints a JSON report; exit 0 pass, 1 fail.
//   node tools/qa_render.js index.html 2026-10-16
"use strict";
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const [, , htmlPath, articleId] = process.argv;
const html = fs.readFileSync(path.resolve(htmlPath), "utf8");
const errors = [];
const vc = new VirtualConsole();
vc.on("error", (...a) => errors.push(a.map(String).join(" ")));
vc.on("jsdomError", (e) => errors.push("jsdomError: " + (e && e.message)));

const dom = new JSDOM(html, {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  url: "https://x.test/",
  virtualConsole: vc,
  beforeParse(window) {
    // layout APIs jsdom does not implement; the reader calls them on navigation
    window.scrollTo = () => {};
    window.HTMLElement.prototype.scrollIntoView = function () {};
  },
});
const { window } = dom;
const doc = window.document;
const fails = [];
const report = { article: articleId };

function finish() {
  report.console_errors = errors;
  if (errors.length) fails.push(`${errors.length} console error(s)`);
  report.fails = fails;
  report.pass = fails.length === 0;
  process.stdout.write(JSON.stringify(report, null, 1) + "\n");
  window.close();
  process.exit(report.pass ? 0 : 1);
}

window.addEventListener("load", () => {
  try {
    const P = JSON.parse(doc.getElementById("data").textContent);
    const art = (P.articles || []).find((a) => a.id === articleId);
    if (!art) { fails.push(`article ${articleId} not in payload`); return finish(); }

    // payload-level checks
    const figs = new Set((art.source.figures || []).map((f) => f.id));
    const badFig = [], noFig = [], noDict = new Set(), noName = new Set();
    art.blocks.forEach((b) => b.sents.forEach((s) => s.forEach((t) => {
      if (t.fig && !figs.has(t.fig)) badFig.push(t.w);
      if (/\d/.test(t.w) && !t.fig) noFig.push(t.w);
      if (t.l) {
        const d = P.dict[t.l];
        if (!d || !d.en || !d.vi || !d.ipa) noDict.add(t.l);
      }
      if (t.n && !(P.names[t.n] && P.names[t.n].vi)) noName.add(t.n);
    })));
    if (noName.size) fails.push(`names without an entry: ${[...noName].join(", ")}`);
    if (badFig.length) fails.push(`fig ids not in source.figures: ${badFig.join(", ")}`);
    if (noFig.length) fails.push(`numbers without fig: ${noFig.join(", ")}`);
    if (noDict.size) fails.push(`lemmas without populated dict entry: ${[...noDict].join(", ")}`);

    // the list shows the new card
    const card = doc.querySelector(`.card[data-id="${articleId}"]`);
    report.card = !!card;
    if (!card) fails.push("article card missing from the list");

    // open the article through the UI and tap every token
    card && card.click();
    window.dispatchEvent(new window.HashChangeEvent("hashchange"));
    const toks = [...doc.querySelectorAll("#scr-reader .t[data-p]")];
    report.tokens = toks.length;
    if (!toks.length) fails.push("reader rendered no tokens");
    const empty = [], wrongName = [];
    for (const el of toks) {
      el.click();
      const vi = doc.querySelector("#sheetBody .vi");
      if (!doc.getElementById("sheet").classList.contains("on") || !vi || !vi.textContent.trim()) empty.push(el.textContent);
      // a name token opens the sheet of the name it belongs to, not of the word
      const [bi, si, ti] = el.getAttribute("data-p").split(".").map(Number);
      const t = art.blocks[bi].sents[si][ti];
      const h2 = doc.querySelector("#sheetBody h2");
      if (t.n && (!h2 || h2.textContent !== t.n)) wrongName.push(`${t.w} -> ${h2 && h2.textContent} (want ${t.n})`);
    }
    if (wrongName.length) fails.push(`name tokens open the wrong sheet: ${wrongName.slice(0, 10).join("; ")}`);
    report.sheets_opened = toks.length - empty.length;
    if (empty.length) fails.push(`tokens with an empty sheet: ${empty.slice(0, 20).join(", ")}`);
    report.paragraphs = doc.querySelectorAll("#scr-reader .para").length;
  } catch (e) {
    fails.push("exception: " + e.message);
  }
  finish();
});
