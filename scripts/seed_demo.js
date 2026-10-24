// Creates some market history so the dashboard isn't empty on first load:
// a few voluntary retirements, one Article 6 compliance retirement, one
// verifier rejection, marketplace listings (including the real Alto Mayo
// project, scored on registry data only), and a demonstration of the guards
// rejecting bad actions. Then run `npm run demo:monitor` to push Alto Mayo's
// satellite-based re-score and watch its listing get suspended.
const fs = require("fs");
const path = require("path");
const hre = require("hardhat");
const { loadDeployment } = require("./oracle_push_scores");

const AI = path.join(__dirname, "..", "ai");
const PRICE = hre.ethers.parseEther("0.001"); // per tonne, ~$3 at $3,000/ETH
// The real project re-scored live in the demo, and its illustrative serial range.
const MONITORED = "VCS944";
const MONITORED_BATCH = {
  registry: "VCS", projectId: MONITORED, projectType: "REDD+", country: "Peru", vintage: 2020,
  serialFrom: 944n * 10n ** 12n + 1n, serialTo: 944n * 10n ** 12n + 50_000n, correspondingAdjustment: false,
};

function satelliteResult(id) {
  const summary = JSON.parse(fs.readFileSync(path.join(AI, "real_world", "summary.json"), "utf8"));
  return summary.satellite.find((s) => s.project_id === id);
}

// Fixed-price listings on the example marketplace, plus one real project scored
// on registry data alone (what a registry publishes, before satellite data).
async function seedMarket(cg, signer, signers, active) {
  const { market: m } = loadDeployment();
  if (!m) return console.log("No marketplace in web/deployment.js; skipping listings.");
  const market = await hre.ethers.getContractAt("CarbonMarket", m.address, signer);
  await (await cg.setApprovalForAll(m.address, true)).wait();

  // One low-risk and one medium-risk batch (Medium trades, with its warning shown).
  const byScore = [...active].sort((x, y) => Number(x.riskScore) - Number(y.riskScore));
  const forSale = [byScore.find((b, i) => i >= 3 && Number(b.riskScore) < 35), byScore[byScore.length - 1]].filter(Boolean);
  for (const b of forSale) {
    const amt = 5_000n;
    await (await market.list(b.id, amt, PRICE)).wait();
    console.log(`Listed ${amt} t of #${b.id} (${b.projectId}) at ${hre.ethers.formatEther(PRICE)} ETH/t`);
  }
  if (signers.length > 3 && forSale.length) {
    await (await market.connect(signers[3]).buy(0, 250n, { value: 250n * PRICE })).wait();
    console.log(`Account #3 bought 250 t from listing #0`);
  }

  const alto = satelliteResult(MONITORED);
  if (!alto) return console.log(`No satellite result for ${MONITORED}; skipping the monitoring demo.`);
  const meta = JSON.parse(fs.readFileSync(path.join(AI, "model", "model_meta.json"), "utf8"));
  const rc = await (await cg.registerBatch(MONITORED_BATCH, signer.address)).wait();
  const id = rc.logs.map((l) => cg.interface.parseLog(l)).find((e) => e && e.name === "BatchRegistered").args.tokenId;
  await (await cg.setRiskScore(id, alto.score_registry_only, alto.reasons_registry_only, meta.model_hash, meta.data_hash)).wait();
  const amt = 20_000n;
  await (await market.list(id, amt, PRICE)).wait();
  console.log(`#${id} ${alto.name} (real project, demo serials): registry-only risk ${alto.score_registry_only}, listed ${amt} t`);
  console.log(`  -> run "npm run demo:monitor" to push its satellite-based score (${alto.score_with_satellite}).`);
}

const Status = ["Pending", "Active", "Flagged", "Rejected"];
// Fictional buyers for the demo.
const BUYERS = ["Northwind Logistics", "Contoso Airlines", "Fabrikam Steel", "Tailspin Data Centers"];

async function main() {
  const { address } = loadDeployment();
  const [signer] = await hre.ethers.getSigners();
  const cg = await hre.ethers.getContractAt("CarbonGuard", address, signer);

  const n = Number(await cg.batchCount());
  const batches = [];
  for (let id = 1; id <= n; id++) batches.push({ id, ...(await cg.getBatch(id)).toObject() });
  const active = batches.filter((b) => Status[Number(b.status)] === "Active");
  const flagged = batches.filter((b) => Status[Number(b.status)] === "Flagged");

  // Voluntary retirements on a few clean batches
  for (let i = 0; i < Math.min(3, active.length); i++) {
    const b = active[i];
    const amt = b.issued / 5n;
    await (await cg.retire(b.id, amt, BUYERS[i], "FY2025 Scope 1 & 2 offset", false)).wait();
    console.log(`Retired ${amt} t of #${b.id} for ${BUYERS[i]}`);
  }

  // One compliance claim on a batch with an Article 6 corresponding adjustment
  const ca = active.find((b) => b.correspondingAdjustment);
  if (ca) {
    await (await cg.retire(ca.id, 2500n, BUYERS[3], "CORSIA 2025 compliance claim", true)).wait();
    console.log(`Compliance retirement of 2500 t from #${ca.id} (has corresponding adjustment)`);
  }

  // A 2-of-3 verifier panel when the network gives us enough accounts (local
  // Hardhat does; with a single key the panel keeps the default of 1).
  const signers = await hre.ethers.getSigners();
  const panel = signers.length >= 3 ? [signer, signers[1], signers[2]] : [signer];
  if (panel.length === 3) {
    const role = await cg.VERIFIER_ROLE();
    for (const v of panel.slice(1)) await (await cg.grantRole(role, v.address)).wait();
    await (await cg.setRequiredApprovals(2)).wait();
    console.log(`Verifier panel: 2-of-3 (${panel.map((v) => v.address.slice(0, 8)).join(", ")})`);
  }

  // The panel confirms the worst flag (permanently frozen); the rest stay for the live demo
  flagged.sort((a, b) => Number(b.riskScore) - Number(a.riskScore));
  if (flagged.length) {
    const worst = flagged[0];
    const note = "Desk review: baseline deforestation rate inflated vs. satellite record";
    for (const v of panel.slice(0, panel.length === 3 ? 2 : 1)) {
      await (await cg.connect(v).verifierDecision(worst.id, false, note)).wait();
    }
    console.log(`Verifier panel rejected #${worst.id} (${worst.projectId}, risk ${worst.riskScore})`);
  }
  // One flagged batch waits on the panel with a single approval, to show no single key can unfreeze it.
  if (panel.length === 3 && flagged.length > 1) {
    const waiting = flagged[1];
    await (await cg.connect(panel[2]).verifierDecision(waiting.id, true, "Field audit looks fine to me")).wait();
    console.log(`#${waiting.id} has 1 of 2 approvals and stays frozen until a second verifier agrees`);
  }

  await seedMarket(cg, signer, signers, active);

  // Show that the guards work (these are static calls - nothing is sent)
  const decode = (d) => {
    try {
      return typeof d === "string" ? cg.interface.parseError(d)?.name : undefined;
    } catch {
      return undefined;
    }
  };
  const tryCall = async (label, fn) => {
    try {
      await fn();
      console.log(`  ✗ ${label}: unexpectedly allowed`);
    } catch (e) {
      const name = e.revert?.name || decode(e.data) || decode(e.data?.data) || e.shortMessage;
      console.log(`  ✓ ${label}: reverted with ${name}`);
    }
  };
  console.log("Guard checks:");
  if (flagged[1]) await tryCall("retire flagged credits", () => cg.retire.staticCall(flagged[1].id, 1, "x", "x", false));
  const b1 = batches[0];
  await tryCall("re-bridge an existing serial range", () =>
    cg.registerBatch.staticCall(
      {
        registry: b1.registry, projectId: b1.projectId, projectType: b1.projectType, country: b1.country,
        vintage: b1.vintage, serialFrom: b1.serialFrom + 10n, serialTo: b1.serialTo + 10n,
        correspondingAdjustment: b1.correspondingAdjustment,
      },
      signer.address
    )
  );
  const noCa = active.find((b) => !b.correspondingAdjustment);
  if (noCa) await tryCall("compliance claim without corresponding adjustment", () =>
    cg.retire.staticCall(noCa.id, 1, "x", "x", true));
}

module.exports = { MONITORED, satelliteResult };

if (require.main === module) {
  main().catch((e) => {
    console.error(e);
    process.exitCode = 1;
  });
}
