/* Warranty Claim Explorer: a dependency-free single-page app over the explorer API.
 *
 * Views (hash routes):
 *   #/                              home: counts, suggested starting points
 *   #/entity?iri=...                relationship explorer: graph, related information, details
 *   #/list/<type>?offset=0          paged list of claims, vehicles, parts, dealers, ...
 *   #/questions[/cq03?param=...]    the ten competency questions, runnable with parameters
 *   #/ask?q=...                     natural-language search (Amazon Bedrock), when enabled
 *
 * No third-party scripts: the graph is drawn with plain SVG, so the page works under a strict
 * Content-Security-Policy (script-src 'self') and needs nothing from a CDN.
 */
"use strict";

const ID_BASE = "https://warranty.example.com/id/";
const TYPES = {
  claim:        { label: "Warranty Claim", plural: "Claims",          path: "claim",         color: "#1b3a6b" },
  vehicle:      { label: "Vehicle",        plural: "Vehicles",        path: "vehicle",       color: "#2f7d6d" },
  part:         { label: "Part",           plural: "Parts",           path: "part",          color: "#b7791f" },
  dealer:       { label: "Dealer",         plural: "Dealers",         path: "dealer",        color: "#5a4fcf" },
  repairOrder:  { label: "Repair Order",   plural: "Repair Orders",   path: "repair-order",  color: "#2b78c5" },
  supplier:     { label: "Supplier",       plural: "Suppliers",       path: "supplier",      color: "#b5523b" },
  customer:     { label: "Customer",       plural: "Customers",       path: "customer",      color: "#64748b" },
  partCategory: { label: "Part Category",  plural: "Part Categories", path: "part-category", color: "#6d8a24" },
};
// Result columns that hold a business key, and the entity type they identify.
const KEY_COLUMNS = {
  claimNumber: "claim", relatedClaim: "claim", firstClaim: "claim", repeatClaim: "claim",
  vin: "vehicle", partNumber: "part", dealerCode: "dealer", roNumber: "repairOrder",
  supplierCode: "supplier", customerId: "customer", categoryCode: "partCategory",
};
const MONEY = new Set(["totalCost", "laborCost", "partsCost", "avgCost", "avgClaimCost", "unitCost", "cost"]);
const BARS = { claimRatePct: 100, laborVsStandard: 2 };
const HEADERS = {
  vin: "VIN", roNumber: "RO number", avgMonthsInService: "Avg MIS", monthsInService: "MIS",
  claimRatePct: "Claim rate %", laborVsStandard: "Labor vs standard", iri: "IRI",
};

const state = { config: { apiBase: "/api", nlqEnabled: false, environment: "local" }, stats: null, questions: null };
const view = document.getElementById("view");

/* ------------------------------------------------------------------ helpers */

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined) continue;
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) if (c) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}

function iriFor(type, id) { return ID_BASE + TYPES[type].path + "/" + encodeURIComponent(id); }
function typeOfIri(iri) {
  const path = (iri || "").slice(ID_BASE.length).split("/")[0];
  return Object.keys(TYPES).find((k) => TYPES[k].path === path);
}
function entityHref(iri) { return "#/entity?iri=" + encodeURIComponent(iri); }
function humanize(name) {
  if (HEADERS[name]) return HEADERS[name];
  const s = name.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
function fmt(col, v) {
  if (v === null || v === undefined || v === "") return "";
  if (MONEY.has(col) && typeof v === "number") return "$" + v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (typeof v === "number" && /year/i.test(col)) return String(v);
  if (typeof v === "number") return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(v);
}
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

async function api(path, params) {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  const resp = await fetch(state.config.apiBase + path + qs, { headers: { Accept: "application/json" } });
  const body = await resp.json().catch(() => ({ error: resp.statusText }));
  if (!resp.ok) throw new Error(body.error || resp.statusText);
  return body;
}

function loading(msg = "Loading…") { return el("div", { class: "loading" }, el("span", { class: "spinner" }), msg); }
function errorBox(err) { return el("div", { class: "error" }, "Something went wrong: ", String(err.message || err)); }

/* ------------------------------------------------------------------ icons */

const ICONS = {
  claim: [["path", { d: "M6.5 3h7.5l4 4v14h-11.5z M14 3v4h4 M9.5 11.5h5.5 M9.5 15h5.5 M9.5 18h3.5" }]],
  vehicle: [["path", { d: "M3 16.5v-3.3l2.1-4.3A2 2 0 0 1 6.9 7.8h10.2a2 2 0 0 1 1.8 1.1l2.1 4.3v3.3z M3.5 13h17" }],
            ["circle", { cx: 7.3, cy: 17, r: 1.9 }], ["circle", { cx: 16.7, cy: 17, r: 1.9 }]],
  part: [["circle", { cx: 12, cy: 12, r: 5 }], ["circle", { cx: 12, cy: 12, r: 1.8 }],
         ["path", { d: "M12 2.5v3.2 M12 18.3v3.2 M2.5 12h3.2 M18.3 12h3.2 M5.3 5.3l2.2 2.2 M16.5 16.5l2.2 2.2 M5.3 18.7l2.2-2.2 M16.5 7.5l2.2-2.2" }]],
  dealer: [["path", { d: "M3 10.5l9-6.5 9 6.5 M5 10v10.5h14V10 M10 20.5V15h4v5.5" }]],
  repairOrder: [["path", { d: "M8.5 3.5h7v3h-7z M7 5H5v16.5h14V5h-2 M8.5 11.5h7 M8.5 15h7 M8.5 18.5h4" }]],
  supplier: [["path", { d: "M3 21V11.5l5 3v-3l5 3v-3l5 3V4.5h3V21z M2.5 21h19 M7 18h1.5 M11.5 18H13 M16 18h1.5" }]],
  customer: [["circle", { cx: 12, cy: 8, r: 3.8 }], ["path", { d: "M4.5 21c0-4.2 3.4-6.8 7.5-6.8s7.5 2.6 7.5 6.8" }]],
  partCategory: [["path", { d: "M3.5 12.2V3.5h8.7l9 9-8.7 8.7z" }], ["circle", { cx: 8, cy: 8, r: 1.6 }]],
  search: [["circle", { cx: 10.5, cy: 10.5, r: 6.5 }], ["path", { d: "M15.5 15.5L21 21" }]],
  questions: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M9.3 9.3a2.8 2.8 0 1 1 3.9 2.6c-.8.4-1.2 1-1.2 1.8v.8 M12 17.2v.3" }]],
  ask: [["path", { d: "M4 5h16v11H9.5L4 20z M8.5 10.5h.1 M12 10.5h.1 M15.5 10.5h.1" }]],
};
function icon(name, attrs = {}) {
  const g = svg("svg", { viewBox: "0 0 24 24", class: "icon", "aria-hidden": "true", ...attrs });
  for (const [tag, a] of ICONS[name] || []) g.append(svg(tag, a));
  return g;
}
document.querySelectorAll("[data-icon]").forEach((n) => n.append(icon(n.dataset.icon)));

/* ------------------------------------------------------------------ tables */

function cellFor(col, value) {
  const td = el("td");
  const t = KEY_COLUMNS[col] || (col === "number" && /^C-/.test(value) ? "claim"
          : col === "number" && /^RO-/.test(value) ? "repairOrder" : null);
  if (t && value) {
    td.append(el("a", { href: entityHref(iriFor(t, value)) }, String(value)));
  } else if (BARS[col] !== undefined && typeof value === "number") {
    const bar = el("span", { class: "bar" });
    bar.style.width = Math.max(2, Math.min(100, (value / BARS[col]) * 100)) + "%";
    td.append(el("div", { class: "bar-cell" }, el("div", { class: "bar-track" }, bar), el("span", {}, fmt(col, value))));
    td.className = "num";
  } else {
    td.append(fmt(col, value));
    if (typeof value === "number") td.className = "num";
  }
  return td;
}

function table(columns, rows, { onRow } = {}) {
  if (!rows.length) return el("div", { class: "empty" }, "No rows.");
  const head = el("tr", {}, columns.map((c) => el("th", {}, humanize(c))));
  const body = rows.map((r) => {
    const tr = el("tr", onRow ? { class: "clickable", onclick: (e) => { if (e.target.tagName !== "A") onRow(r); } } : {},
      columns.map((c) => cellFor(c, r[c])));
    return tr;
  });
  return el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, body)));
}

/* ------------------------------------------------------------------ graph */

function wrapLabel(text, max = 22) {
  const s = String(text || "");
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function drawGraph(host, data) {
  clear(host);
  const W = Math.max(host.clientWidth, 520);
  const H = Math.max(440, Math.min(data.nodes.some((n) => n.hop) ? 640 : 600, W * 0.7));
  const cx = W / 2, cy = H / 2;
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "graph", role: "img",
                            "aria-label": `Relationships of ${data.center.label}` });
  const center = data.nodes.find((n) => n.center);
  const ring1 = data.nodes.filter((n) => !n.center && !n.hop);
  const ring2 = data.nodes.filter((n) => n.hop === 2);
  const pos = new Map([[center.iri, { x: cx, y: cy }]]);
  const r1 = Math.min(W, H) * (ring2.length ? 0.31 : 0.37);
  const stretch = Math.min(1.7, W / H);                   // use the width: an ellipse, not a circle
  const many = ring1.length > 12;
  ring1.forEach((n, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(ring1.length, 1);
    const r = many && i % 2 ? r1 * 1.18 : r1 * 0.95;
    pos.set(n.iri, { x: cx + Math.cos(a) * r * stretch, y: cy + Math.sin(a) * r, a });
  });
  // Second-hop nodes continue outward from their parent, fanned out when a parent has several.
  const children = new Map();
  ring2.forEach((n) => {
    const edge = data.edges.find((e) => e.target === n.iri && e.hop === 2);
    if (edge && pos.get(edge.source)) {
      if (!children.has(edge.source)) children.set(edge.source, []);
      children.get(edge.source).push(n);
    }
  });
  for (const [parentIri, kids] of children) {
    const parent = pos.get(parentIri);
    kids.forEach((n, k) => {
      // Lean toward the horizontal: there is more room left and right than above and below.
      const side = Math.cos(parent.a) >= 0 ? 0 : Math.PI;
      const lean = parent.a + (side - (parent.a > Math.PI ? parent.a - 2 * Math.PI : parent.a)) * 0.5;
      const a = lean + (k - (kids.length - 1) / 2) * 0.5;
      const d = Math.min(W, H) * 0.21;
      pos.set(n.iri, { x: parent.x + Math.cos(a) * d * stretch, y: parent.y + Math.sin(a) * d, a });
    });
  }
  for (const p of pos.values()) {   // keep everything inside the canvas
    p.x = Math.max(70, Math.min(W - 70, p.x));
    p.y = Math.max(p.y < cy - 20 ? 96 : 56, Math.min(H - 62, p.y));
  }

  const edges = svg("g", { class: "edges" });
  const labels = svg("g", { class: "edge-labels" });
  const perPredicate = {};
  data.edges.forEach((e) => { perPredicate[e.predicate] = (perPredicate[e.predicate] || 0) + 1; });
  const labelled = new Set();
  data.edges.forEach((e) => {
    const a = pos.get(e.source), b = pos.get(e.target);
    if (!a || !b) return;
    edges.append(svg("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: e.hop === 2 ? "edge hop2" : "edge" }));
    // Repeated relationships (12 claims on one part) get one label, not twelve.
    if (perPredicate[e.predicate] <= 2 || !labelled.has(e.predicate)) {
      labelled.add(e.predicate);
      const t = e.source === center.iri ? 0.6 : 0.5;     // nearer the neighbor, away from the center label
      labels.append(svg("text", { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t - 3, class: "edge-label",
                                  "text-anchor": "middle" }, e.label));
    }
  });
  root.append(edges, labels);

  const nodes = svg("g", { class: "nodes" });
  data.nodes.forEach((n) => {
    const p = pos.get(n.iri);
    if (!p) return;
    const r = n.center ? 38 : n.hop ? 20 : 25;
    const color = (TYPES[n.type] || {}).color || "#475569";
    const g = svg("g", { class: "node" + (n.center ? " center" : ""), transform: `translate(${p.x},${p.y})`,
                         tabindex: 0, role: "link",
                         onclick: () => { if (!n.center) location.hash = entityHref(n.iri); },
                         onkeydown: (ev) => { if (ev.key === "Enter" && !n.center) location.hash = entityHref(n.iri); } },
      svg("title", {}, `${n.typeLabel}: ${n.label} (${n.identifier})`),
      svg("circle", { r, fill: color, class: "node-disc" }));
    const ic = icon(n.type, { x: -r * 0.55, y: -r * 0.55, width: r * 1.1, height: r * 1.1, class: "node-icon" });
    g.append(ic);
    // Labels go below the node, except for nodes in the upper part of the canvas, where the
    // edge arrives from below: there they go above so the line never crosses the text.
    const above = !n.center && p.y < cy - 20;
    const hasId = n.label !== n.identifier && n.type !== "vehicle";
    const y0 = above ? -r - (hasId ? 38 : 24) : r + 14;
    g.append(svg("text", { y: y0, "text-anchor": "middle", class: "node-type" }, n.typeLabel),
             svg("text", { y: y0 + 15, "text-anchor": "middle", class: "node-label" },
                 wrapLabel(n.type === "vehicle" ? "VIN " + n.identifier : n.label, n.center ? 30 : 24)));
    if (hasId) {
      g.append(svg("text", { y: y0 + 29, "text-anchor": "middle", class: "node-id" }, wrapLabel(n.identifier, 24)));
    }
    nodes.append(g);
  });
  root.append(nodes);
  host.append(root);
}

/* ------------------------------------------------------------------ views */

async function viewHome() {
  const stats = state.stats || (state.stats = await api("/stats"));
  const cards = ["claim", "vehicle", "part", "dealer", "repairOrder", "supplier", "customer"].map((t) =>
    el("a", { class: "stat", href: "#/list/" + t },
      el("span", { class: "stat-ico" }, icon(t)),
      el("span", { class: "stat-n" }, (stats.counts[t] || 0).toLocaleString()),
      el("span", { class: "stat-l" }, TYPES[t].plural)));
  const starts = [
    ["Start with claim C-100245", "A water pump claim at Prosper Meridian. Follow it to the vehicle, part, supplier and 60 related claims.", entityHref(iriFor("claim", "C-100245"))],
    ["Which build month is the problem?", "CQ09 finds the San Marcos build window where water pump claims cluster.", "#/questions/cq09"],
    ["Who should we contact first?", "CQ10 lists vehicles from that window that have not failed yet, with owners and dealers.", "#/questions/cq10"],
    ["Which dealers book too much labor?", "CQ07 compares booked hours with each part's standard labor time.", "#/questions/cq07"],
  ];
  return el("section", { class: "home" },
    el("div", { class: "hero" },
      el("p", { class: "eyebrow" }, "From disconnected data to connected insights"),
      el("h1", {}, "Discover how claims, vehicles, dealers, repairs and parts connect"),
      el("p", { class: "lede" }, "Every record here is a node in one knowledge graph that follows the warranty business ontology. ",
        "Search for any claim, VIN, part, dealer or supplier, then follow the relationships.")),
    el("div", { class: "stats" }, cards),
    el("p", { class: "stat-foot" }, `${stats.triples.toLocaleString()} triples · $${Math.round(stats.totalClaimCost).toLocaleString()} total claim cost`),
    el("h2", {}, "Good places to start"),
    el("div", { class: "starts" }, starts.map(([t, d, href]) =>
      el("a", { class: "start", href }, el("strong", {}, t), el("span", {}, d), el("span", { class: "go" }, "Open →")))));
}

function panelRows(rows) {
  return el("dl", { class: "panel-rows" }, rows.filter((r) => r.value !== undefined && r.value !== null && r.value !== "")
    .map((r) => [el("dt", {}, r.label), el("dd", {}, fmt(r.key || "", r.value))]));
}

async function viewEntity(params) {
  const iri = params.get("iri");
  const type = typeOfIri(iri);
  const graphHost = el("div", { class: "graph-host" }, loading("Loading relationships…"));
  const side = el("aside", { class: "panel" }, loading());
  const details = el("section", { class: "details" });
  const head = el("div", { class: "entity-head" });
  const page = el("section", { class: "explore" }, head, el("div", { class: "explore-grid" },
    el("div", { class: "graph-card" }, graphHost, el("div", { class: "legend" },
      Object.entries(TYPES).map(([k, t]) => { const dot = el("span", { class: "dot" }); dot.style.background = t.color; return el("span", {}, dot, t.label); }))),
    side), details);

  (async () => {
    try {
      const data = await api("/neighborhood", { iri });
      const c = data.center;
      head.append(el("span", { class: "chip" }, icon(c.type), c.typeLabel),
                  el("h1", {}, c.type === "vehicle" ? c.identifier : c.label));
      if (c.label !== c.identifier) head.append(el("span", { class: "sub" }, c.type === "vehicle" ? c.label : c.identifier));
      drawGraph(graphHost, data);
      window.addEventListener("resize", () => drawGraph(graphHost, data), { once: true });
      details.append(el("h2", {}, "Details"),
        el("div", { class: "attr-grid" }, c.attributes.map((a) =>
          el("div", { class: "attr" }, el("span", { class: "attr-l" }, humanize(a.property)), el("span", { class: "attr-v" }, fmt(a.property, a.value))))),
        el("p", { class: "classes" }, "Types (with inferred superclasses): ", c.classes.join(" · ")));
      if (type !== "claim") {
        clear(side).append(el("h2", {}, "Related Information"), panelRows([
          ...c.attributes.slice(1, 6).map((a) => ({ label: humanize(a.property), value: a.value, key: a.property })),
          ...data.relations.map((r) => ({ label: r.label.charAt(0).toUpperCase() + r.label.slice(1), value: r.total })),
        ]));
        const big = data.relations.filter((r) => r.total > r.shown);
        if (big.length) side.append(el("p", { class: "note" }, big.map((r) => `Graph shows ${r.shown} of ${r.total} “${r.label}”.`).join(" ")));
      }
    } catch (err) { clear(graphHost).append(errorBox(err)); }
  })();

  if (type === "claim") {
    (async () => {
      try {
        const rel = await api("/related", { iri });
        const btn = el("button", { class: "primary", type: "button" }, `View Related Claims (${rel.relatedClaims.length}) →`);
        const relHost = el("div");
        btn.addEventListener("click", () => {
          clear(relHost).append(el("h2", { id: "related" }, "Related claims: same causal part, same model"),
            el("p", { class: "muted" }, "Competency question CQ03. Sorted by build date: notice where they cluster."),
            table(["relatedClaim", "claimDate", "vin", "modelYear", "plant", "buildDate", "dealer", "monthsInService", "failureCode"], rel.relatedClaims));
          relHost.scrollIntoView({ behavior: "smooth" });
        });
        clear(side).append(el("h2", {}, "Related Information"),
          panelRows(rel.panel.map((r) => ({ ...r, key: r.label }))),
          el("dl", { class: "panel-rows compact" },
            el("dt", {}, "Total cost"), el("dd", {}, fmt("totalCost", rel.claim.totalCost)),
            el("dt", {}, "Status"), el("dd", {}, rel.claim.status),
            el("dt", {}, "Owner"), el("dd", {}, rel.claim.owner || "")),
          btn);
        details.after(relHost);
      } catch (err) { clear(side).append(errorBox(err)); }
    })();
  }
  return page;
}

async function viewList(type, params) {
  const offset = Number(params.get("offset") || 0);
  const data = await api("/entities", { type, offset, limit: 50 });
  const pager = el("div", { class: "pager" },
    el("span", {}, `${offset + 1}–${Math.min(offset + data.rows.length, data.total)} of ${data.total.toLocaleString()}`),
    el("a", { class: "btn" + (offset === 0 ? " disabled" : ""), href: `#/list/${type}?offset=${Math.max(0, offset - 50)}` }, "← Previous"),
    el("a", { class: "btn" + (offset + 50 >= data.total ? " disabled" : ""), href: `#/list/${type}?offset=${offset + 50}` }, "Next →"));
  return el("section", { class: "list" },
    el("div", { class: "list-head" }, el("h1", {}, icon(type), TYPES[type].plural), pager),
    table(data.columns, data.rows, { onRow: (r) => { location.hash = entityHref(r.iri); } }));
}

async function viewQuestions(id, params) {
  const qs = state.questions || (state.questions = await api("/competency"));
  const current = qs.find((q) => q.id === id) || qs[0];
  const list = el("ol", { class: "cq-list" }, qs.map((q) =>
    el("li", { class: q.id === current.id ? "active" : "" },
      el("a", { href: "#/questions/" + q.id }, el("span", { class: "cq-id" }, q.id.toUpperCase()), q.title))));
  const form = el("form", { class: "cq-form" });
  current.params.forEach((p) => {
    form.append(el("label", {}, humanize(p.name),
      el("input", { name: p.name, value: params.get(p.name) || p.default, pattern: p.pattern.replace(/^\^|\$$/g, ""), required: true })));
  });
  const out = el("div", { class: "cq-out" });
  const run = async () => {
    clear(out).append(loading("Running SPARQL…"));
    const values = Object.fromEntries(new FormData(form).entries());
    try {
      const r = await api("/competency/" + current.id, values);
      clear(out).append(
        el("div", { class: "cq-meta" }, `${r.rows.length} rows · ${r.elapsedMs} ms`),
        table(r.columns, r.rows),
        el("details", { class: "sparql" }, el("summary", {}, "SPARQL"), el("pre", {}, el("code", {}, r.sparql))));
    } catch (err) { clear(out).append(errorBox(err)); }
  };
  form.append(el("button", { class: "primary", type: "submit" }, "Run question"));
  form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
  run();
  return el("section", { class: "questions" },
    el("div", { class: "cq-side" }, el("h2", {}, "Competency questions"),
      el("p", { class: "muted" }, "The business questions the ontology and graph must answer. Each is a SPARQL file in queries/competency/."), list),
    el("div", { class: "cq-main" },
      el("p", { class: "eyebrow" }, current.id.toUpperCase()),
      el("h1", {}, current.title),
      el("p", { class: "question" }, current.question),
      el("p", { class: "value" }, el("strong", {}, "Why it matters: "), current.value),
      form, out));
}

async function viewAsk(params) {
  const q = params.get("q") || "";
  const examples = ["Which dealers submitted the most water pump claims?",
    "What is the average claim cost by model?",
    "Which suppliers have parts with claims in the first 6 months of service?",
    "List the repair orders at Tyler Meridian for infotainment head units"];
  const input = el("textarea", { rows: 2, placeholder: "Ask a question about warranty claims…" });
  input.value = q;
  const out = el("div", { class: "ask-out" });
  const ask = async () => {
    const question = input.value.trim();
    if (question.length < 3) return;
    history.replaceState(null, "", "#/ask?q=" + encodeURIComponent(question));
    clear(out).append(loading("Writing and running a SPARQL query with Amazon Bedrock…"));
    try {
      const resp = await fetch(state.config.apiBase + "/nlq", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
      const r = await resp.json();
      if (!resp.ok) throw new Error(r.error || resp.statusText);
      const cols = r.rows && r.rows.length ? Object.keys(r.rows.reduce((a, row) => Object.assign(a, row), {})) : [];
      clear(out).append(
        r.error ? errorBox(new Error(r.error)) : el("p", { class: "answer" }, r.answer || `${r.rows.length} rows.`),
        r.explanation ? el("p", { class: "muted" }, r.explanation) : null,
        r.rows && r.rows.length ? table(cols, r.rows) : null,
        el("details", { class: "sparql", open: !!r.error }, el("summary", {}, "Generated SPARQL"), el("pre", {}, el("code", {}, r.sparql || ""))),
        el("p", { class: "fine" }, `Model: ${r.model}. Queries are read-only and checked before they run.`));
    } catch (err) { clear(out).append(errorBox(err)); }
  };
  const disabled = !state.config.nlqEnabled;
  const page = el("section", { class: "ask" },
    el("p", { class: "eyebrow" }, "Natural language search · Amazon Bedrock"),
    el("h1", {}, "Ask a question"),
    disabled ? el("div", { class: "notice" }, state.config.environment === "local"
      ? "Natural-language search is off in local mode. Run scripts/serve_local.py --bedrock with AWS credentials that can call Amazon Bedrock."
      : "Natural-language search is not deployed. Deploy with -c nlq=true.") : null,
    el("form", { class: "ask-form", onsubmit: (e) => { e.preventDefault(); ask(); } }, input,
      el("button", { class: "primary", type: "submit", disabled }, "Ask")),
    el("div", { class: "chips" }, examples.map((x) => el("button", { type: "button", class: "chip-btn", disabled,
      onclick: () => { input.value = x; ask(); } }, x))),
    out);
  if (q && !disabled) ask();
  return page;
}

/* ------------------------------------------------------------------ search box */

const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
let searchTimer = null, searchSeq = 0;

function looksLikeQuestion(text) { return text.trim().split(/\s+/).length >= 4 || /\?$/.test(text.trim()); }

async function runSearch() {
  const text = searchInput.value.trim();
  const seq = ++searchSeq;
  if (text.length < 2) { searchResults.hidden = true; return; }
  const items = [];
  if (state.config.nlqEnabled && looksLikeQuestion(text)) {
    items.push(el("a", { class: "sr ask-item", href: "#/ask?q=" + encodeURIComponent(text), role: "option" },
      icon("ask"), el("span", {}, el("strong", {}, "Ask: "), text)));
  }
  try {
    const r = await api("/search", { q: text });
    if (seq !== searchSeq) return;
    r.results.forEach((h) => items.push(el("a", { class: "sr", href: entityHref(h.iri), role: "option" },
      el("span", { class: "sr-ico" }, icon(h.type)),
      el("span", { class: "sr-main" }, el("strong", {}, h.type === "vehicle" ? h.identifier : h.label),
        el("small", {}, h.typeLabel + (h.label !== h.identifier ? " · " + (h.type === "vehicle" ? h.label : h.identifier) : ""))))));
  } catch (err) { /* keep the ask item */ }
  clear(searchResults).append(...(items.length ? items : [el("div", { class: "sr empty" }, "No matches")]));
  searchResults.hidden = false;
}
searchInput.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 220); });
searchInput.addEventListener("focus", () => { if (searchResults.childElementCount) searchResults.hidden = false; });
document.addEventListener("click", (e) => { if (!searchForm.contains(e.target)) searchResults.hidden = true; });
searchForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const first = searchResults.querySelector("a.sr:not(.ask-item)") || searchResults.querySelector("a.sr");
  if (!searchResults.hidden && first) { location.hash = first.getAttribute("href"); }
  else if (state.config.nlqEnabled && looksLikeQuestion(searchInput.value)) location.hash = "#/ask?q=" + encodeURIComponent(searchInput.value);
  else { await runSearch(); const f = searchResults.querySelector("a.sr"); if (f) location.hash = f.getAttribute("href"); }
  searchResults.hidden = true;
});
searchResults.addEventListener("click", () => { searchResults.hidden = true; });

/* ------------------------------------------------------------------ router */

async function route() {
  const hash = location.hash.slice(1) || "/";
  const [path, query] = hash.split("?");
  const params = new URLSearchParams(query || "");
  const parts = path.split("/").filter(Boolean);
  const section = parts[0] === "list" ? parts[1] : parts[0] === "entity" ? typeOfIri(params.get("iri")) : parts[0] || "home";
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === section));
  clear(view).append(loading());
  try {
    let node;
    if (parts[0] === "entity") node = await viewEntity(params);
    else if (parts[0] === "list" && TYPES[parts[1]]) node = await viewList(parts[1], params);
    else if (parts[0] === "questions") node = await viewQuestions(parts[1], params);
    else if (parts[0] === "ask") node = await viewAsk(params);
    else node = await viewHome();
    clear(view).append(node);
    view.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  } catch (err) { clear(view).append(errorBox(err)); }
}

(async function start() {
  try {
    const resp = await fetch("config.json", { cache: "no-store" });
    if (resp.ok) Object.assign(state.config, await resp.json());
  } catch (err) { /* defaults */ }
  document.getElementById("env-badge").textContent = state.config.environment === "aws" ? "AWS · Amazon Neptune" : "Local · in-memory graph";
  document.getElementById("nav-ask").classList.toggle("off", !state.config.nlqEnabled);
  window.addEventListener("hashchange", route);
  route();
})();
