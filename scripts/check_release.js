// Pre-publish checklist. Run before pushing to GitHub: npm run check (also runs in CI).
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { execSync } = require("child_process");

const ROOT = path.join(__dirname, "..");
const SKIP_DIRS = new Set(["node_modules", "artifacts", "cache", "coverage", ".git", "__pycache__", ".pytest_cache"]);
// Hardhat's well-known local account #0 key: public, documented, never holds real funds.
const PUBLIC_TEST_KEYS = new Set(["ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"]);

const results = [];
const check = (name, fn) => {
  try {
    const problem = fn();
    results.push({ name, ok: !problem, problem });
  } catch (e) {
    results.push({ name, ok: false, problem: e.message });
  }
};
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");
const sha256 = (rel) => "0x" + crypto.createHash("sha256").update(fs.readFileSync(path.join(ROOT, rel))).digest("hex");
const jsObject = (rel) => {
  const src = read(rel);
  return JSON.parse(src.slice(src.indexOf("{"), src.lastIndexOf("}") + 1));
};

function* walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else yield full;
  }
}

const isGit = fs.existsSync(path.join(ROOT, ".git")) || fs.existsSync(path.join(ROOT, "..", ".git"));
const tracked = (rel) => {
  if (!isGit) return false;
  return execSync(`git ls-files -- "${rel}"`, { cwd: ROOT }).toString().trim() !== "";
};

check("No private keys or API keys in the repo", () => {
  const hits = [];
  for (const file of walk(ROOT)) {
    const rel = path.relative(ROOT, file).replace(/\\/g, "/");
    if (rel === ".env" || /\.(png|jpg|joblib|ico)$/.test(rel)) continue;
    if (fs.statSync(file).size > 5_000_000) continue;
    read(rel).split(/\r?\n/).forEach((line, i) => {
      if (!/priv|secret|mnemonic|api[_-]?key|seed phrase/i.test(line)) return;
      for (const m of line.matchAll(/(?:0x)?([0-9a-fA-F]{64})\b/g)) {
        if (!PUBLIC_TEST_KEYS.has(m[1].toLowerCase())) hits.push(`${rel}:${i + 1}`);
      }
      if (/ETHERSCAN_API_KEY\s*=\s*[A-Z0-9]{30,}/.test(line)) hits.push(`${rel}:${i + 1}`);
      if (/https:\/\/[^\s"']*(infura|alchemy)[^\s"']*\/[0-9a-zA-Z_-]{20,}/.test(line)) hits.push(`${rel}:${i + 1}`);
    });
  }
  return hits.length ? `possible secret at ${hits.join(", ")}` : null;
});

check(".env is git-ignored and not committed", () => {
  const ignore = read(".gitignore").split(/\r?\n/).map((l) => l.trim());
  if (!ignore.includes(".env")) return ".env is missing from .gitignore";
  if (!ignore.includes("node_modules/")) return "node_modules/ is missing from .gitignore";
  if (tracked(".env")) return ".env is tracked by git - remove it and rotate the key";
  return null;
});

check("LICENSE file exists", () => (fs.existsSync(path.join(ROOT, "LICENSE")) ? null : "add a LICENSE file"));

check("Model hashes match the model and data files (AI provenance)", () => {
  const meta = JSON.parse(read("ai/model/model_meta.json"));
  if (meta.model_hash !== sha256("ai/model/carbonguard_risk_v1.joblib")) return "model_hash is stale - run npm run score";
  // data_hash covers every training file, in order (synthetic, then real projects).
  const h = crypto.createHash("sha256");
  for (const f of meta.data_files || ["projects_raw.csv"]) h.update(fs.readFileSync(path.join(ROOT, "ai", "data", f)));
  if (meta.data_hash !== "0x" + h.digest("hex")) return "data_hash is stale - run npm run score";
  return null;
});

check("Dashboard model card matches the model", () => {
  if (!fs.existsSync(path.join(ROOT, "web/model.js"))) return "web/model.js missing - run the oracle script";
  const card = jsObject("web/model.js");
  const meta = JSON.parse(read("ai/model/model_meta.json"));
  return card.model_hash === meta.model_hash && card.data_hash === meta.data_hash
    ? null
    : "web/model.js shows different hashes than ai/model/model_meta.json - rerun scripts/oracle_push_scores.js";
});

check("README test counts are accurate", () => {
  const readme = read("README.md");
  const contractTests = fs
    .readdirSync(path.join(ROOT, "test"))
    .filter((f) => f.endsWith(".test.js"))
    .reduce((n, f) => n + (read(`test/${f}`).match(/^\s*it\(/gm) || []).length, 0);
  const out = execSync("python -m pytest ai/tests --collect-only -q -p no:cacheprovider", { cwd: ROOT }).toString();
  const aiTests = Number((out.match(/(\d+) tests? collected/) || [])[1]);
  const claimedContract = Number((readme.match(/(\d+) contract and integration tests/) || [])[1]);
  const claimedAi = Number((readme.match(/(\d+) AI pipeline tests/) || [])[1]);
  const problems = [];
  if (claimedContract !== contractTests) problems.push(`README says ${claimedContract} contract tests, found ${contractTests}`);
  if (claimedAi !== aiTests) problems.push(`README says ${claimedAi} AI tests, found ${aiTests}`);
  return problems.join("; ") || null;
});

check("Dashboard deployment config is valid", () => {
  const cfg = jsObject("web/deployment.js");
  return /^0x[0-9a-fA-F]{40}$/.test(cfg.address) ? null : "web/deployment.js has no contract address";
});

check("No file over 50 MB", () => {
  const big = [...walk(ROOT)].filter((f) => fs.statSync(f).size > 50 * 1024 * 1024);
  return big.length ? big.map((f) => path.relative(ROOT, f)).join(", ") : null;
});

for (const r of results) console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}${r.ok ? "" : `\n      -> ${r.problem}`}`);
const failed = results.filter((r) => !r.ok).length;
console.log(failed ? `\n${failed} check(s) failed.` : `\nAll ${results.length} checks passed.`);
process.exitCode = failed ? 1 : 0;
