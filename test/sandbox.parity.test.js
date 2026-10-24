// The browser sandbox (web/scorer.js + web/sandbox_model.js) must be the same
// model as the Python pipeline that writes scores on chain: identical scores
// and reasons for every real project, and no way for its data to leave the page.
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { expect } = require("chai");

const ROOT = path.join(__dirname, "..");
const read = (...p) => fs.readFileSync(path.join(ROOT, ...p), "utf8");

function loadSandbox() {
  const window = {};
  const ctx = vm.createContext({ window }); // its own builtins: cross-context calls are slow
  vm.runInContext(read("web", "sandbox_model.js"), ctx);
  vm.runInContext(read("web", "scorer.js"), ctx);
  return { M: window.CG_SANDBOX, S: window.CGScorer };
}

// Minimal RFC 4180 parser (quoted fields, doubled quotes, commas and newlines inside quotes).
function parseCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); rows.push(row); row = []; field = "";
    } else field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  const [header, ...body] = rows;
  return body.filter((r) => r.length === header.length).map((r) => Object.fromEntries(header.map((h, i) => [h, r[i]])));
}

const NUMERIC = ["first_vintage", "last_vintage", "est_annual_reductions", "total_issued", "total_retired",
  "max_to_median_issuance", "buffer_pool_pct", "satellite_cover_delta_pct", "verifier_changes"];

function toRaw(row) {
  const r = { project_type: row.project_type };
  for (const k of NUMERIC) r[k] = row[k] === "" ? null : Number(row[k]);
  return r;
}

describe("Browser sandbox = on-chain model", function () {
  this.timeout(120_000);
  const { M, S } = loadSandbox();

  it("exports the model that scores on chain (same model hash)", function () {
    const meta = JSON.parse(read("ai", "model", "model_meta.json"));
    expect(M.model_hash).to.equal(meta.model_hash);
    expect(M.data_hash).to.equal(meta.data_hash);
    expect(M.features).to.deep.equal(meta.features);
  });

  it("reproduces the Python score and reasons for all 6,107 real projects", function () {
    const real = parseCsv(read("ai", "data", "real_projects.csv"));
    const expected = new Map(parseCsv(read("ai", "real_world", "vrod_scored.csv")).map((r) => [r.project_id, r]));
    expect(real.length).to.equal(6107);
    const scoreDiff = [], reasonDiff = [];
    for (const row of real) {
      const want = expected.get(row.project_id);
      const got = S.scoreRaw(M, toRaw(row));
      if (got.risk !== Number(want.risk_score)) scoreDiff.push(`${row.project_id}: js ${got.risk} py ${want.risk_score}`);
      const reasons = got.reasons.length ? got.reasons.join(" | ") : "No significant red flags";
      if (reasons !== want.reasons) reasonDiff.push(`${row.project_id}: js "${reasons}" py "${want.reasons}"`);
    }
    expect(scoreDiff, scoreDiff.slice(0, 5).join("\n")).to.have.length(0);
    expect(reasonDiff, reasonDiff.slice(0, 5).join("\n")).to.have.length(0);
  });

  it("scores every preset exactly as the Python model does", function () {
    expect(M.presets.length).to.be.greaterThan(5);
    for (const p of M.presets) {
      const got = S.scoreRaw(M, p.raw);
      expect(got.risk, p.label).to.equal(p.python_score);
      expect(got.reasons, p.label).to.deep.equal(p.python_reasons);
    }
  });

  it("Kariba: registry data alone scores Low; the measured satellite gap lifts it", function () {
    const kariba = M.presets.find((p) => p.key === "VCS902");
    const before = S.scoreRaw(M, kariba.raw).risk;
    const after = S.scoreRaw(M, { ...kariba.raw, satellite_cover_delta_pct: -kariba.measured_gap_pct }).risk;
    expect(before).to.be.below(35);
    expect(after).to.be.greaterThan(before + 30);
  });

  it("dashboard re-check: web/batch_inputs.js holds exactly the oracle's inputs", function () {
    const window = {};
    vm.runInContext(read("web", "batch_inputs.js"), vm.createContext({ window }));
    const { batchInputs } = require("../scripts/oracle_push_scores");
    const fresh = batchInputs(JSON.parse(read("ai", "data", "projects_scored.json")));
    expect(JSON.parse(JSON.stringify(window.CG_BATCH_INPUTS)), "rerun npm run export:inputs").to.deep.equal(fresh);
    expect(fresh.model_hash).to.equal(M.model_hash);
  });

  it("dashboard re-check: real-project inputs reproduce every score the oracle writes, exactly", function () {
    const { batchInputs } = require("../scripts/oracle_push_scores");
    const { batches } = batchInputs(JSON.parse(read("ai", "data", "projects_scored.json")));
    const summary = JSON.parse(read("ai", "real_world", "summary.json"));
    const alto = summary.satellite.find((s) => s.project_id === "VCS944");
    const [registry, withSat] = batches.VCS944.versions.map((v) => S.scoreRaw(M, v.raw));
    expect(registry.risk).to.equal(alto.score_registry_only);
    expect(registry.reasons.join(" | ")).to.equal(alto.reasons_registry_only);
    expect(withSat.risk).to.equal(alto.score_with_satellite);
    expect(withSat.reasons.join(" | ")).to.equal(alto.reasons);
    // Synthetic batches were scored out-of-fold, so only their reasons must match the final model.
    for (const p of JSON.parse(read("ai", "data", "projects_scored.json")).filter((x) => batches[x.project_id])) {
      const got = S.scoreRaw(M, batches[p.project_id].versions[0].raw);
      expect(got.reasons.length ? got.reasons.join(" | ") : "No significant red flags", p.project_id).to.equal(p.reasons);
    }
  });

  it("formats numbers like Python (ties round to even)", function () {
    expect(S.fmt(2.5, 0)).to.equal("2");
    expect(S.fmt(3.5, 0)).to.equal("4");
    expect(S.fmt(1.25, 1)).to.equal("1.2");
    expect(S.fmt(1.35, 1)).to.equal("1.4"); // 1.35 is stored as 1.350000000000000088...
    expect(S.roundHalfEven(64.5)).to.equal(64);
    expect(S.roundHalfEven(65.5)).to.equal(66);
  });

  it("nothing the user types can leave the browser", function () {
    const forbidden = /\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|EventSource|\bethers\b|<form|localStorage|https?:\/\/(?!www\.w3\.org)/;
    for (const f of ["scorer.js", "sandbox.html"]) {
      const src = read("web", f)
        .replace(/<a [^>]*href="https?:\/\/[^"]*"/g, "<a") // outbound citation links are fine
        .replace(/<link [^>]*href="https:\/\/fonts\.(googleapis|gstatic)\.com[^"]*"[^>]*>/g, ""); // web fonts carry no user data
      expect(forbidden.test(src), `${f} contains a network or storage API`).to.equal(false);
    }
    // The page only loads local scripts.
    const scripts = [...read("web", "sandbox.html").matchAll(/<script[^>]*src="([^"]+)"/g)].map((m) => m[1]);
    expect(scripts).to.deep.equal(["sandbox_model.js", "scorer.js"]);
  });
});
