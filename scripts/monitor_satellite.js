// Yearly satellite monitoring, for the live demo. A new satellite measurement
// arrives for the real Alto Mayo project (ai/satellite/measure.py), and the
// oracle writes its re-score on chain: the same model and model hash, now with
// the measured forest-cover gap. The score crosses the freeze threshold, so the
// batch is frozen and its marketplace listing is suspended, with no one touching
// the marketplace. Run after `npm run demo:local`:  npm run demo:monitor
const fs = require("fs");
const path = require("path");
const hre = require("hardhat");
const { loadDeployment } = require("./oracle_push_scores");
const { MONITORED, satelliteResult } = require("./seed_demo");

const Status = ["Pending", "Active", "Flagged", "Rejected"];

async function main() {
  const { address, market: m } = loadDeployment();
  const [signer] = await hre.ethers.getSigners();
  const cg = await hre.ethers.getContractAt("CarbonGuard", address, signer);
  const meta = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "ai", "model", "model_meta.json"), "utf8"));
  const sat = satelliteResult(MONITORED);

  const n = Number(await cg.batchCount());
  let id = null;
  for (let i = n; i >= 1 && id === null; i--) if ((await cg.getBatch(i)).projectId === MONITORED) id = i;
  if (id === null) throw new Error(`No ${MONITORED} batch on chain: run npm run demo:local first.`);

  const before = await cg.getBatch(id);
  console.log(`#${id} ${sat.name}: risk ${before.riskScore}, ${Status[Number(before.status)]}`);
  console.log(`New satellite measurement: ${Math.round(sat.gap * 100)}% of claimed avoided forest loss not observed.`);
  await (await cg.setRiskScore(id, sat.score_with_satellite, sat.reasons, meta.model_hash, meta.data_hash)).wait();
  const after = await cg.getBatch(id);
  console.log(`Re-scored on chain: risk ${after.riskScore}, ${Status[Number(after.status)]}`);
  console.log(`  ${sat.reasons}`);

  if (m) {
    const market = await hre.ethers.getContractAt("CarbonMarket", m.address, signer);
    const count = Number(await market.listingCount());
    for (let i = 0; i < count; i++) {
      const l = await market.getListing(i);
      if (Number(l.tokenId) === id && l.open) {
        console.log(`Marketplace listing #${i}: ${(await market.isLive(i)) ? "live" : "SUSPENDED (credits frozen by CarbonGuard)"}`);
      }
    }
  }
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
