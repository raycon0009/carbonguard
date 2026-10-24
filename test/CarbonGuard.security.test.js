const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-toolbox/network-helpers");
const { Status, MODEL, DATA, batch, deploy, deployWithBatch, deployWithActiveBatch } = require("./fixtures");

describe("CarbonGuard security edge cases", function () {
  describe("Only a human can unfreeze", function () {
    it("the oracle cannot unfreeze a Flagged batch by re-scoring it low", async function () {
      const { cg, oracle, developer, buyer } = await loadFixture(deployWithBatch);
      await cg.connect(oracle).setRiskScore(1, 95, "Phantom credits", MODEL, DATA);
      await cg.connect(oracle).setRiskScore(1, 5, "Looks fine now", ethers.id("v2"), DATA);
      const b = await cg.getBatch(1);
      expect(b.status).to.equal(Status.Flagged);
      expect(b.riskScore).to.equal(5); // score and provenance still updated for audit
      await expect(
        cg.connect(developer).safeTransferFrom(developer.address, buyer.address, 1, 1, "0x")
      ).to.be.revertedWithCustomError(cg, "NotTradable").withArgs(1, Status.Flagged);
    });

    it("a verifier can still approve a batch after a low re-score", async function () {
      const { cg, oracle } = await loadFixture(deployWithBatch);
      await cg.connect(oracle).setRiskScore(1, 95, "", MODEL, DATA);
      await cg.connect(oracle).setRiskScore(1, 5, "", MODEL, DATA);
      await cg.verifierDecision(1, true, "Field audit");
      expect(await cg.isTradable(1)).to.equal(true);
    });
  });

  describe("Quality gate covers every path", function () {
    it("Pending credits cannot be retired", async function () {
      const { cg, developer } = await loadFixture(deployWithBatch);
      await expect(cg.connect(developer).retire(1, 1, "Acme", "offset", false))
        .to.be.revertedWithCustomError(cg, "NotTradable").withArgs(1, Status.Pending);
    });

    it("Rejected credits can never be transferred or retired", async function () {
      const { cg, oracle, developer, buyer } = await loadFixture(deployWithBatch);
      await cg.connect(oracle).setRiskScore(1, 97, "", MODEL, DATA);
      await cg.verifierDecision(1, false, "Baseline inflated");
      await expect(
        cg.connect(developer).safeTransferFrom(developer.address, buyer.address, 1, 1, "0x")
      ).to.be.revertedWithCustomError(cg, "NotTradable").withArgs(1, Status.Rejected);
      await expect(cg.connect(developer).retire(1, 1, "Acme", "offset", false))
        .to.be.revertedWithCustomError(cg, "NotTradable").withArgs(1, Status.Rejected);
      await expect(cg.verifierDecision(1, true, "changed my mind"))
        .to.be.revertedWithCustomError(cg, "NotFlagged").withArgs(1, Status.Rejected);
    });

    it("an approved operator is still blocked by the gate", async function () {
      const { cg, oracle, developer, buyer } = await loadFixture(deployWithBatch);
      await cg.connect(developer).setApprovalForAll(buyer.address, true);
      await cg.connect(oracle).setRiskScore(1, 95, "", MODEL, DATA);
      await expect(
        cg.connect(buyer).safeTransferFrom(developer.address, buyer.address, 1, 1, "0x")
      ).to.be.revertedWithCustomError(cg, "NotTradable").withArgs(1, Status.Flagged);
    });

    it("an approved operator cannot retire someone else's credits", async function () {
      const { cg, developer, buyer } = await loadFixture(deployWithActiveBatch);
      await cg.connect(developer).setApprovalForAll(buyer.address, true);
      await expect(cg.connect(buyer).retire(1, 10, "Buyer Inc", "offset", false))
        .to.be.revertedWithCustomError(cg, "ERC1155InsufficientBalance");
      expect(await cg.balanceOf(developer.address, 1)).to.equal(1000);
    });

    it("a batch transfer mixing Active and Flagged ids reverts entirely", async function () {
      const { cg, oracle, developer, buyer } = await loadFixture(deployWithActiveBatch);
      await cg.registerBatch(batch({ vintage: 2022 }), developer.address);
      await cg.connect(oracle).setRiskScore(2, 90, "", MODEL, DATA);
      await expect(
        cg.connect(developer).safeBatchTransferFrom(developer.address, buyer.address, [1, 2], [10, 10], "0x")
      ).to.be.revertedWithCustomError(cg, "NotTradable").withArgs(2, Status.Flagged);
      expect(await cg.balanceOf(buyer.address, 1)).to.equal(0);
    });
  });

  describe("Serial range edge cases", function () {
    it("rejects minting to the zero address", async function () {
      const { cg } = await loadFixture(deploy);
      await expect(cg.registerBatch(batch(), ethers.ZeroAddress))
        .to.be.revertedWithCustomError(cg, "InvalidSerialRange");
    });

    it("a single-serial range mints exactly one tonne", async function () {
      const { cg, developer } = await loadFixture(deploy);
      await cg.registerBatch(batch({ serialFrom: 42n, serialTo: 42n }), developer.address);
      expect(await cg.balanceOf(developer.address, 1)).to.equal(1);
    });

    it("a range covering every uint256 overflows and mints nothing", async function () {
      const { cg, developer } = await loadFixture(deploy);
      await expect(cg.registerBatch(batch({ serialFrom: 0n, serialTo: ethers.MaxUint256 }), developer.address))
        .to.be.revertedWithPanic(0x11);
      expect(await cg.batchCount()).to.equal(0);
      expect(await cg.totalIssued()).to.equal(0);
    });

    it("the same serials under another registry or project are separate credits", async function () {
      const { cg, developer } = await loadFixture(deployWithBatch);
      await cg.registerBatch(batch({ registry: "GS" }), developer.address);
      await cg.registerBatch(batch({ projectId: "VCS9999" }), developer.address);
      expect(await cg.batchCount()).to.equal(3);
    });

    it("an overlap with a later range reports that range's token id", async function () {
      const { cg, developer } = await loadFixture(deployWithBatch);
      await cg.registerBatch(batch({ serialFrom: 3000n, serialTo: 3999n }), developer.address);
      await expect(cg.registerBatch(batch({ serialFrom: 3500n, serialTo: 4500n }), developer.address))
        .to.be.revertedWithCustomError(cg, "AlreadyTokenized")
        .withArgs(2, 3500, 3999);
    });

    it("a range that swallows an existing one is rejected", async function () {
      const { cg, developer } = await loadFixture(deployWithBatch);
      await expect(cg.registerBatch(batch({ serialFrom: 1n, serialTo: 100000n }), developer.address))
        .to.be.revertedWithCustomError(cg, "AlreadyTokenized")
        .withArgs(1, 1000, 1999);
    });
  });

  describe("Roles", function () {
    it("a revoked oracle can no longer score", async function () {
      const { cg, oracle } = await loadFixture(deployWithBatch);
      await cg.revokeRole(await cg.ORACLE_ROLE(), oracle.address);
      await expect(cg.connect(oracle).setRiskScore(1, 10, "", MODEL, DATA))
        .to.be.revertedWithCustomError(cg, "AccessControlUnauthorizedAccount");
    });

    it("a non-admin cannot grant itself any role", async function () {
      const { cg, stranger } = await loadFixture(deploy);
      await expect(cg.connect(stranger).grantRole(await cg.ORACLE_ROLE(), stranger.address))
        .to.be.revertedWithCustomError(cg, "AccessControlUnauthorizedAccount");
      await expect(cg.connect(stranger).grantRole(await cg.REGISTRY_ROLE(), stranger.address))
        .to.be.revertedWithCustomError(cg, "AccessControlUnauthorizedAccount");
    });
  });

  it("reading a retirement that does not exist reverts", async function () {
    const { cg } = await loadFixture(deploy);
    await expect(cg.getRetirement(0)).to.be.revertedWithPanic(0x32);
  });
});
