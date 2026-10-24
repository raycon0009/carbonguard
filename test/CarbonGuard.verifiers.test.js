const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-toolbox/network-helpers");
const { Status, MODEL, DATA, deploy, deployWithBatch } = require("./fixtures");

// 2-of-3 review panel: admin plus two independent verifiers, batch #1 flagged by the AI.
async function deployPanel() {
  const ctx = await deployWithBatch();
  const signers = await ethers.getSigners();
  const [v1, v2] = [signers[5], signers[6]];
  const role = await ctx.cg.VERIFIER_ROLE();
  await ctx.cg.grantRole(role, v1.address);
  await ctx.cg.grantRole(role, v2.address);
  await ctx.cg.setRequiredApprovals(2);
  await ctx.cg.connect(ctx.oracle).setRiskScore(1, 92, "Issuance spike", MODEL, DATA);
  return { ...ctx, v1, v2, role };
}

describe("CarbonGuard multi-verifier review (2-of-3)", function () {
  it("one approval is not enough to unfreeze a flagged batch", async function () {
    const { cg, v1 } = await loadFixture(deployPanel);
    await expect(cg.connect(v1).verifierDecision(1, true, "Looks fine"))
      .to.emit(cg, "VerifierVote")
      .withArgs(1, v1.address, true, "Looks fine")
      .and.not.to.emit(cg, "VerifierDecision");
    expect((await cg.getBatch(1)).status).to.equal(Status.Flagged);
    expect(await cg.isTradable(1)).to.equal(false);
    const [approvals, rejections, required] = await cg.getVotes(1);
    expect([approvals, rejections, required]).to.deep.equal([1n, 0n, 2n]);
    expect(await cg.hasVoted(1, v1.address)).to.equal(true);
  });

  it("a second independent approval unfreezes it", async function () {
    const { cg, v1, v2 } = await loadFixture(deployPanel);
    await cg.connect(v1).verifierDecision(1, true, "Field audit OK");
    await expect(cg.connect(v2).verifierDecision(1, true, "Satellite re-check OK"))
      .to.emit(cg, "VerifierDecision")
      .withArgs(1, true, "Satellite re-check OK", v2.address);
    const b = await cg.getBatch(1);
    expect(b.status).to.equal(Status.Active);
    expect(b.humanReviewed).to.equal(true);
  });

  it("two rejections make the rejection permanent", async function () {
    const { cg, oracle, v1, v2 } = await loadFixture(deployPanel);
    await cg.connect(v1).verifierDecision(1, false, "Baseline inflated");
    await cg.connect(v2).verifierDecision(1, false, "Confirmed");
    expect((await cg.getBatch(1)).status).to.equal(Status.Rejected);
    await expect(cg.connect(oracle).setRiskScore(1, 5, "", MODEL, DATA))
      .to.be.revertedWithCustomError(cg, "AlreadyReviewed");
  });

  it("a split vote leaves the batch frozen", async function () {
    const { cg, v1, v2 } = await loadFixture(deployPanel);
    await cg.connect(v1).verifierDecision(1, true, "");
    await cg.connect(v2).verifierDecision(1, false, "");
    expect((await cg.getBatch(1)).status).to.equal(Status.Flagged);
    expect((await cg.getVotes(1)).slice(0, 2)).to.deep.equal([1n, 1n]);
  });

  it("a verifier cannot vote twice to reach the threshold alone", async function () {
    const { cg, v1 } = await loadFixture(deployPanel);
    await cg.connect(v1).verifierDecision(1, true, "");
    await expect(cg.connect(v1).verifierDecision(1, true, "again"))
      .to.be.revertedWithCustomError(cg, "AlreadyVoted")
      .withArgs(1, v1.address);
  });

  it("only verifiers can vote: the registry and oracle roles are not enough", async function () {
    const { cg, oracle, stranger } = await loadFixture(deployPanel);
    const registryOnly = (await ethers.getSigners())[7];
    await cg.grantRole(await cg.REGISTRY_ROLE(), registryOnly.address);
    for (const who of [stranger, oracle, registryOnly]) {
      await expect(cg.connect(who).verifierDecision(1, true, ""))
        .to.be.revertedWithCustomError(cg, "AccessControlUnauthorizedAccount")
        .withArgs(who.address, await cg.VERIFIER_ROLE());
    }
  });

  it("a revoked verifier's earlier vote still counts, but they cannot vote again", async function () {
    const { cg, role, admin, v1, v2 } = await loadFixture(deployPanel);
    await cg.connect(v1).verifierDecision(1, true, "");
    await cg.revokeRole(role, v1.address);
    await expect(cg.connect(v1).verifierDecision(1, true, ""))
      .to.be.revertedWithCustomError(cg, "AccessControlUnauthorizedAccount");
    await cg.connect(v2).verifierDecision(1, true, "");
    expect(await cg.isTradable(1)).to.equal(true);
    expect(await cg.hasVoted(1, admin.address)).to.equal(false);
  });

  describe("threshold", function () {
    it("defaults to 1 so a single-key deployment still works", async function () {
      const { cg } = await loadFixture(deploy);
      expect(await cg.requiredApprovals()).to.equal(1);
    });

    it("only the admin can change it, and it can never be 0", async function () {
      const { cg, stranger } = await loadFixture(deploy);
      await expect(cg.setRequiredApprovals(3)).to.emit(cg, "RequiredApprovalsChanged").withArgs(3);
      expect(await cg.requiredApprovals()).to.equal(3);
      await expect(cg.setRequiredApprovals(0)).to.be.revertedWithCustomError(cg, "InvalidThreshold");
      await expect(cg.connect(stranger).setRequiredApprovals(1))
        .to.be.revertedWithCustomError(cg, "AccessControlUnauthorizedAccount");
    });

    it("reading votes for an unknown batch reverts", async function () {
      const { cg } = await loadFixture(deploy);
      await expect(cg.getVotes(9)).to.be.revertedWithCustomError(cg, "UnknownBatch").withArgs(9);
    });
  });
});
