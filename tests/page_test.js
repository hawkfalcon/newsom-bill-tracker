#!/usr/bin/env node
/* Behavioral tests for the Newsom Bill Watch page script.
 * Usage: node tests/page_test.js index.html
 *
 * Stubs a minimal DOM, executes the page's inline <script> in a VM context,
 * then drives the UI (clicks, keyboard, URL state, popstate) and asserts on
 * the rendered counts / URL the page produces. Expected counts are derived
 * from the DATA embedded in the page, so the tests work on any snapshot.
 */
"use strict";
const fs = require("fs");
const vm = require("vm");

const file = process.argv[2];
if (!file) { console.error("usage: node page_test.js <index.html>"); process.exit(2); }
const html = fs.readFileSync(file, "utf-8");

const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error("FAIL: no <script> block found"); process.exit(1); }
const scriptSrc = m[1];

/* Extract the DATA object the build injects, for computing expectations. */
const dm = scriptSrc.match(/const DATA = (\{.*?\});\n/s);
if (!dm) { console.error("FAIL: could not locate embedded DATA"); process.exit(1); }
const DATA = JSON.parse(dm[1].replace(/\\u003c/g, "<"));
const bills = DATA.bills;
const cnt = (wave, status) => bills.filter(b =>
  (wave === "all" || b.wave === wave) && b.status === status).length;
const DEF_WAVE = "2026";
const DEF_SET = ["signed", "vetoed"];
const defCount = cnt(DEF_WAVE, "signed") + cnt(DEF_WAVE, "vetoed");
const pendAll = cnt("all", "pending");
const veto2025 = cnt("2025", "vetoed");
const veto2026 = cnt(DEF_WAVE, "vetoed");

// ---------- minimal DOM stubs ----------
let failures = 0;
function check(cond, msg) {
  if (cond) { console.log("  ok  -", msg); }
  else { failures++; console.error("  FAIL-", msg); }
}

function makeElement(id, extra = {}) {
  const el = {
    id,
    textContent: "",
    innerHTML: "",
    value: "",
    _attrs: {},
    _classes: new Set(),
    _listeners: {},
    dataset: {},
    ...extra,
  };
  el.classList = {
    add: c => el._classes.add(c),
    remove: c => el._classes.delete(c),
    toggle: (c, on) => (on === undefined
      ? (el._classes.has(c) ? el._classes.delete(c) : el._classes.add(c))
      : (on ? el._classes.add(c) : el._classes.delete(c))),
    contains: c => el._classes.has(c),
  };
  el.setAttribute = (k, v) => { el._attrs[k] = String(v); };
  el.getAttribute = k => (k in el._attrs ? el._attrs[k] : null);
  el.addEventListener = (ev, fn) => { (el._listeners[ev] ||= []).push(fn); };
  el.click = () => (el._listeners.click || []).forEach(fn => fn({}));
  el.change = () => (el._listeners.change || []).forEach(fn => fn({target: el}));
  el.press = key =>
    (el._listeners.keydown || []).forEach(fn =>
      fn({ key, preventDefault: () => {} }));
  return el;
}

function makeEnv(search) {
  const els = {};
  for (const id of ["updatedAt", "stat-veto", "n-veto", "stat-sign", "n-sign",
                    "stat-pend", "n-pend", "waves", "q", "topicFilter", "countnote", "wavenote", "list"]) {
    els[id] = makeElement(id);
  }
  const waveButtons = ["2026", "2025", "all"].map(w => {
    const b = makeElement("wave-" + w);
    b.dataset.wave = w;
    return b;
  });
  const statEls = [els["stat-veto"], els["stat-sign"], els["stat-pend"]];
  const controls = makeElement("controls");
  controls.scrollIntoView = () => {};

  const location = { pathname: "/newsom-bill-tracker/", search };
  const history = {
    calls: [],
    replaceState(_s, _t, url) {
      history.calls.push(url);
      if (url.startsWith("?")) location.search = url;
      else if (url.startsWith("/")) { location.pathname = url; location.search = ""; }
    },
  };
  const window = {
    scrollY: 0,
    _listeners: {},
    addEventListener(ev, fn) { (this._listeners[ev] ||= []).push(fn); },
    fire(ev) { (this._listeners[ev] || []).forEach(fn => fn({})); },
  };
  const document = {
    getElementById: id => els[id],
    querySelector: sel => (sel === ".controls" ? controls : null),
    querySelectorAll: sel => {
      if (sel === "#waves button") return waveButtons;
      if (sel === ".stat") return statEls;
      return [];
    },
  };
  const sandbox = { document, window, location, history, console,
                    Date, Set, Map, URLSearchParams, JSON, RegExp, Number, String };
  window.location = location;
  vm.createContext(sandbox);
  return { els, waveButtons, statEls, location, history, window, sandbox };
}

function runPage(search) {
  const env = makeEnv(search);
  vm.runInContext(scriptSrc, env.sandbox, { filename: "page-script.js" });
  return env;
}

const rows = el => (el.innerHTML.match(/<div class="row">/g) || []).length;
const pressed = el => el.getAttribute("aria-pressed") === "true";

// ---------- scenario A: fresh load, no params ----------
console.log("A: default load (no URL params)");
{
  const e = runPage("");
  check(rows(e.els.list) === defCount,
        `default shows signed+vetoed 2026-wave bills: ${defCount} (got ${rows(e.els.list)})`);
  check(e.els.countnote.textContent === `Showing ${defCount} of ${defCount}`,
        `countnote default (got “${e.els.countnote.textContent}”)`);
  check(pressed(e.els["stat-sign"]) && e.els["stat-sign"].classList.contains("active"), "Signed card active by default");
  check(pressed(e.els["stat-veto"]) && e.els["stat-veto"].classList.contains("active"), "Vetoed card active by default");
  check(!pressed(e.els["stat-pend"]) && !e.els["stat-pend"].classList.contains("active"), "Pending card off by default");
  check(e.els.list.innerHTML.includes("class=\"author-link\"") &&
        e.els.list.innerHTML.includes("https://calmatters.digitaldemocracy.org/bills#author="),
        "author labels link to Digital Democracy author filters");
  check(e.history.calls.length === 0, "URL stays clean on default load");
}

// ---------- scenario B: load with ?status=pending&wave=all&q=… ----------
console.log("B: load with ?status=pending&wave=all&q=education");
{
  const e = runPage("?status=pending&wave=all&q=education");
  check(e.els.q.value === "education", "search box pre-filled from ?q");
  check(e.waveButtons[2].classList.contains("on"), "“All session” wave tab selected");
  check(pressed(e.els["stat-pend"]) && !pressed(e.els["stat-sign"]) && !pressed(e.els["stat-veto"]),
        "only Pending card active");
  const expected = bills.filter(b =>
    b.status === "pending" &&
    [b.measure, b.title, b.author, b.author_info && b.author_info.name,
      ...(b.topics || []), b.action || ""].join(" ").toLowerCase().includes("education")
  ).length;
  const n = rows(e.els.list);
  check(n === expected, `pending “education” matches = ${expected} (got ${n})`);
  check(e.els.countnote.textContent === `Showing ${expected} of ${pendAll}`,
        `countnote against all ${pendAll} pending (got “${e.els.countnote.textContent}”)`);
}

// ---------- scenario C: topic filter ----------
console.log("C: topic filter updates list + URL");
{
  const e = runPage("");
  const expected = bills.filter(b => b.wave === DEF_WAVE &&
    ["signed", "vetoed"].includes(b.status) && (b.topics || []).includes("Health")).length;
  e.els.topicFilter.value = "Health";
  e.els.topicFilter.change();
  check(e.history.calls.at(-1) === "?topic=Health", `URL now ?topic=Health (got ${e.history.calls.at(-1)})`);
  check(rows(e.els.list) === expected, `Health topic filter = ${expected} (got ${rows(e.els.list)})`);
  check(e.els.topicFilter.value === "Health", "topic select stays in sync");

  e.location.search = "?topic=Housing&wave=all";
  e.window.fire("popstate");
  check(e.els.topicFilter.value === "Housing" && e.waveButtons[2].classList.contains("on"),
        "popstate applies topic and wave");
}

// ---------- scenario D: toggling ----------
console.log("D: toggling statuses updates list + URL");
{
  const e = runPage("");
  e.els["stat-sign"].click();                       // signed off
  check(pressed(e.els["stat-veto"]) && !pressed(e.els["stat-sign"]), "click Signed toggles it off");
  check(e.history.calls.at(-1) === "?status=vetoed", `URL now ?status=vetoed (got ${e.history.calls.at(-1)})`);
  check(rows(e.els.list) === veto2026 && (veto2026 === 0 ? e.els.countnote.textContent === "No matches" : true),
        `vetoed-only 2026 wave = ${veto2026} (got ${rows(e.els.list)})`);

  e.els["stat-veto"].click();                       // last one: guard no-op
  check(pressed(e.els["stat-veto"]), "cannot deselect the last remaining status");

  e.els["stat-pend"].click();                       // pending on
  check(e.history.calls.at(-1) === "?status=vetoed,pending",
        `URL canonical order vetoed,pending (got ${e.history.calls.at(-1)})`);
  check(rows(e.els.list) === veto2026 + pendAll, "vetoed+pending count adds up");

  e.els["stat-veto"].click();                       // vetoed off
  check(e.history.calls.at(-1) === "?status=pending", `URL ?status=pending (got ${e.history.calls.at(-1)})`);
  e.els["stat-sign"].click();                       // signed on
  check(e.history.calls.at(-1) === "?status=signed,pending", `URL ?status=signed,pending (got ${e.history.calls.at(-1)})`);
  e.els["stat-pend"].click();                       // pending off → signed only
  check(e.history.calls.at(-1) === "?status=signed", `URL ?status=signed (got ${e.history.calls.at(-1)})`);
  e.els["stat-veto"].click();                       // → back to default set
  check(e.history.calls.at(-1) === "/newsom-bill-tracker/",
        `URL params dropped when back to default (got ${e.history.calls.at(-1)})`);
  check(rows(e.els.list) === defCount, "list back to default count");
}

// ---------- scenario E: wave + combined params ----------
console.log("E: wave switching + combined URL");
{
  const e = runPage("");
  e.els["stat-sign"].click();                       // vetoed only
  e.waveButtons[1].click();                         // 2025 wave
  check(e.history.calls.at(-1) === "?status=vetoed&wave=2025",
        `URL ?status=vetoed&wave=2025 (got ${e.history.calls.at(-1)})`);
  check(rows(e.els.list) === veto2025, `2025-wave vetoes = ${veto2025} (got ${rows(e.els.list)})`);
  check(e.els["wavenote"].innerHTML.includes("2025 wave"), "2025 wave note shown");
  e.waveButtons[0].click();                         // back to 2026
  check(e.history.calls.at(-1) === "?status=vetoed", `wave param removed for default (got ${e.history.calls.at(-1)})`);
}

// ---------- scenario F: keyboard activation ----------
console.log("F: keyboard (Enter/Space) activates cards");
{
  const e = runPage("");
  e.els["stat-sign"].press("Enter");
  check(!pressed(e.els["stat-sign"]), "Enter toggles Signed off");
  e.els["stat-sign"].press(" ");
  check(pressed(e.els["stat-sign"]), "Space toggles Signed back on");
}

// ---------- scenario G: popstate re-sync ----------
console.log("G: popstate re-reads filter state from URL");
{
  const e = runPage("");
  e.location.search = "?status=vetoed&wave=all";
  e.window.fire("popstate");
  check(pressed(e.els["stat-veto"]) && !pressed(e.els["stat-sign"]) && !pressed(e.els["stat-pend"]),
        "popstate applies ?status=vetoed");
  check(e.waveButtons[2].classList.contains("on"), "popstate applies ?wave=all");
  check(rows(e.els.list) === veto2025 + veto2026, "all vetoes listed across waves");
}

// ---------- scenario H: invalid params fall back to defaults ----------
console.log("H: invalid URL params ignored");
{
  const e = runPage("?status=bogus&wave=1999&q=");
  check(rows(e.els.list) === defCount, "garbage params fall back to defaults");
  check(!e.els.q.value, "empty ?q leaves search box empty");
}

console.log(failures ? `\n${failures} FAILURE(S)` : "\nALL CHECKS PASSED");
process.exit(failures ? 1 : 0);
