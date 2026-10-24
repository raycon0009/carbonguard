const { ethers } = require("hardhat");

const Status = { Pending: 0n, Active: 1n, Flagged: 2n, Rejected: 3n };
const MODEL = ethers.id("cg-risk-v1-model");
const DATA = ethers.id("projects_raw.csv");

const batch = (over = {}) => ({
  registry: "VCS",
  projectId: "VCS1389",
  projectType: "REDD+",
  country: "Peru",
  vintage: 2021,
  serialFrom: 1000n,
  serialTo: 1999n,
  correspondingAdjustment: false,
  ...over,
});

async function deploy() {
  const [admin, oracle, developer, buyer, stranger] = await ethers.getSigners();
  const cg = await ethers.deployContract("CarbonGuard", [admin.address]);
  await cg.grantRole(await cg.ORACLE_ROLE(), oracle.address);
  return { cg, admin, oracle, developer, buyer, stranger };
}

async function deployWithBatch() {
  const ctx = await deploy();
  await ctx.cg.registerBatch(batch(), ctx.developer.address);
  return ctx;
}

async function deployWithActiveBatch() {
  const ctx = await deployWithBatch();
  await ctx.cg.connect(ctx.oracle).setRiskScore(1, 22, "No significant red flags", MODEL, DATA);
  return ctx;
}

module.exports = { Status, MODEL, DATA, batch, deploy, deployWithBatch, deployWithActiveBatch };
