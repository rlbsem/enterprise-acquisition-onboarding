"use strict";
const $ = (s) => document.querySelector(s),
  E = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
const state = {
  user: null,
  overview: null,
  report: null,
  company: null,
  route: "portfolio",
  admissionFilter: "all",
  companyQuery: "",
};
const labels = {
  portfolio: "Portfolio overview",
  company: "Operating company",
  governance: "Admission & exceptions",
  finance: "Financial reconciliation",
  history: "Reporting history",
};
const money = (value) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: state.report.currency,
    maximumFractionDigits: 0,
  }).format(value / 100);
const date = (value) =>
  new Date(value.length > 10 ? value : value + "T12:00:00Z").toLocaleDateString(
    "en-US",
    { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" },
  );
const month = (value) =>
  new Date(value + "T12:00:00Z").toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
const chip = (text, kind = "info") =>
  `<span class="chip ${kind}">${E(text)}</span>`;
const panel = (title, description, body) =>
  `<section class="panel"><div class="panel-head"><div><h2>${E(title)}</h2><p>${E(description)}</p></div></div>${body}</section>`;
const table = (label, heads, rows) =>
  `<div class="table-wrap" role="region" aria-label="${E(label)}" tabindex="0"><table><thead><tr>${heads.map((h) => `<th scope="col">${E(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("") || `<tr><td colspan="${heads.length}">No records in this publication and scope.</td></tr>`}</tbody></table></div><p class="scroll-hint">Scroll within the table to inspect all columns.</p>`;
const json = (value) => `<pre>${E(JSON.stringify(value, null, 2))}</pre>`;
const sourceButtons = (ids) =>
  `<div class="source-links">${(ids || []).map((id) => `<button class="evidence-button" data-source="${id}">${E((state.report.sources.find((s) => s.event_id === id) || {}).source_id || id)}</button>`).join("")}</div>`;
const selectedPeriod = () => $("#period-select").value;
const selectedRows = (rows) =>
  rows.filter(
    (r) => selectedPeriod() === "all" || r.period === selectedPeriod(),
  );
const currentCompany = () =>
  $("#company-select").value === "all"
    ? state.overview.companies[0].id
    : $("#company-select").value;
function totals() {
  const rows = selectedRows(state.report.totals);
  return Object.fromEntries(
    Object.keys(state.report.totals[0])
      .filter((k) => k.endsWith("_minor"))
      .map((k) => [k, rows.reduce((n, r) => n + r[k], 0)]),
  );
}
function heading(eyebrow, title, description) {
  return `<div class="page-heading"><div><p class="eyebrow">${E(eyebrow)}</p><h1 tabindex="-1">${E(title)}</h1><p class="intro">${E(description)}</p></div>${chip(state.report.status === "reconciled_with_open_variances" ? "Reconciled · open variances" : state.report.status === "scope_excluded" ? "Scope held at publication" : "Reconciled publication", state.report.status !== "reconciled" ? "warn" : "good")}</div>`;
}
function metrics() {
  const t = totals();
  return `<section class="metrics" aria-label="Published financial measures">${[
    ["Commercial bookings", "bookings_minor", "Contractual commitments"],
    [
      "Consolidated net invoicing",
      "consolidated_invoice_minor",
      "After supported eliminations",
    ],
    [
      "Consolidated ERP postings",
      "consolidated_erp_minor",
      "Posted source amounts",
    ],
    ["Allocated cash", "allocated_cash_minor", "Payment allocations only"],
    [
      "Supported eliminations",
      "elimination_minor",
      "Bilateral source evidence",
    ],
  ]
    .map(
      ([label, key, note]) =>
        `<div class="metric"><label>${label}</label><strong data-metric="${key}">${money(t[key])}</strong><small>${note}</small></div>`,
    )
    .join("")}</section>`;
}
function exceptions() {
  const rows = selectedRows(state.report.datasets.reconciliation_variances);
  return (
    rows
      .map(
        (r) =>
          `<article class="exception"><div><h3>${r.code === "erp_posting_difference" ? "ERP posting difference" : r.code === "intercompany_unresolved" ? "Unsupported intercompany candidate" : E(r.code.replaceAll("_", " "))}</h3><p>${E(r.company)} · ${E(r.source_id)} · ${month(r.period)}</p><p>${r.code === "intercompany_unresolved" ? "Required bilateral evidence is incomplete. Retained gross; not eliminated." : "Net invoice and independently posted amount differ. Review remains open."}</p></div><div class="amount">${money(r.amount_minor)}</div></article>`,
      )
      .join("") ||
    `<p class="empty">No open variance in the selected period and scope.</p>`
  );
}
function companyTable() {
  return table(
    "Acquisition admission",
    [
      "Operating company / entity",
      "Acquisition",
      "Current admission",
      "Mapping",
      "Source coverage",
      "Action",
    ],
    state.overview.companies.filter(c => (state.admissionFilter === "all" || admissionLabel(c).toLowerCase() === state.admissionFilter) && `${c.name} ${c.legal_entity}`.toLowerCase().includes(state.companyQuery)).map(
      (c) =>
        `<tr><td><strong>${E(c.name)}</strong><small>${E(c.legal_entity)}</small></td><td>${date(c.acquired_on)}</td><td>${chip(admissionLabel(c), c.admitted ? "good" : "warn")}</td><td>v${c.active_mapping}</td><td>${c.gate.coverage.filter(s => s.complete).length} / ${c.gate.coverage.length} sources</td><td><button data-company="${E(c.id)}">Inspect <span aria-hidden="true">↗</span></button></td></tr>`,
    ),
  );
}
function admissionLabel(c) {
  return c.admitted ? "Admitted" : c.status === "staged" && c.gate.passed ? "Pending" : "Held";
}
function scenarioContext() {
  if (state.report.scenario.id === "multi-company-v1") {
    return panel(
      `Measured portfolio scenario · ${state.overview.companies.length} permitted companies`,
      "January and October 2026 · independently persisted synthetic source records",
      `<p>Different CRM, operations and finance contracts share local customer and invoice IDs. Company scope, reviewed mappings, exact source coverage and acquisition dates determine inclusion.</p><p class="fine">This is a bounded multi-company workload, not an annual revenue census or a production capacity guarantee. Held and pending companies retain their records; their amounts are excluded from the captured publication. Current admission and historical financial inclusion can differ.</p>`,
    );
  }
  const annual = state.report.scenario.id === "annual-2026";
  const profiles = Object.entries(state.report.scenario.profiles);
  return panel(
    annual ? "Annual source scenario · January–December 2026" : "Selected-period correctness scenario",
    annual
      ? "Twelve source months, not twelve months of portfolio ownership. Totals include admitted companies only, from each acquisition date."
      : "January, February and October 2026 are a bounded correctness fixture. These bookings are not annual portfolio revenue.",
    `<p>Three representative operating companies illustrate integration into a larger platform. A 50+ brand platform with $5M–$20M annual operating profiles is business context, not a claim about this dataset or customer deployments.</p>` +
    (annual ? `<div class="scenario-profiles">${profiles.map(([id, amount]) => `<div><strong>${E(state.overview.companies.find(c => c.id === id)?.name || id)}</strong><span>${money(amount)} / year</span><small>Assumed gross billing profile · ${state.report.control[id].admitted ? "admitted, acquisition dates apply" : "held; excluded from published totals"}</small></div>`).join("")}</div><p class="fine">One compressed monthly anchor-contract bundle per company, not a customer census. Profiles are assumptions; bookings, invoicing, postings and cash below are separately calculated source facts. No recognized revenue is modeled.</p>` : `<p class="fine">Use the optional annual demo to inspect twelve-month source economics without changing this verified fixture.</p>`),
  );
}
function portfolio() {
  const companies = state.overview.companies;
  return (
    heading(
      "INVESTMENT / INTEGRATION / REPORTING",
      state.user.role === "sponsor"
        ? "Which acquisitions are ready to report?"
        : "Your operating company, in context.",
      "Current admission is separate from historical financial inclusion. Every figure below comes from a validated, immutable publication.",
    ) +
    scenarioContext() +
    metrics() +
    panel(
      "Acquisition readiness",
      "Live control state · source identity, legal entity and mapping coverage",
      `<div class="portfolio-filters"><div><label for="admission-filter">Admission state</label><select id="admission-filter">${["all", "admitted", "held", "pending"].map(s => `<option value="${s}" ${state.admissionFilter === s ? "selected" : ""}>${s[0].toUpperCase() + s.slice(1)}</option>`).join("")}</select></div><div><label for="company-query">Find company or legal entity</label><input id="company-query" type="search" value="${E(state.companyQuery)}" /></div></div><div id="company-table">${companyTable()}</div>`,
    ) +
    `<div class="grid2">${panel("Exceptions that need a decision", "Distinct exception categories; not a combined accounting loss", exceptions())}${panel("A defensible reporting perimeter", "Source evidence remains visible when a company or transaction is excluded.", `<div class="stat-strip"><div><strong>${companies.filter((c) => c.admitted).length}<span> / ${companies.length}</span></strong><span>currently admitted companies</span></div><div><strong>${state.overview.reports.length}</strong><span>validated reporting versions</span></div></div><div class="callout"><strong>What was known at ${date(state.report.cutoff)}</strong><br>Current controls may change. Published source inputs and exclusions do not.</div><button data-nav="history">Inspect reporting history →</button>`)}</div>`
  );
}
function sourceTable(c) {
  return table(
    "Source coverage",
    ["Source", "Owned domain", "Projected records", "Current mapping"],
    c.systems.map(
      (s) =>
        `<tr><td>${E(s.source)}</td><td>${E(s.domain)}</td><td>${c.source_records.filter((r) => r.source === s.source).length}</td><td>v${c.company.active_mapping}</td></tr>`,
    ),
  );
}
function companyPage(c) {
  const published = state.report.control[c.company.id];
  const local = selectedRows(state.report.datasets.legal_entity_totals).filter(
    (r) => r.company === c.company.id,
  );
  return (
    heading(
      "OPERATING COMPANY",
      c.company.name,
      `${c.company.legal_entity} · Acquired ${date(c.company.acquired_on)} · Mapping v${c.company.active_mapping}`,
    ) +
    `<div class="notice">Current admission: <strong>${c.company.admitted ? "Admitted" : "Held"}</strong>. This publication captured <strong>${published.admitted ? "admitted" : "held"}</strong> status at mapping v${published.mapping_version}. Reviewing admission does not republish financial history.</div>` +
    panel(
      "Source-system coverage",
      "The registered source owner retains each field and original local ID.",
      sourceTable(c),
    ) +
    `<div class="grid2">${panel("Admission decision", c.company.gate.passed ? "Fresh reconciliation passed; the recorded admission flag is still required." : "Unresolved controls prevent admission.", `<p>${chip(c.company.admitted ? "Admitted" : "Held", c.company.admitted ? "good" : "warn")}</p>${json(c.company.gate.issues || [])}<button data-nav="governance">Inspect exceptions →</button>`)}${panel("Recorded handoff & recovery", "Read-only persisted execution evidence. Opening this view sends no receiver request.", c.outbound.map((r) => `<p>${chip(r.state, r.state === "confirmed" ? "good" : "warn")} <code>${E(r.effect_id)}</code></p><p class="fine">${r.attempts} persisted dispatch attempt(s) · ${E(r.detail.replaceAll("_", " "))}</p><details><summary>Independent receipt and exact-content proof</summary>${json(r.proof)}</details>`).join("") || `<p class="empty">No handoff intent exists for this company.</p>`)}</div>` +
    panel(
      "Company financial results",
      "Only this scope's approved legal-entity rows; excluded periods are not evidence of zero underlying activity.",
      table(
        "Company financial measures",
        [
          "Period",
          "Net invoicing",
          "ERP postings",
          "Allocated cash",
          "Elimination",
        ],
        local.map(
          (r) =>
            `<tr><td>${month(r.period)}</td><td>${money(r.net_invoice_minor)}</td><td>${money(r.erp_posted_minor)}</td><td>${money(r.allocated_cash_minor)}</td><td>${money(r.elimination_minor)}</td></tr>`,
        ),
      ),
    ) +
    `<details><summary>Current source records and immutable projection history</summary>${json({ current: c.source_records, history: c.source_history })}</details>`
  );
}
function financial() {
  const d = state.report.datasets;
  return (
    heading(
      "SOURCE / POSTING / COLLECTION",
      "Financial reconciliation",
      "Invoice grain, ERP postings and payment allocations remain separate. Open differences remain open; a valid calculation does not manufacture missing source evidence.",
    ) +
    metrics() +
    `<div class="grid2">${panel("Open variances", "Separate source-linked review items, not an aggregated loss.", exceptions())}${panel(
      "Gross to consolidated",
      "Approved scope, before and after the explicit elimination adjustment.",
      table(
        "Financial bridge",
        ["Measure", "Published USD"],
        [
          ["Net invoice sources", "net_invoice_minor"],
          ["ERP posting sources", "erp_posted_minor"],
          ["Supported elimination", "elimination_minor"],
          ["Consolidated net invoices", "consolidated_invoice_minor"],
        ].map(
          ([label, key]) =>
            `<tr><td>${label}</td><td class="num">${money(totals()[key])}</td></tr>`,
        ),
      ),
    )}</div>` +
    panel(
      "Invoice-level reconciliation",
      "Children are aggregated before joining. Select a source ID to inspect its frozen original body.",
      table(
        "Invoice reconciliation",
        [
          "Company / invoice",
          "Net invoice",
          "ERP postings",
          "Difference",
          "Source evidence",
        ],
        selectedRows(d.fct_invoices).map(
          (r) =>
            `<tr><td><strong>${E(r.company)} / ${E(r.invoice_id)}</strong><small>${month(r.period)} · ${E(r.legal_entity)}</small></td><td class="num">${money(r.net_minor)}</td><td class="num">${money(r.erp_minor)}</td><td class="num">${money(r.net_minor - r.erp_minor)}</td><td>${sourceButtons(r.source_event_ids)}</td></tr>`,
        ),
      ),
    ) +
    panel(
      "Intercompany evidence",
      "Exact invoice linkage and bilateral legal entities are required; equal values or names are insufficient.",
      table(
        "Intercompany elimination detail",
        [
          "Seller / invoice",
          "Charge / acceptance",
          "Decision",
          "Adjustment",
          "Owned sources",
        ],
        selectedRows(d.intercompany_eliminations).map(
          (r) =>
            `<tr><td>${E(r.company)} / ${E(r.invoice_id)}</td><td>${r.charge_count} / ${r.acceptance_count}</td><td>${chip(r.elimination_minor ? "Supported" : "Unresolved", r.elimination_minor ? "good" : "warn")}</td><td>${money(r.elimination_minor)}</td><td>${sourceButtons([...(r.charge_event_ids || []), ...(r.acceptance_event_ids || [])])}</td></tr>`,
        ),
      ),
    ) +
    panel(
      "Allocated cash",
      "Each allocation links one payment to one invoice. Cash is not inferred from a won opportunity or completed work order.",
      table(
        "Payment allocations",
        [
          "Company / allocation",
          "Payment → invoice",
          "Allocated USD",
          "Evidence",
        ],
        selectedRows(d.fct_allocations).map(
          (r) =>
            `<tr><td>${E(r.company)} / ${E(r.allocation_id)}</td><td>${E(r.payment_id)} → ${E(r.invoice_id)}</td><td>${money(r.amount_minor)}</td><td>${sourceButtons(r.source_event_ids)}</td></tr>`,
        ),
      ),
    )
  );
}
function reportingHistory() {
  return (
    heading(
      "PRESERVED / VERSIONED / TRACEABLE",
      "What changed, and what did not.",
      "A reporting version freezes source-observation knowledge and captured admission state. A later source correction creates a new publication; it does not create a business-system write.",
    ) +
    metrics() +
    panel(
      "Reporting versions",
      "Only validated financial publications are selectable. Unpublished working dbt candidates are excluded.",
      table(
        "Publication versions",
        [
          "Version",
          "Source-observation cutoff",
          "Published at (UTC)",
          "Previous version",
        ],
        state.overview.reports.map(
          (r) =>
            `<tr><td><strong>${E(r.report_id)}</strong></td><td>${date(r.cutoff)}</td><td>${E(new Date(r.published_at).toISOString().slice(0, 19).replace("T", " "))}</td><td>${E(r.previous_id || "First publication")}</td></tr>`,
        ),
      ),
    ) +
    panel(
      "Prior-period restatement bridge",
      "Changes calculated from the selected scope's validated publication rows. Unchanged measures are retained in the source record.",
      table(
        "Restatement changes",
        ["Period", "Measure", "Before", "After", "Change"],
        selectedRows(state.report.bridge)
          .filter((r) => r.delta_minor !== 0)
          .map(
            (r) =>
              `<tr><td>${month(r.period)}</td><td>${E(r.metric.replaceAll("_minor", "").replaceAll("_", " "))}</td><td>${money(r.before_minor)}</td><td>${money(r.after_minor)}</td><td>${money(r.delta_minor)}</td></tr>`,
          ),
      ),
    ) +
    panel(
      "Excluded source invoices",
      "Different reasons remain distinct: held admission versus acquisition-effective exclusion.",
      table(
        "Reporting exclusions",
        [
          "Company / source invoice",
          "Original source amount",
          "Reason",
          "Evidence",
        ],
        state.report.exclusions.map(
          (r) =>
            `<tr><td>${E(r.company)} / ${E(r.source_id)}</td><td>${money(r.amount_minor)}</td><td>${chip(r.reason.replaceAll("_", " "), "warn")}</td><td>${sourceButtons([r.event_id])}</td></tr>`,
        ),
      ),
    ) +
    `<details><summary>Publication provenance and captured admission state</summary>${json({ publication: state.report.id, cutoff: state.report.cutoff, input_hash: state.report.input_hash, control: state.report.control })}</details>`
  );
}
function governancePage(c) {
  const g = c.governance,
    write = state.user.role === "reviewer";
  const held = g.quarantine.filter((q) => !q.resolution);
  const ambiguous = held.find((q) => q.reason === "ambiguous_identity");
  let content =
    heading(
      "EXPLICIT AUTHORITY / PRESERVED EVIDENCE",
      "Admission & exceptions",
      `${c.company.name} · ${c.company.legal_entity}. Decisions append history; they cannot rewrite original source facts or bypass failed controls.`,
    ) +
    `<div class="notice">${write ? "Authorized reviewer: scoped decisions require a reason and are checked against the current source context." : "Read-only view. This session cannot propose, approve or recompute admission."} Current admission: <strong>${c.company.admitted ? "Admitted" : "Held"}</strong>.</div>` +
    panel(
      "Quarantine & original evidence",
      "Resolution markers do not erase original source messages.",
      g.quarantine
        .map(
          (q) =>
            `<details ${!q.resolution ? "open" : ""}><summary>${E(q.reason.replaceAll("_", " "))} · ${q.resolution ? "Resolved, original retained" : "Unresolved"}</summary><p class="fine">Original message ${q.message_id} · ${E(q.body.source)} · Mapping v${q.body.mapping_version}</p>${json({ source: q.body, candidates: q.detail.candidate_ids || [], resolution: q.resolution })}</details>`,
        )
        .join("") || `<p class="empty">No quarantined source record.</p>`,
    );
  if (write && ambiguous)
    content += panel(
      "Review the identity link",
      "Select an existing scoped canonical account deliberately. No automatic merge is performed.",
      `<form id="identity-form" data-quarantine="${ambiguous.id}"><div class="form-grid"><div><label for="candidate">Reviewed existing account</label><select id="candidate" name="candidate" required><option value="">Choose a reviewed candidate</option>${(ambiguous.detail.candidate_ids || []).map((id, i) => `<option value="${E(id)}">Account ${i + 1} · ${E(id)}</option>`).join("")}</select></div><div><label for="identity-reason">Source-based reason</label><input id="identity-reason" name="reason" required maxlength="500"></div></div><button type="submit" class="primary">Create identity proposal</button></form>`,
    );
  content += panel(
    "Proposals & decisions",
    "A rejected proposal cannot later be approved. Source changes make a pending decision stale.",
    g.reviews
      .map(
        (r) =>
          `<article class="review-card" data-review="${E(r.id)}"><header><div><h3>${E(r.kind)} proposal</h3><code>${E(r.id)}</code><p class="fine">${E(r.actor)} · ${E(r.reason)}</p></div>${chip(r.result || "Pending", r.result === "approved" ? "good" : r.result === "rejected" ? "warn" : "info")}</header><details><summary>Proposed content, decision and frozen context</summary>${json({ payload: r.payload, decision: c.decisions.find((d) => d.review_id === r.id) || null, context_hash: r.context_hash })}</details>${write && !r.result ? `<form class="decision-form" data-review="${E(r.id)}"><div class="form-grid"><div><label for="decision-${r.id}">Decision</label><select id="decision-${r.id}" name="result"><option value="rejected">Reject proposal</option><option value="approved">Approve exact proposal</option></select></div><div><label for="reason-${r.id}">Decision reason</label><input id="reason-${r.id}" name="reason" required maxlength="500"></div></div><button type="submit">Record decision</button></form>` : `<p class="fine">${r.result ? "Decision preserved · " + E(r.decision_actor) : "Awaiting an authorized reviewer"}</p>`}</article>`,
      )
      .join("") || `<p class="empty">No proposal has been created.</p>`,
  );
  content += panel(
    "Mapping history",
    `Current active version ${c.company.active_mapping}; previous mapping definitions and source history remain available.`,
    c.mapping_versions
      .map(
        (m) =>
          `<details><summary>Mapping v${m.version} · ${E(m.reviewed_by)}</summary>${json(m)}</details>`,
      )
      .join(""),
  );
  if (write)
    content +=
      panel(
        "Propose a controlled mapping resnapshot",
        "Review the contract and exact current inventory. Preview has no write effect; activation requires a separate decision.",
        `<details><summary>Open mapping proposal editor</summary><form id="mapping-form"><label for="mapping-contract">Mapping contract JSON</label><textarea id="mapping-contract" name="contract" rows="10">${E(JSON.stringify(g.contract, null, 2))}</textarea><p><button type="button" id="preview-mapping">Preview exact source coverage</button></p><label for="mapping-coverage">Reviewed coverage JSON</label><textarea id="mapping-coverage" name="coverage">${E(JSON.stringify(c.coverage || {}, null, 2))}</textarea><label for="mapping-reason">Mapping review reason</label><input id="mapping-reason" name="reason" required maxlength="500"><button type="submit">Create mapping proposal</button></form></details>`,
      ) +
      panel(
        "Recompute admission",
        "This requests the existing reconciliation gate. It cannot force a pass or republish financial results.",
        `<form id="admission-form"><label for="admission-reason">Admission request reason</label><input id="admission-reason" name="reason" required maxlength="500"><button type="submit" class="primary">Recompute admission</button></form>`,
      );
  return (
    content +
    `<details><summary>Scoped decision and control audit</summary>${json(c.audit)}</details>`
  );
}
async function api(path, body) {
  const response = await fetch(
    "/console/api" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": state.user.csrf,
          },
          body: JSON.stringify(body),
        },
  );
  if (response.status === 401) {
    location.assign("/console/login");
    throw new Error("Session expired");
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request was not applied");
  return data;
}
function message(text, error = false) {
  $("#status").textContent = text;
  $("#status").classList.toggle("error", error);
}
let refreshSequence = 0;
async function refresh(focus = false) {
  const sequence = ++refreshSequence;
  try {
    $("#main").setAttribute("aria-busy", "true");
    const overview = await api("/overview");
    if (sequence !== refreshSequence) return;
    state.overview = overview;
    const scope = $("#company-select").value;
    const report = await api(
      `/reports/${encodeURIComponent($("#report-select").value)}?company=${encodeURIComponent(scope)}`,
    );
    if (sequence !== refreshSequence) return;
    state.report = report;
    state.route = location.hash.slice(1) || "portfolio";
    if (!labels[state.route]) state.route = "portfolio";
    document
      .querySelectorAll("[data-route]")
      .forEach((a) => a.toggleAttribute("aria-current", false));
    const active = document.querySelector(`[data-route="${state.route}"]`);
    active.setAttribute("aria-current", "page");
    $("#route-label").textContent = labels[state.route];
    $("#publication-note").textContent =
      `${state.report.currency} · ${state.report.scenario.id === "annual-2026" ? "2026 source year · acquisition scope applies" : "Selected months, not YTD"} · Source cutoff ${date(state.report.cutoff)}`;
    if (["company", "governance"].includes(state.route)) {
      const data = await api(
        "/companies/" + encodeURIComponent(currentCompany()),
      );
      if (sequence !== refreshSequence) return;
      state.company = data;
      $("#main").innerHTML =
        state.route === "company" ? companyPage(data) : governancePage(data);
    } else
      $("#main").innerHTML =
        state.route === "finance"
          ? financial()
          : state.route === "history"
            ? reportingHistory()
            : portfolio();
    if (focus) $("#main h1").focus();
  } catch (error) {
    message("Not applied: " + error.message.replaceAll("_", " "), true);
  } finally {
    if (sequence === refreshSequence)
      $("#main").setAttribute("aria-busy", "false");
  }
}
async function mutate(path, body, text) {
  try {
    const data = await api(path, body);
    await refresh();
    message(text + (data.review_id ? " · " + data.review_id : ""));
    return data;
  } catch (error) {
    message("Not applied: " + error.message.replaceAll("_", " "), true);
  }
}
document.addEventListener("click", async (event) => {
  const source = event.target.closest("[data-source]");
  if (source) {
    try {
      const data = await api(
        `/reports/${state.report.id}/sources/${source.dataset.source}`,
      );
      $("#dialog-title").textContent =
        `${data.body.kind} · ${data.body.source_id}`;
      $("#dialog-content").textContent = JSON.stringify(data, null, 2);
      $("#evidence-dialog").showModal();
    } catch (error) {
      message(error.message, true);
    }
  }
  const company = event.target.closest("[data-company]");
  if (company) {
    $("#company-select").value = company.dataset.company;
    location.hash = "company";
    await refresh(true);
  }
  const nav = event.target.closest("[data-nav]");
  if (nav) location.hash = nav.dataset.nav;
  if (event.target.id === "preview-mapping") {
    try {
      const result = await api(
        `/companies/${currentCompany()}/mapping-preview`,
        { contract: JSON.parse($("#mapping-contract").value) },
      );
      $("#mapping-coverage").value = JSON.stringify(result.coverage, null, 2);
      message(
        "Exact source coverage previewed. No proposal or activation has occurred.",
      );
    } catch (error) {
      message("Not applied: " + error.message.replaceAll("_", " "), true);
    }
  }
});
document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (
    !["identity-form", "mapping-form", "admission-form"].includes(form.id) &&
    !form.classList.contains("decision-form")
  )
    return;
  event.preventDefault();
  const path = "/companies/" + currentCompany();
  const data = new FormData(form);
  if (form.id === "identity-form")
    await mutate(
      path + "/identity",
      {
        quarantine_id: Number(form.dataset.quarantine),
        candidate: data.get("candidate"),
        reason: data.get("reason"),
      },
      "Identity proposal persisted; a separate decision is required",
    );
  else if (form.classList.contains("decision-form"))
    await mutate(
      path + `/reviews/${form.dataset.review}/decision`,
      { result: data.get("result"), reason: data.get("reason") },
      "Decision recorded in PostgreSQL",
    );
  else if (form.id === "admission-form")
    await mutate(
      path + "/admission",
      { reason: data.get("reason") },
      "Admission recomputed. Published financial history is unchanged",
    );
  else {
    try {
      await mutate(
        path + "/mapping",
        {
          contract: JSON.parse(data.get("contract")),
          coverage: JSON.parse(data.get("coverage")),
          reason: data.get("reason"),
        },
        "Mapping proposal persisted; activation requires a separate decision",
      );
    } catch {
      message("Mapping JSON is invalid; no request was sent.", true);
    }
  }
});
$("#dialog-close").addEventListener("click", () =>
  $("#evidence-dialog").close(),
);
$("#logout").addEventListener("click", async () => {
  await api("/logout", {});
  location.assign("/console/login");
});
for (const id of ["report-select", "period-select", "company-select"])
  $("#" + id).addEventListener("change", () => refresh());
document.addEventListener("change", (event) => {
  if (event.target.id === "admission-filter") {
    state.admissionFilter = event.target.value;
    $("#company-table").innerHTML = companyTable();
  }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "company-query") {
    state.companyQuery = event.target.value.toLowerCase();
    $("#company-table").innerHTML = companyTable();
  }
});
window.addEventListener("hashchange", () => refresh(true));
(async () => {
  try {
    state.user = await api("/session");
    setTimeout(
      () => location.replace("/console/login"),
      Math.max(0, Date.parse(state.user.expires_at) - Date.now()),
    );
    state.overview = await api("/overview");
    $("#role-label").textContent =
      state.user.role === "sponsor"
        ? "Portfolio sponsor"
        : state.user.role === "reviewer"
          ? "Scoped integration reviewer"
          : "Operating-company leader";
    $("#report-select").innerHTML = state.overview.reports
      .map(
        (r) =>
          `<option value="${E(r.report_id)}">${E(r.report_id[0].toUpperCase() + r.report_id.slice(1))} · ${date(r.cutoff)}</option>`,
      )
      .join("");
    $("#report-select").value = state.overview.reports.at(-1).report_id;
    const report = await api(`/reports/${$("#report-select").value}`);
    $("#period-select").innerHTML =
      `<option value="all">All selected periods</option>` +
      report.periods
        .map((p) => `<option value="${p}">${month(p)}</option>`)
        .join("");
    $("#company-select").innerHTML =
      (state.user.role === "sponsor"
        ? `<option value="all">All permitted companies</option>`
        : "") +
      state.overview.companies
        .map((c) => `<option value="${E(c.id)}">${E(c.name)}</option>`)
        .join("");
    if (state.user.role === "reviewer" && !location.hash)
      location.hash = "governance";
    await refresh();
  } catch (error) {
    message(error.message, true);
  }
})();
