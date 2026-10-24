const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-toolbox/network-helpers");

const { Status, MODEL, DATA, batch, deploy, deployWithBatch, deployWithActiveBatch } = require("./fixtures");

describe("CarbonGuard", function () {
  describe("Bridging & double tokenisation", function () {
    it("mints one token per serial number to the project owner, in Pending", async function () {
      const { cg, developer } = await loadFixture(deploy);
      await expect(cg.registerBatch(batch(), developer.address))
        .to.emit(cg, "BatchRegistered")
        .withArgs(1, "VCS", "VCS1389", 2021, 1000, 1999, developer.address);
      expect(await cg.balanceOf(developer.address, 1)).to.equal(1000);
      const b = await cg.getBatch(1);
      expect(b.status).to.equal(Status.Pending);
      expect(b.issued).to.equal(1000);
      expect(await cg.totalIssued()).to.equal(1000);
    });

    it("rejects re-tokenising the exact same serial range", async function () {
      const { cg, developer } = await loadFixture(deployWithBatch);
      await expect(cg.registerBatch(batch(), developer.address))
        .to.be.revertedWithCustomError(cg, "AlreadyTokenized")
        .withArgs(1, 1000, 1999);
    });

    it("rejects a partially overlapping serial range and reports the overlap", async function () {
      const { cg, developer } = await loadFixture(deployWithBatch);
      await expect(cg.registerBatch(batch({ serialFrom: 1900n, serialTo: 2500n }), developer.address))
        .to.be.revertedWithCustomError(cg, "AlreadyTokenized")
        .withArgs(1, 1900, 1999);
    });

    it("allows adjacent ranges and the same serials in a different vintage", async function () {
      const { cg, developer } = await loadFixture(deployWithBatch);
      await cg.registerBatch(batch({ serialFrom: 2000n, serialTo: 2499n }), developer.address);
      await cg.registerBatch(batch({ vintage: 2022 }), developer.address);
      expect(await cg.batchCount()).to.equal(3);
    });

    it("rejects an inverted serial range", async function () {
      const { cg, developer } = await loadFixture(deploy);
      await expect(
        cg.registerBatch(batch({ serialFrom: 10n, serialTo: 5n }), developer.address)
      ).to.be.revertedWithCustomError(cg, "InvalidSerialRange");
    });

    it("only the registry role can bridge credits", async function () {
      const { cg, stranger } = await loadFixture(deploy);
      await expect(cg.connect(stranger).registerBatch(batch(), stranger.address))
        .to.be.revertedWithCustomError(cg, "AccessControlUnauthorizedAccount");
    });
  });

  describe("AI risk gate", function () {
    it("unscored (Pending) credits cannot be transferred", async function () {
      const { cg, developer, buyer } = await loadFixture(deployWithBatch);
      await expect(
        cg.connect(developer).safeTransferFrom(developer.address, buyer.address, 1, 10, "0x")
      ).to.be.revertedWithCustomError(cg, "NotTradable").withArgs(1, Status.Pending);
    });

    it("a low score activates the batch and records model provenance", async function () {
      const { cg, oracle } = await loadFixture(deployWithBatch);
      await expect(cg.connect(oracle).setRiskScore(1, 22, "No significant red flags", MODEL, DATA))
        .to.emit(cg, "RiskScored")
        .withArgs(1, 22, Status.Active, "No significant red flags", MODEL, DATA);
      const b = await cg.getBatch(1);
      expect(b.modelHash).to.equal(MODEL);
      expect(b.dataHash).to.equal(DATA);
      expect(await cg.isTradable(1)).to.equal(true);
    });

    it("a high score (> 70) freezes the batch", async function () {
      const { cg, oracle, developer, buyer } = await loadFixture(deployWithBatch);
      await cg.connect(oracle).setRiskScore(1, 95, "Issued 4.6x its own ex-ante estimate", MODEL, DATA);
      expect((await cg.getBatch(1)).status).to.equal(Status.Flagged);
      await expect(
        cg.connect(developer).safeTransferFrom(developer.address, buyer.address, 1, 10, "0x")
      ).to.be.revertedWithCustomError(cg, "NotTradable").withArgs(1, Status.Flagged);
    });

    it("exactly 70 is still tradable (threshold is strictly greater)", async function () {
      const { cg, oracle } = await loadFixture(deployWithBatch);
      await cg.connect(oracle).setRiskScore(1, 70, "", MODEL, DATA);
      expect(await cg.isTradable(1)).to.equal(true);
    });

    it("re-scoring with a newer model can freeze an active batch", async function () {
      const { cg, oracle } = await loadFixture(deployWithActiveBatch);
      await cg.connect(oracle).setRiskScore(1, 88, "Satellite gap", ethers.id("v2"), DATA);
      expect((await cg.getBatch(1)).status).to.equal(Status.Flagged);
    });

    it("only the oracle can score, and scores must be 0-100", async function () {
      const { cg, oracle, stranger } = await loadFixture(deployWithBatch);
      await expect(cg.connect(stranger).setRiskScore(1, 10, "", MODEL, DATA))
        .to.be.revertedWithCustomError(cg, "AccessControlUnauthorizedAccount");
      await expect(cg.connect(oracle).setRiskScore(1, 101, "", MODEL, DATA))
        .to.be.revertedWithCustomError(cg, "ScoreOutOfRange").withArgs(101);
    });

    it("rejects scoring an unknown batch", async function () {
      const { cg, oracle } = await loadFixture(deploy);
      await expect(cg.connect(oracle).setRiskScore(7, 10, "", MODEL, DATA))
        .to.be.revertedWithCustomError(cg, "UnknownBatch").withArgs(7);
    });
  });

  describe("Human verifier review", function () {
    it("a verifier can approve a flagged batch, and later AI scores cannot re-freeze it", async function () {
      const { cg, admin, oracle } = await loadFixture(deployWithBatch);
      await cg.connect(oracle).setRiskScore(1, 80, "Issuance spike", MODEL, DATA);
      await expect(cg.verifierDecision(1, true, "Field audit confirmed baseline"))
        .to.emit(cg, "VerifierDecision")
        .withArgs(1, true, "Field audit confirmed baseline", admin.address);
      expect(await cg.isTradable(1)).to.equal(true);
      await cg.connect(oracle).setRiskScore(1, 90, "still risky", MODEL, DATA);
      expect(await cg.isTradable(1)).to.equal(true);
    });

    it("a verifier can reject a flagged batch permanently", async function () {
      const { cg, oracle } = await loadFixture(deployWithBatch);
      await cg.connect(oracle).setRiskScore(1, 97, "Phantom credits", MODEL, DATA);
      await cg.verifierDecision(1, false, "Baseline inflated");
      expect((await cg.getBatch(1)).status).to.equal(Status.Rejected);
      await expect(cg.connect(oracle).setRiskScore(1, 5, "", MODEL, DATA))
        .to.be.revertedWithCustomError(cg, "AlreadyReviewed");
    });

    it("cannot review a batch that is not flagged", async function () {
      const { cg } = await loadFixture(deployWithActiveBatch);
      await expect(cg.verifierDecision(1, true, ""))
        .to.be.revertedWithCustomError(cg, "NotFlagged").withArgs(1, Status.Active);
    });

    it("only the registry role can review", async function () {
      const { cg, oracle, stranger } = await loadFixture(deployWithBatch);
      await cg.connect(oracle).setRiskScore(1, 97, "", MODEL, DATA);
      await expect(cg.connect(stranger).verifierDecision(1, true, ""))
        .to.be.revertedWithCustomError(cg, "AccessControlUnauthorizedAccount");
    });
  });

  describe("Retirement & double selling / double claiming", function () {
    it("burns retired credits and stores a public certificate", async function () {
      const { cg, developer, buyer } = await loadFixture(deployWithActiveBatch);
      await cg.connect(developer).safeTransferFrom(developer.address, buyer.address, 1, 300, "0x");
      await expect(cg.connect(buyer).retire(1, 250, "Acme Corp", "2025 Scope 1 offset", false))
        .to.emit(cg, "Retired")
        .withArgs(0, 1, buyer.address, "Acme Corp", 250, false, 22);

      expect(await cg.balanceOf(buyer.address, 1)).to.equal(50);
      expect(await cg.totalRetired()).to.equal(250);
      expect((await cg.getBatch(1)).retired).to.equal(250);
      expect(await cg.retirementCount()).to.equal(1);
      const r = await cg.getRetirement(0);
      expect(r.beneficiary).to.equal("Acme Corp");
      expect(r.modelHash).to.equal(MODEL);
      expect(r.riskScoreAtRetirement).to.equal(22);
    });

    it("a retired tonne can never be retired or sold again", async function () {
      const { cg, developer, buyer } = await loadFixture(deployWithActiveBatch);
      await cg.connect(developer).retire(1, 1000, "Acme Corp", "offset", false);
      await expect(cg.connect(developer).retire(1, 1, "Acme Corp", "again", false))
        .to.be.revertedWithCustomError(cg, "ERC1155InsufficientBalance");
      await expect(
        cg.connect(developer).safeTransferFrom(developer.address, buyer.address, 1, 1, "0x")
      ).to.be.revertedWithCustomError(cg, "ERC1155InsufficientBalance");
    });

    it("flagged credits cannot be retired", async function () {
      const { cg, oracle, developer } = await loadFixture(deployWithBatch);
      await cg.connect(oracle).setRiskScore(1, 95, "", MODEL, DATA);
      await expect(cg.connect(developer).retire(1, 10, "Acme", "offset", false))
        .to.be.revertedWithCustomError(cg, "NotTradable").withArgs(1, Status.Flagged);
    });

    it("compliance (NDC/CORSIA) claims need an Article 6 corresponding adjustment", async function () {
      const { cg, oracle, developer } = await loadFixture(deployWithActiveBatch);
      await expect(cg.connect(developer).retire(1, 10, "Acme", "CORSIA", true))
        .to.be.revertedWithCustomError(cg, "NoCorrespondingAdjustment").withArgs(1);

      await cg.registerBatch(batch({ projectId: "GS2001", correspondingAdjustment: true }), developer.address);
      await cg.connect(oracle).setRiskScore(2, 15, "", MODEL, DATA);
      await expect(cg.connect(developer).retire(2, 10, "Acme", "CORSIA", true)).to.emit(cg, "Retired");
    });

    it("rejects zero-amount retirements and unknown batches", async function () {
      const { cg, developer } = await loadFixture(deployWithActiveBatch);
      await expect(cg.connect(developer).retire(1, 0, "Acme", "", false))
        .to.be.revertedWithCustomError(cg, "ZeroAmount");
      await expect(cg.connect(developer).retire(9, 1, "Acme", "", false))
        .to.be.revertedWithCustomError(cg, "UnknownBatch");
    });
  });

  it("supports ERC1155 and AccessControl interfaces", async function () {
    const { cg } = await loadFixture(deploy);
    expect(await cg.supportsInterface("0xd9b67a26")).to.equal(true); // ERC1155
    expect(await cg.supportsInterface("0x7965db0b")).to.equal(true); // AccessControl
  });
});
