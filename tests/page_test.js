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
// Wave years are build-time derived (newest first); fall back for old snapshots.
const YEARS = [...new Set(bills.map(b => b.wave).filter(Boolean))].sort().reverse();
const WAVE_IDS = DATA.wave_years && DATA.wave_years.length
  ? DATA.wave_years
  : [...YEARS, "all"];
const DEF_WAVE = DATA.default_wave || (WAVE_IDS.length ? WAVE_IDS[0] : "2026");
const DEF_SET = ["signed", "vetoed"];
const defCount = cnt(DEF_WAVE, "signed") + cnt(DEF_WAVE, "vetoed");
const pendAll = cnt("all", "pending");
const pendDef = cnt(DEF_WAVE, "pending");
const vetoAll = bills.filter(b => b.status === "vetoed").length;
const ALL_IDX = WAVE_IDS.indexOf("all");

// ---------- minimal DOM stubs ----------
let failures = 0;
function check(cond, msg) {
  if (cond) { console.log("  ok  -", msg); }
  else { failures++; console.error("  FAIL- ", msg); }
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
  el.querySelectorAll = () => [];
  el.focus = () => {};
  el.addEventListener = (ev, fn) => { (el._listeners[ev] ||= []).push(fn); };
  el.click = () => (el._listeners.click || []).forEach(fn => fn({}));
  el.press = key =>
    (el._listeners.keydown || []).forEach(fn =>
      fn({ key, preventDefault: () => {} }));
  return el;
}

function makeEnv(search) {
  const els = {};
  for (const id of ["updatedAt", "sessionFlag", "stat-veto", "n-veto", "stat-sign", "n-sign",
                    "stat-pend", "n-pend", "waves", "q", "countnote", "wavenote", "list",
                    "topicControl", "topicTrigger", "topicValue", "topicMenu"]) {
    els[id] = makeElement(id);
  }
  const waveButtons = WAVE_IDS.map(w => {
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
                    Date, Set, Map, URLSearchParams, JSON, RegExp, Number, String,
                    // Synchronous timers so input-driven renders are immediate.
                    setTimeout: fn => { fn(); return 0; },
                    clearTimeout: () => {} };
  window.location = location;
  vm.createContext(sandbox);
  return { els, waveButtons, statEls, location, history, window, sandbox };
}

function runPage(search) {
  const env = makeEnv(search);
  vm.runInContext(scriptSrc, env.sandbox, { filename: "page-script.js" });
  return env;
}

function fakeOption(topic) {
  const opt = { dataset: { topic }, closest: sel => (sel === ".topic-option" ? opt : null) };
  return opt;
}

const rows = el => (el.innerHTML.match(/<div class="row(?: [^\"]*)?">/g) || []).length;
const pressed = el => el.getAttribute("aria-pressed") === "true";

// ---------- scenario A: fresh load, no params ----------
console.log("A: default load (no URL params)");
{
  const e = runPage("");
  check(rows(e.els.list) === defCount,
        `default shows signed+vetoed ${DEF_WAVE}-wave bills: ${defCount} (got ${rows(e.els.list)})`);
  check(e.els.countnote.textContent === `Showing ${defCount} of ${defCount}`,
        `countnote default (got \u201c${e.els.countnote.textContent}\u201d)`);
  check(pressed(e.els["stat-sign"]) && e.els["stat-sign"].classList.contains("active"), "Signed card active by default");
  check(pressed(e.els["stat-veto"]) && e.els["stat-veto"].classList.contains("active"), "Vetoed card active by default");
  check(!pressed(e.els["stat-pend"]) && !e.els["stat-pend"].classList.contains("active"), "Pending card off by default");
  check(e.els.list.innerHTML.includes("class=\"author-link\"") &&
        e.els.list.innerHTML.includes("https://calmatters.digitaldemocracy.org/bills#author="),
        "author labels link to Digital Democracy author filters");
  check(e.els.list.innerHTML.includes("session_year%5B%5D=" + DATA.session.replace(/^(\d{4})(\d{4})$/, "$1-$2")),
        "author links carry the session from the data");
  check(e.els.list.innerHTML.includes('class="row signed"'),
        "signed bill rows carry the signed outline class");
  check(e.els.sessionFlag.textContent.includes(DATA.session_label),
        `session flag comes from the data (got \u201c${e.els.sessionFlag.textContent}\u201d)`);
  check(e.history.calls.length === 0, "URL stays clean on default load");
}

// ---------- scenario B: load with ?status=pending&wave=all&q=… ----------
console.log("B: load with ?status=pending&wave=all&q=education");
{
  const e = runPage("?status=pending&wave=all&q=education");
  check(e.els.q.value === "education", "search box pre-filled from ?q");
  check(e.waveButtons[ALL_IDX].classList.contains("on"), "\u201cAll session\u201d wave tab selected");
  check(pressed(e.els["stat-pend"]) && !pressed(e.els["stat-sign"]) && !pressed(e.els["stat-veto"]),
        "only Pending card active");
  const expected = bills.filter(b =>
    b.status === "pending" &&
    [b.measure, b.title, b.author, b.author_info && b.author_info.name,
      b.plain_summary || "", ...(b.topics || []), b.action || ""].join(" ").toLowerCase().includes("education")
  ).length;
  const n = rows(e.els.list);
  check(n === expected, `pending \u201ceducation\u201d matches = ${expected} (got ${n})`);
  check(e.els.countnote.textContent === `Showing ${expected} of ${pendAll}`,
        `countnote against all ${pendAll} pending (got \u201c${e.els.countnote.textContent}\u201d)`);
}

// ---------- scenario C: topic filter ----------
console.log("C: topic filter updates list + URL");
{
  const e = runPage("");
  const expected = bills.filter(b => b.wave === DEF_WAVE &&
    ["signed", "vetoed"].includes(b.status) && (b.topics || []).includes("Health")).length;
  // Drive the real menu: open the trigger, click an option.
  e.els.topicTrigger.click();
  e.els.topicMenu._listeners.click.forEach(fn => fn({ target: fakeOption("Health") }));
  check(e.history.calls.at(-1) === "?topic=Health", `URL now ?topic=Health (got ${e.history.calls.at(-1)})`);
  check(rows(e.els.list) === expected, `Health topic filter = ${expected} (got ${rows(e.els.list)})`);
  check(e.els.topicValue.textContent === "Health", "topic trigger label stays in sync");

  e.location.search = "?topic=Housing&wave=all";
  e.window.fire("popstate");
  check(e.els.topicValue.textContent === "Housing" && e.waveButtons[ALL_IDX].classList.contains("on"),
        "popstate applies topic and wave");
}

// ---------- scenario D: toggling ----------
console.log("D: toggling statuses updates list + URL");
{
  const e = runPage("");
  e.els["stat-sign"].click();                       // signed off
  check(pressed(e.els["stat-veto"]) && !pressed(e.els["stat-sign"]), "click Signed toggles it off");
  check(e.history.calls.at(-1) === "?status=vetoed", `URL now ?status=vetoed (got ${e.history.calls.at(-1)})`);
  const vetoDef = cnt(DEF_WAVE, "vetoed");
  check(rows(e.els.list) === vetoDef && (vetoDef === 0 ? e.els.countnote.textContent === "No matches" : true),
        `vetoed-only ${DEF_WAVE} wave = ${vetoDef} (got ${rows(e.els.list)})`);

  e.els["stat-veto"].click();                       // last one: guard no-op
  check(pressed(e.els["stat-veto"]), "cannot deselect the last remaining status");

  e.els["stat-pend"].click();                       // pending on
  check(e.history.calls.at(-1) === "?status=vetoed,pending",
        `URL canonical order vetoed,pending (got ${e.history.calls.at(-1)})`);
  check(rows(e.els.list) === vetoDef + pendDef, "vetoed+pending count adds up");

  e.els["stat-veto"].click();                       // vetoed off
  check(e.history.calls.at(-1) === "?status=pending", `URL ?status=pending (got ${e.history.calls.at(-1)})`);
  e.els["stat-sign"].click();                       // signed on
  check(e.history.calls.at(-1) === "?status=signed,pending", `URL ?status=signed,pending (got ${e.history.calls.at(-1)})`);
  e.els["stat-pend"].click();                       // pending off -> signed only
  check(e.history.calls.at(-1) === "?status=signed", `URL ?status=signed (got ${e.history.calls.at(-1)})`);
  e.els["stat-veto"].click();                       // -> back to default set
  check(e.history.calls.at(-1) === "/newsom-bill-tracker/",
        `URL params dropped when back to default (got ${e.history.calls.at(-1)})`);
  check(rows(e.els.list) === defCount, "list back to default count");
}

// ---------- scenario E: wave + combined params ----------
console.log("E: wave switching + combined URL");
{
  const e = runPage("");
  e.els["stat-sign"].click();                       // vetoed only
  const idx25 = WAVE_IDS.indexOf("2025");
  if (idx25 >= 0) {
    e.waveButtons[idx25].click();                   // 2025 wave
    check(e.history.calls.at(-1) === "?status=vetoed&wave=2025",
          `URL ?status=vetoed&wave=2025 (got ${e.history.calls.at(-1)})`);
    check(rows(e.els.list) === cnt("2025", "vetoed"),
          `2025-wave vetoes = ${cnt("2025", "vetoed")} (got ${rows(e.els.list)})`);
    check(e.els.wavenote.innerHTML.includes("2025 wave"), "2025 wave note shown");
  } else {
    check(true, "no 2025 wave in this snapshot; skipping");
  }
  e.waveButtons[WAVE_IDS.indexOf(DEF_WAVE)].click(); // back to default wave
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
  check(e.waveButtons[ALL_IDX].classList.contains("on"), "popstate applies ?wave=all");
  check(rows(e.els.list) === vetoAll, "all vetoes listed across waves");
  check(e.els.list.innerHTML.includes('class="row vetoed"'),
        "vetoed bill rows carry the vetoed outline class");
}

// ---------- scenario H: invalid params fall back to defaults ----------
console.log("H: invalid URL params ignored");
{
  const e = runPage("?status=bogus&wave=1999&q=");
  check(rows(e.els.list) === defCount, "garbage params fall back to defaults");
  check(!e.els.q.value, "empty ?q leaves search box empty");
}

// ---------- scenario I: gov-announced action on a pending bill ----------
console.log("I: pending bills with an announced action say so");
{
  const flagged = bills.filter(b => b.status === "pending" && b.gov_action);
  if (flagged.length) {
    const e = runPage("?status=pending&wave=all");
    check(e.els.list.innerHTML.includes("Governor's office announced:"),
          "announced-action note rendered for pending bills");
    const vetoFlagged = flagged.filter(b => b.gov_action === "vetoed" && b.gov_msg_url);
    if (vetoFlagged.length) {
      check(e.els.list.innerHTML.includes("Veto letter"),
            "veto letter link offered while LegInfo is still pending");
    }
  } else {
    check(true, "no announced-but-pending bills in this snapshot; skipping");
  }
}

// ---------- scenario J: topic menu keyboard navigation ----------
console.log("J: topic menu arrow keys + Enter");
{
  const e = runPage("");
  e.els.topicTrigger.press("ArrowDown");            // opens, active = "All topics"
  check(e.els.topicControl.classList.contains("open"), "ArrowDown opens the topic menu");
  check(e.els.topicTrigger.getAttribute("aria-activedescendant") === "topic-opt-0",
        `activedescendant starts at option 0 (got ${e.els.topicTrigger.getAttribute("aria-activedescendant")})`);
  e.els.topicMenu.press("ArrowDown");               // -> Agriculture
  e.els.topicMenu.press("ArrowDown");               // -> Budget
  check(e.els.topicTrigger.getAttribute("aria-activedescendant") === "topic-opt-2",
        `two ArrowDowns land on option 2 (got ${e.els.topicTrigger.getAttribute("aria-activedescendant")})`);
  e.els.topicMenu.press("Enter");
  check(e.history.calls.at(-1) === "?topic=Budget", `Enter selects Budget (got ${e.history.calls.at(-1)})`);
  check(!e.els.topicControl.classList.contains("open"), "menu closes after selection");
  check(rows(e.els.list) === bills.filter(b => b.wave === DEF_WAVE &&
        ["signed", "vetoed"].includes(b.status) && (b.topics || []).includes("Budget")).length,
        "Budget topic list rendered");
  // Escape closes without selecting.
  e.els.topicTrigger.click();
  check(e.els.topicControl.classList.contains("open"), "click reopens the menu");
  e.els.topicMenu.press("Escape");
  check(!e.els.topicControl.classList.contains("open"), "Escape closes the menu");
  check(e.history.calls.at(-1) === "?topic=Budget", "Escape did not change the topic");
}

// ---------- scenario K: long summaries are clipped on the card ----------
console.log("K: card explanations stay under the length cap");
{
  const longest = bills.reduce((a, b) =>
    ((b.plain_summary || "").length > (a.plain_summary || "").length ? b : a), bills[0]);
  const e = runPage(`?q=${encodeURIComponent(longest.measure)}&wave=all&status=signed,vetoed,pending`);
  check(rows(e.els.list) >= 1,
        `searching the longest-explanation measure renders rows (got ${rows(e.els.list)})`);
  const unesc = s => s.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'");
  const summaries = [...e.els.list.innerHTML.matchAll(
    /<div class="summary">([\s\S]*?)<\/div>/g
  )].map(m => unesc(m[1]).replace(/<[^>]+>/g, "").trim());
  check(summaries.length > 0, "summaries rendered on the rows");
  const maxLen = summaries.length ? Math.max(...summaries.map(s => s.length)) : 0;
  check(maxLen <= 485, `no card explanation exceeds the cap (longest ${maxLen})`);
  if ((longest.plain_summary || "").length > 480) {
    check(summaries.some(s => s.endsWith("\u2026")),
          "over-long explanations are clipped with an ellipsis");
  }
}

console.log(failures ? `\n${failures} FAILURE(S)` : "\nALL CHECKS PASSED");
process.exit(failures ? 1 : 0);
