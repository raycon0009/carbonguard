// End to end: AI output files -> oracle script -> contract -> dashboard code.
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-toolbox/network-helpers");
const { pushScores } = require("../scripts/oracle_push_scores");
const { Status } = require("./fixtures");

const ROOT = path.join(__dirname, "..");
const projects = JSON.parse(fs.readFileSync(path.join(ROOT, "ai", "data", "projects_scored.json"), "utf8"));
const meta = JSON.parse(fs.readFileSync(path.join(ROOT, "ai", "model", "model_meta.json"), "utf8"));

// Load web/common.js the way the browser does, with the real ethers library.
function loadDashboard(abi, address) {
  const window = { CG_CONFIG: { abi, address, rpc: "http://127.0.0.1:1", chainId: 31337, explorer: "" } };
  const ctx = vm.createContext({ window, ethers, console });
  vm.runInContext(fs.readFileSync(path.join(ROOT, "web", "common.js"), "utf8") + "\nwindow.CG = CG;", ctx);
  return window.CG;
}

async function deployAndPush() {
  const [admin] = await ethers.getSigners();
  const cg = await ethers.deployContract("CarbonGuard", [admin.address]);
  const results = await pushScores(cg, admin, projects, meta);
  return { cg, admin, results };
}

async function revertOf(promise) {
  try {
    await promise;
  } catch (e) {
    return e;
  }
  throw new Error("expected a revert");
}

describe("AI -> chain -> dashboard pipeline", function () {
  this.timeout(120_000);

  it("writes every score, reason and provenance hash exactly as the model produced it", async function () {
    const { cg, results } = await loadFixture(deployAndPush);
    expect(results.length).to.be.greaterThan(10);
    for (const { tokenId, project } of results) {
      const b = await cg.getBatch(tokenId);
      expect(b.projectId).to.equal(project.project_id);
      expect(b.riskScore).to.equal(project.risk_score);
      expect(b.riskReasons).to.equal(project.reasons);
      expect(b.modelHash).to.equal(meta.model_hash);
      expect(b.dataHash).to.equal(meta.data_hash);
    }
  });

  it("Python, JavaScript and Solidity agree on what is high risk", async function () {
    const { cg, results } = await loadFixture(deployAndPush);
    const CG = loadDashboard(JSON.parse(cg.interface.formatJson()), await cg.getAddress());
    const tiers = new Set();
    for (const { tokenId, project } of results) {
      const status = (await cg.getBatch(tokenId)).status;
      expect(status === Status.Flagged, `${project.project_id} score ${project.risk_score}`).to.equal(
        project.risk_tier === "High"
      );
      expect(CG.tier(project.risk_score), `dashboard tier for ${project.risk_score}`).to.equal(project.risk_tier);
      tiers.add(project.risk_tier);
    }
    expect([...tiers].sort()).to.deep.equal(["High", "Low", "Medium"]); // demo shows all three
  });

  it("the longest AI explanation still fits comfortably in one transaction", async function () {
    const { results } = await loadFixture(deployAndPush);
    const worst = results.reduce((a, b) => (a.scoreGas > b.scoreGas ? a : b));
    expect(worst.scoreGas).to.be.lessThan(500_000n);
  });

  it("the dashboard ABI matches the compiled contract", async function () {
    const src = fs.readFileSync(path.join(ROOT, "web", "deployment.js"), "utf8");
    const config = JSON.parse(src.slice(src.indexOf("{"), src.lastIndexOf("}") + 1));
    const deployed = config.abi;
    const compiled = JSON.parse(
      fs.readFileSync(path.join(ROOT, "artifacts", "contracts", "CarbonGuard.sol", "CarbonGuard.json"), "utf8")
    ).abi;
    const sig = (abi) => new ethers.Interface(abi).fragments.map((f) => f.format("full")).sort();
    expect(sig(deployed)).to.deep.equal(sig(compiled));
    const market = JSON.parse(
      fs.readFileSync(path.join(ROOT, "artifacts", "contracts", "CarbonMarket.sol", "CarbonMarket.json"), "utf8")
    ).abi;
    expect(config.market, "deployment.js has no marketplace: run npm run demo:local").to.exist;
    expect(sig(config.market.abi)).to.deep.equal(sig(market));
  });

  it("every contract error has a plain-English message on the dashboard", async function () {
    const { cg } = await loadFixture(deployAndPush);
    const src = fs.readFileSync(path.join(ROOT, "web", "common.js"), "utf8");
    const start = src.indexOf("const texts = {");
    const end = start + src.slice(start).search(/\r?\n\s*\};/); // the map's own closing brace
    const textsBlock = src.slice(start, end);
    const mapped = new Set([...textsBlock.matchAll(/^\s+(\w+): \(\) =>/gm)].map((m) => m[1]));
    const market = await ethers.getContractFactory("CarbonMarket");
    const errors = [...cg.interface.fragments, ...market.interface.fragments].filter((f) => f.type === "error");
    const missing = errors.map((f) => f.name).filter((n) => !mapped.has(n));
    expect(missing, "errors without a dashboard message").to.deep.equal([]);
  });

  describe("cost and impact claims", function () {
    const { measureGas } = require("../scripts/gas_report");
    // Budgets keep the published cost claims honest if the contract grows.
    const BUDGET = {
      "Bridge a registry batch": 450_000,
      "Write AI score": 300_000,
      "Transfer credits": 80_000,
      "Retire credits (voluntary": 330_000,
      "Retire credits (Article 6": 330_000,
      "Verifier vote": 100_000,
      "Marketplace: list": 200_000,
      "Marketplace: buy": 150_000,
    };

    it("every action stays within its gas budget", async function () {
      const rows = await measureGas();
      for (const [prefix, max] of Object.entries(BUDGET)) {
        const hits = rows.filter((r) => r.action.startsWith(prefix));
        expect(hits, prefix).to.not.be.empty;
        for (const r of hits) expect(r.gas, r.action).to.be.lessThan(max);
      }
    });

    it("the dashboard's cost figures were measured on the current contract", async function () {
      // Coverage instruments the bytecode, which changes gas; the plain test run checks this.
      if (require("hardhat").__SOLIDITY_COVERAGE_RUNNING) this.skip();
      const rows = await measureGas();
      const ctx = { window: {} };
      vm.runInNewContext(fs.readFileSync(path.join(ROOT, "web", "costs.js"), "utf8"), ctx);
      const retire = rows.find((r) => r.action.startsWith("Retire credits (voluntary")).gas;
      expect(ctx.window.CG_COSTS.retireGas, "rerun npx hardhat run scripts/gas_report.js").to.equal(retire);
    });

    it("impact constants are positive and cite a source", async function () {
      const ctx = { window: {} };
      vm.runInNewContext(fs.readFileSync(path.join(ROOT, "web", "impact.js"), "utf8"), ctx);
      const im = ctx.window.CG_IMPACT;
      expect(im.carTonnesPerYear).to.be.within(3, 6);
      expect(im.priceUsdPerTonne).to.be.greaterThan(0);
      expect(im.carSource).to.match(/^https:\/\/www\.epa\.gov\//);
      expect(im.priceSource).to.match(/^https:\/\//);
      expect(im.priceNote).to.match(/assumed/);
    });
  });

  describe("attack simulator (same calls the dashboard makes)", function () {
    it("double tokenisation is blocked with a readable message", async function () {
      const { cg, admin } = await loadFixture(deployAndPush);
      const CG = loadDashboard(JSON.parse(cg.interface.formatJson()), await cg.getAddress());
      const b = await cg.getBatch(1);
      const shift = (b.serialTo - b.serialFrom) / 2n;
      const e = await revertOf(
        cg.registerBatch.staticCall(
          { registry: b.registry, projectId: b.projectId, projectType: b.projectType, country: b.country,
            vintage: b.vintage, serialFrom: b.serialFrom + shift, serialTo: b.serialTo + shift,
            correspondingAdjustment: b.correspondingAdjustment },
          admin.address
        )
      );
      const h = CG.humanError(e);
      expect(h.name).to.equal("AlreadyTokenized");
      expect(h.text).to.match(/^Double tokenisation blocked: serials .* already on chain as batch #1\.$/);
    });

    it("selling a flagged credit is blocked with a readable message", async function () {
      const { cg, admin, results } = await loadFixture(deployAndPush);
      const CG = loadDashboard(JSON.parse(cg.interface.formatJson()), await cg.getAddress());
      const flagged = results.find((r) => r.project.risk_tier === "High");
      const e = await revertOf(
        cg.safeTransferFrom.staticCall(admin.address, "0x000000000000000000000000000000000000dEaD", flagged.tokenId, 100, "0x")
      );
      const h = CG.humanError(e);
      expect(h.name).to.equal("NotTradable");
      expect(h.text).to.equal(`Quality gate: batch #${flagged.tokenId} is Flagged and cannot be moved or retired.`);
    });

    it("a compliance claim without a corresponding adjustment is blocked with a readable message", async function () {
      const { cg, results } = await loadFixture(deployAndPush);
      const CG = loadDashboard(JSON.parse(cg.interface.formatJson()), await cg.getAddress());
      const plain = results.find((r) => r.project.risk_tier === "Low" && !r.project.has_corresponding_adjustment);
      const e = await revertOf(cg.retire.staticCall(plain.tokenId, 10, "Demo Airline", "CORSIA claim", true));
      const h = CG.humanError(e);
      expect(h.name).to.equal("NoCorrespondingAdjustment");
      expect(h.text).to.match(/^Double claiming blocked/);
    });

    it("a wallet rejection and an unknown failure still produce a sentence", async function () {
      const { cg } = await loadFixture(deployAndPush);
      const CG = loadDashboard(JSON.parse(cg.interface.formatJson()), await cg.getAddress());
      expect(CG.humanError({ code: "ACTION_REJECTED" }).text).to.equal("You rejected the transaction in your wallet.");
      expect(CG.humanError(new Error("network down")).text).to.equal("network down");
    });
  });
});
