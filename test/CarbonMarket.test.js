// Example marketplace: trading venues inherit CarbonGuard's quality gate.
const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-toolbox/network-helpers");
const { Status, MODEL, DATA, batch, deployWithActiveBatch } = require("./fixtures");

const PRICE = ethers.parseEther("0.001"); // per tonne

async function marketFixture() {
  const ctx = await deployWithActiveBatch(); // batch #1: 1,000 t owned by developer, Active
  const market = await ethers.deployContract("CarbonMarket", [await ctx.cg.getAddress()]);
  await ctx.cg.connect(ctx.developer).setApprovalForAll(await market.getAddress(), true);
  return { ...ctx, market };
}

async function listedFixture() {
  const ctx = await marketFixture();
  await ctx.market.connect(ctx.developer).list(1, 500, PRICE);
  return ctx;
}

const freeze = (ctx, id = 1) =>
  ctx.cg.connect(ctx.oracle).setRiskScore(id, 86, "Satellite shows 77% less avoided forest loss than claimed", MODEL, DATA);

describe("CarbonMarket (example trading venue)", function () {
  describe("listing", function () {
    it("lists tradable credits", async function () {
      const { market, developer } = await loadFixture(marketFixture);
      await expect(market.connect(developer).list(1, 500, PRICE))
        .to.emit(market, "Listed").withArgs(0, developer.address, 1, 500, PRICE);
      const l = await market.getListing(0);
      expect(l.seller).to.equal(developer.address);
      expect(l.remaining).to.equal(500n);
      expect(l.open).to.equal(true);
      expect(await market.listingCount()).to.equal(1n);
      expect(await market.isLive(0)).to.equal(true);
    });

    it("refuses pending, flagged and rejected credits", async function () {
      const ctx = await loadFixture(marketFixture);
      const { cg, market, developer, admin } = ctx;
      await cg.registerBatch(batch({ serialFrom: 5000n, serialTo: 5999n }), developer.address); // #2 Pending
      await expect(market.connect(developer).list(2, 1, PRICE)).to.be.revertedWithCustomError(market, "CreditsFrozen").withArgs(2);
      await freeze(ctx, 2); // Flagged
      expect((await cg.getBatch(2)).status).to.equal(Status.Flagged);
      await expect(market.connect(developer).list(2, 1, PRICE)).to.be.revertedWithCustomError(market, "CreditsFrozen");
      await cg.connect(admin).verifierDecision(2, false, "confirmed"); // Rejected
      await expect(market.connect(developer).list(2, 1, PRICE)).to.be.revertedWithCustomError(market, "CreditsFrozen");
    });

    it("refuses zero amounts and prices, unknown batches, missing approval and missing credits", async function () {
      const { cg, market, developer, buyer } = await loadFixture(marketFixture);
      await expect(market.connect(developer).list(1, 0, PRICE)).to.be.revertedWithCustomError(market, "ZeroAmount");
      await expect(market.connect(developer).list(1, 1, 0)).to.be.revertedWithCustomError(market, "ZeroAmount");
      await expect(market.connect(developer).list(99, 1, PRICE)).to.be.revertedWithCustomError(cg, "UnknownBatch");
      await expect(market.connect(buyer).list(1, 1, PRICE)).to.be.revertedWithCustomError(market, "MarketNotApproved");
      await cg.connect(buyer).setApprovalForAll(await market.getAddress(), true);
      await expect(market.connect(buyer).list(1, 1, PRICE))
        .to.be.revertedWithCustomError(market, "InsufficientBalance").withArgs(0, 1);
    });
  });

  describe("buying", function () {
    it("transfers credits to the buyer and credits the seller", async function () {
      const { cg, market, developer, buyer } = await loadFixture(listedFixture);
      await expect(market.connect(buyer).buy(0, 200, { value: 200n * PRICE }))
        .to.emit(market, "Purchased").withArgs(0, buyer.address, 200, 200n * PRICE);
      expect(await cg.balanceOf(buyer.address, 1)).to.equal(200n);
      expect(await cg.balanceOf(developer.address, 1)).to.equal(800n);
      expect((await market.getListing(0)).remaining).to.equal(300n);
      expect(await market.proceeds(developer.address)).to.equal(200n * PRICE);
    });

    it("closes the listing when it sells out", async function () {
      const { market, buyer } = await loadFixture(listedFixture);
      await market.connect(buyer).buy(0, 500, { value: 500n * PRICE });
      expect((await market.getListing(0)).open).to.equal(false);
      expect(await market.isLive(0)).to.equal(false);
      await expect(market.connect(buyer).buy(0, 1, { value: PRICE })).to.be.revertedWithCustomError(market, "ListingClosed");
    });

    it("requires exact payment and a valid amount", async function () {
      const { market, buyer } = await loadFixture(listedFixture);
      await expect(market.connect(buyer).buy(0, 10, { value: 9n * PRICE }))
        .to.be.revertedWithCustomError(market, "WrongPayment").withArgs(10n * PRICE, 9n * PRICE);
      await expect(market.connect(buyer).buy(0, 10, { value: 11n * PRICE })).to.be.revertedWithCustomError(market, "WrongPayment");
      await expect(market.connect(buyer).buy(0, 0, { value: 0 })).to.be.revertedWithCustomError(market, "ZeroAmount");
      await expect(market.connect(buyer).buy(0, 501, { value: 501n * PRICE }))
        .to.be.revertedWithCustomError(market, "InsufficientListing").withArgs(500, 501);
      await expect(market.connect(buyer).buy(7, 1, { value: PRICE })).to.be.revertedWithCustomError(market, "ListingClosed").withArgs(7);
    });

    it("reverts when the seller no longer holds the credits", async function () {
      const { cg, market, developer, buyer, stranger } = await loadFixture(listedFixture);
      await cg.connect(developer).safeTransferFrom(developer.address, stranger.address, 1, 900, "0x");
      await expect(market.connect(buyer).buy(0, 200, { value: 200n * PRICE }))
        .to.be.revertedWithCustomError(cg, "ERC1155InsufficientBalance");
    });
  });

  describe("credits frozen after listing (e.g. a new satellite measurement)", function () {
    it("suspends the listing: it cannot be bought", async function () {
      const ctx = await loadFixture(listedFixture);
      const { cg, market, buyer } = ctx;
      await freeze(ctx);
      expect((await market.getListing(0)).open).to.equal(true);
      expect(await market.isLive(0)).to.equal(false);
      await expect(market.connect(buyer).buy(0, 1, { value: PRICE }))
        .to.be.revertedWithCustomError(market, "CreditsFrozen").withArgs(1);
      expect(await cg.balanceOf(buyer.address, 1)).to.equal(0n);
    });

    it("CarbonGuard's own gate blocks the transfer too, even for an approved operator", async function () {
      const ctx = await loadFixture(listedFixture);
      const { cg, market, developer, buyer } = ctx;
      await freeze(ctx);
      // The market is an approved operator, but the token itself refuses to move.
      const marketSigner = await ethers.getImpersonatedSigner(await market.getAddress());
      await ethers.provider.send("hardhat_setBalance", [await market.getAddress(), "0x56BC75E2D63100000"]);
      await expect(cg.connect(marketSigner).safeTransferFrom(developer.address, buyer.address, 1, 1, "0x"))
        .to.be.revertedWithCustomError(cg, "NotTradable").withArgs(1, Status.Flagged);
    });

    it("comes back after the verifier panel approves the batch", async function () {
      const ctx = await loadFixture(listedFixture);
      const { cg, market, admin, buyer, stranger } = ctx;
      await cg.grantRole(await cg.VERIFIER_ROLE(), stranger.address);
      await cg.setRequiredApprovals(2);
      await freeze(ctx);
      await cg.connect(admin).verifierDecision(1, true, "field audit ok");
      expect(await market.isLive(0)).to.equal(false); // 1 of 2 approvals: still frozen
      await cg.connect(stranger).verifierDecision(1, true, "agree");
      expect(await market.isLive(0)).to.equal(true);
      await market.connect(buyer).buy(0, 1, { value: PRICE });
      expect(await cg.balanceOf(buyer.address, 1)).to.equal(1n);
    });
  });

  describe("cancel and withdraw", function () {
    it("only the seller can cancel, once", async function () {
      const { market, developer, buyer } = await loadFixture(listedFixture);
      await expect(market.connect(buyer).cancel(0)).to.be.revertedWithCustomError(market, "NotSeller");
      await expect(market.connect(developer).cancel(0)).to.emit(market, "Cancelled").withArgs(0);
      await expect(market.connect(developer).cancel(0)).to.be.revertedWithCustomError(market, "ListingClosed");
      await expect(market.connect(buyer).buy(0, 1, { value: PRICE })).to.be.revertedWithCustomError(market, "ListingClosed");
    });

    it("pays the seller exactly once", async function () {
      const { market, developer, buyer } = await loadFixture(listedFixture);
      await market.connect(buyer).buy(0, 100, { value: 100n * PRICE });
      await expect(market.connect(developer).withdraw()).to.changeEtherBalances(
        [developer, market], [100n * PRICE, -100n * PRICE]);
      await expect(market.connect(developer).withdraw()).to.be.revertedWithCustomError(market, "NothingToWithdraw");
    });
  });

  describe("re-entrancy", function () {
    it("a buyer contract cannot re-enter while receiving credits", async function () {
      const { market, buyer } = await loadFixture(listedFixture);
      const attacker = await ethers.deployContract("ReentrantTrader", [await market.getAddress()]);
      await expect(attacker.connect(buyer).buy(0, 10, { value: 10n * PRICE }))
        .to.be.revertedWithCustomError(market, "ReentrancyGuardReentrantCall");
      expect((await market.getListing(0)).remaining).to.equal(500n);
    });

    it("a seller contract cannot withdraw twice by re-entering", async function () {
      const { cg, market, buyer, oracle } = await loadFixture(marketFixture);
      const attacker = await ethers.deployContract("ReentrantTrader", [await market.getAddress()]);
      await cg.registerBatch(batch({ serialFrom: 7000n, serialTo: 7099n }), await attacker.getAddress()); // #2
      await cg.connect(oracle).setRiskScore(2, 10, "No significant red flags", MODEL, DATA);
      await attacker.listAll(2, 100, PRICE);
      await market.connect(buyer).buy(0, 100, { value: 100n * PRICE });
      await expect(attacker.withdraw()).to.be.revertedWithCustomError(market, "WithdrawFailed");
      expect(await market.proceeds(await attacker.getAddress())).to.equal(100n * PRICE);
    });
  });
});
