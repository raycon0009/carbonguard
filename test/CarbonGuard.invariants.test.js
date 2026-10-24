// Randomized invariant test: throw a long, seeded sequence of random actions
// from random wallets at the contract (many of them should revert) and check
// after every step that no tonne is ever created, duplicated or lost.
const { expect } = require("chai");
const { ethers } = require("hardhat");
const { Status, MODEL, DATA } = require("./fixtures");

const STEPS = Number(process.env.FUZZ_STEPS || 300);
const SEED = Number(process.env.FUZZ_SEED || 20261021);

function mulberry32(a) {
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe(`CarbonGuard invariants (${STEPS} random steps, seed ${SEED})`, function () {
  this.timeout(600_000);

  it("never creates, duplicates or loses a tonne", async function () {
    const rnd = mulberry32(SEED);
    const int = (lo, hi) => lo + Math.floor(rnd() * (hi - lo + 1));
    const pick = (arr) => arr[Math.floor(rnd() * arr.length)];

    const [admin, oracle, ...rest] = await ethers.getSigners();
    const holders = rest.slice(0, 4);
    const everyone = [admin, oracle, ...holders];
    const addrs = everyone.map((s) => s.address);
    const cg = await ethers.deployContract("CarbonGuard", [admin.address]);
    await cg.grantRole(await cg.ORACLE_ROLE(), oracle.address);
    // 2-of-2 review panel: admin and the first holder must agree.
    await cg.grantRole(await cg.VERIFIER_ROLE(), holders[0].address);
    await cg.setRequiredApprovals(2);
    const verifiers = [admin, holders[0]];

    const ok = { register: 0, score: 0, verify: 0, transfer: 0, retire: 0 };
    const attempted = { ...ok };
    const tryTx = async (kind, fn) => {
      attempted[kind]++;
      try {
        await (await fn()).wait();
        ok[kind]++;
      } catch (e) {
        // Only contract reverts are acceptable; anything else is a test bug.
        if (!/revert|panic/i.test(e.message)) throw e;
      }
    };

    async function snapshot() {
      const n = Number(await cg.batchCount());
      const batches = [];
      for (let id = 1; id <= n; id++) {
        const b = await cg.getBatch(id);
        const bal = await cg.balanceOfBatch(addrs, addrs.map(() => id));
        batches.push({ id, b, bal: bal.map(BigInt) });
      }
      return batches;
    }

    let prev = [];
    for (let step = 0; step < STEPS; step++) {
      const n = Number(await cg.batchCount());
      // Mostly real ids, sometimes invalid ones (0 and n+1).
      const anyId = () => (n > 0 && rnd() < 0.9 ? int(1, n) : pick([0, n + 1]));
      // Mostly a holder that actually owns some of the batch, so moves can succeed.
      const owner = async (id) => {
        if (id < 1 || id > n || rnd() < 0.2) return pick(holders);
        const bals = await cg.balanceOfBatch(holders.map((h) => h.address), holders.map(() => id));
        const rich = holders.filter((_, i) => bals[i] > 0n);
        return rich.length ? pick(rich) : pick(holders);
      };
      // Mostly within balance, sometimes 0 or more than held.
      const amountFor = (bal) =>
        rnd() < 0.8 && bal > 0n ? BigInt(int(1, Number(bal))) : BigInt(int(0, Number(bal) + 5));
      const action = pick(["register", "score", "score", "verify", "transfer", "transfer", "retire", "retire"]);

      if (action === "register") {
        const from = BigInt(int(0, 6000));
        const caller = rnd() < 0.85 ? admin : pick(holders);
        await tryTx("register", () =>
          cg.connect(caller).registerBatch(
            {
              registry: pick(["VCS", "GS"]),
              projectId: pick(["P1", "P2"]),
              projectType: "REDD+",
              country: "Peru",
              vintage: pick([2020, 2021]),
              serialFrom: from,
              serialTo: from + BigInt(int(-5, 800)), // sometimes inverted
              correspondingAdjustment: rnd() < 0.3,
            },
            pick(holders).address
          )
        );
      } else if (action === "score") {
        const caller = rnd() < 0.9 ? oracle : pick(holders);
        const score = rnd() < 0.6 ? int(0, 70) : int(71, 110); // >100 must revert
        await tryTx("score", () => cg.connect(caller).setRiskScore(anyId(), score, "fuzz", MODEL, DATA));
      } else if (action === "verify") {
        const caller = rnd() < 0.85 ? pick(verifiers) : pick(holders.slice(1));
        await tryTx("verify", () => cg.connect(caller).verifierDecision(anyId(), rnd() < 0.5, "fuzz"));
      } else if (action === "transfer") {
        const id = anyId();
        const from = await owner(id);
        const bal = id >= 1 && id <= n ? await cg.balanceOf(from.address, id) : 0n;
        const amount = amountFor(bal);
        const caller = rnd() < 0.9 ? from : pick(holders); // sometimes unapproved
        await tryTx("transfer", () =>
          cg.connect(caller).safeTransferFrom(from.address, pick(holders).address, id, amount, "0x")
        );
      } else {
        const id = anyId();
        const who = await owner(id);
        const bal = id >= 1 && id <= n ? await cg.balanceOf(who.address, id) : 0n;
        const amount = amountFor(bal);
        await tryTx("retire", () => cg.connect(who).retire(id, amount, "Fuzz Co", "fuzz", rnd() < 0.3));
      }

      const now = await snapshot();
      let sumIssued = 0n;
      let sumRetired = 0n;
      for (const { id, b, bal } of now) {
        sumIssued += b.issued;
        sumRetired += b.retired;
        const held = bal.reduce((x, y) => x + y, 0n);
        expect(held + b.retired, `step ${step}: batch #${id} conservation`).to.equal(b.issued);
        expect(b.issued, `step ${step}: batch #${id} amount = serial count`).to.equal(b.serialTo - b.serialFrom + 1n);

        const before = prev.find((p) => p.id === id);
        if (before) {
          if (before.b.status === Status.Rejected) {
            expect(b.status, `step ${step}: rejected batch #${id} changed status`).to.equal(Status.Rejected);
          }
          if (before.b.status === Status.Flagged && b.status !== Status.Flagged) {
            expect(b.humanReviewed, `step ${step}: #${id} decided without a human`).to.equal(true);
            const [approvals, rejections] = await cg.getVotes(id);
            const agreeing = b.status === Status.Active ? approvals : rejections;
            expect(agreeing, `step ${step}: #${id} decided by fewer than 2 verifiers`).to.be.greaterThanOrEqual(2n);
          }
          if (before.b.status !== Status.Active) {
            expect(bal, `step ${step}: frozen batch #${id} moved`).to.deep.equal(before.bal);
          }
        }
      }
      expect(await cg.totalIssued()).to.equal(sumIssued);
      expect(await cg.totalRetired()).to.equal(sumRetired);

      // No two batches of the same (registry, project, vintage) share a serial.
      for (let i = 0; i < now.length; i++) {
        for (let j = i + 1; j < now.length; j++) {
          const a = now[i].b;
          const c = now[j].b;
          if (a.registry === c.registry && a.projectId === c.projectId && a.vintage === c.vintage) {
            const overlap = a.serialFrom <= c.serialTo && c.serialFrom <= a.serialTo;
            expect(overlap, `step ${step}: batches #${i + 1} and #${j + 1} overlap`).to.equal(false);
          }
        }
      }
      prev = now;
    }

    // The run must actually exercise every action, not just bounce off reverts.
    for (const k of Object.keys(ok)) expect(ok[k], `no successful ${k}`).to.be.greaterThan(0);
    const total = Object.values(attempted).reduce((a, b) => a + b, 0);
    const succeeded = Object.values(ok).reduce((a, b) => a + b, 0);
    console.log(`      ${succeeded}/${total} actions succeeded, ${total - succeeded} reverted as expected`, ok);
  });
});
