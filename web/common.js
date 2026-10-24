// Shared helpers for the CarbonGuard dashboard and certificate pages.
/* global ethers */
const CG = (() => {
  const cfg = window.CG_CONFIG;
  const STATUS = ["Pending", "Active", "Flagged", "Rejected"];
  const iface = new ethers.Interface(cfg.abi);
  const readProvider = new ethers.JsonRpcProvider(cfg.rpc, cfg.chainId, { staticNetwork: true });
  const read = new ethers.Contract(cfg.address, cfg.abi, readProvider);
  // Example marketplace (optional: older deployments don't have one).
  const marketIface = cfg.market ? new ethers.Interface(cfg.market.abi) : null;
  const market = cfg.market ? new ethers.Contract(cfg.market.address, cfg.market.abi, readProvider) : null;

  const tier = (score) => (score > 70 ? "High" : score >= 35 ? "Medium" : "Low");
  const fmt = (n) => Number(n).toLocaleString("en-US");
  const fmtCompact = (n) =>
    Number(n).toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });
  const short = (h, a = 6, b = 4) => (h ? `${h.slice(0, a)}…${h.slice(-b)}` : "");
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const explorer = (kind, id) => (cfg.explorer ? `${cfg.explorer}/${kind}/${id}` : null);
  const reasons = (s) => (s && s !== "No significant red flags" ? s.split(" | ") : []);

  function toBatch(id, b, v) {
    return {
      id,
      registry: b.registry,
      projectId: b.projectId,
      projectType: b.projectType,
      country: b.country,
      vintage: Number(b.vintage),
      serialFrom: b.serialFrom,
      serialTo: b.serialTo,
      ca: b.correspondingAdjustment,
      status: STATUS[Number(b.status)],
      humanReviewed: b.humanReviewed,
      score: Number(b.riskScore),
      reasons: reasons(b.riskReasons),
      modelHash: b.modelHash,
      dataHash: b.dataHash,
      scoredAt: Number(b.scoredAt),
      issued: b.issued,
      retired: b.retired,
      votes: v ? { approvals: Number(v[0]), rejections: Number(v[1]), required: Number(v[2]) } : null,
    };
  }

  async function loadBatches() {
    const n = Number(await read.batchCount());
    const ids = Array.from({ length: n }, (_, i) => i + 1);
    const [raw, votes] = await Promise.all([
      Promise.all(ids.map((id) => read.getBatch(id))),
      Promise.all(ids.map((id) => read.getVotes(id))),
    ]);
    return raw.map((b, i) => toBatch(ids[i], b, votes[i]));
  }

  async function loadRetirements() {
    const n = Number(await read.retirementCount());
    const raw = await Promise.all(Array.from({ length: n }, (_, i) => read.getRetirement(i)));
    return raw.map((r, i) => ({
      id: i,
      tokenId: Number(r.tokenId),
      retiree: r.retiree,
      beneficiary: r.beneficiary,
      purpose: r.purpose,
      amount: r.amount,
      compliance: r.complianceClaim,
      score: Number(r.riskScoreAtRetirement),
      modelHash: r.modelHash,
      timestamp: Number(r.timestamp),
    }));
  }

  async function loadListings() {
    if (!market) return [];
    const n = Number(await market.listingCount());
    const ids = Array.from({ length: n }, (_, i) => i);
    const [raw, live] = await Promise.all([
      Promise.all(ids.map((id) => market.getListing(id))),
      Promise.all(ids.map((id) => market.isLive(id))),
    ]);
    return raw.map((l, i) => ({
      id: i,
      seller: l.seller,
      tokenId: Number(l.tokenId),
      remaining: l.remaining,
      price: l.pricePerTonne,
      open: l.open,
      live: live[i],
    }));
  }

  // Event logs since the deploy block.
  async function logs(filter, contract = read) {
    return contract.queryFilter(filter, cfg.deployBlock || 0);
  }
  // Block timestamps (seconds), one request per distinct block.
  async function blockTimes(evs) {
    const nums = [...new Set(evs.map((e) => e.blockNumber))];
    const blocks = await Promise.all(nums.map((n) => readProvider.getBlock(n)));
    return Object.fromEntries(nums.map((n, i) => [n, blocks[i] ? blocks[i].timestamp : 0]));
  }

  // Turn a revert into a sentence a judge can read.
  function humanError(e) {
    let parsed = null;
    const candidates = [e?.data, e?.error?.data, e?.info?.error?.data, e?.data?.data, e?.error?.data?.data];
    if (e?.revert) parsed = e.revert;
    for (const d of candidates) {
      if (parsed) break;
      if (typeof d === "string" && d.startsWith("0x")) {
        for (const i of [iface, marketIface]) {
          try {
            parsed = parsed || i?.parseError(d) || null;
          } catch {}
        }
      }
    }
    if (!parsed) {
      if (e?.code === "ACTION_REJECTED") return { name: "Rejected", text: "You rejected the transaction in your wallet." };
      return { name: "Error", text: e?.shortMessage || e?.message || String(e) };
    }
    const a = parsed.args || [];
    const texts = {
      AlreadyTokenized: () =>
        `Double tokenisation blocked: serials ${fmt(a[1])}–${fmt(a[2])} are already on chain as batch #${a[0]}.`,
      NotTradable: () =>
        `Quality gate: batch #${a[0]} is ${STATUS[Number(a[1])]} and cannot be moved or retired.`,
      NoCorrespondingAdjustment: () =>
        `Double claiming blocked: batch #${a[0]} has no Article 6 corresponding adjustment, so it cannot back a compliance claim.`,
      ERC1155InsufficientBalance: () =>
        `Double selling blocked: only ${fmt(a[1])} t available, ${fmt(a[2])} t requested. Retired tonnes are burned forever.`,
      AccessControlUnauthorizedAccount: () => `This wallet does not hold the required role.`,
      NotFlagged: () => `Batch #${a[0]} is ${STATUS[Number(a[1])]}; only Flagged batches can be reviewed.`,
      ZeroAmount: () => `Amount must be greater than zero.`,
      UnknownBatch: () => `Batch #${a[0]} does not exist.`,
      InvalidSerialRange: () => `Invalid serial range.`,
      AlreadyReviewed: () => `Batch #${a[0]} was rejected by a verifier; the decision is final.`,
      ScoreOutOfRange: () => `Score ${a[0]} is outside 0–100.`,
      AlreadyVoted: () => `This verifier already voted on batch #${a[0]}. A decision needs independent verifiers.`,
      InvalidThreshold: () => `The number of required verifier approvals must be at least 1.`,
      ERC1155MissingApprovalForAll: () => `This wallet is not approved to move credits owned by ${short(a[1])}.`,
      ERC1155InvalidReceiver: () => `The recipient ${short(a[0])} cannot receive carbon credits.`,
      ERC1155InvalidSender: () => `Invalid sender address.`,
      ERC1155InvalidApprover: () => `Invalid approver address.`,
      ERC1155InvalidOperator: () => `Invalid operator address.`,
      ERC1155InvalidArrayLength: () => `Token ids and amounts must have the same length.`,
      AccessControlBadConfirmation: () => `You can only renounce a role for your own wallet.`,
      // marketplace
      CreditsFrozen: () => `Quality gate: batch #${a[0]} is frozen by CarbonGuard, so it can't be listed or bought until verifiers approve it.`,
      MarketNotApproved: () => `Approve the marketplace to move your credits first (setApprovalForAll).`,
      InsufficientBalance: () => `You hold ${fmt(a[0])} t of this batch but tried to list ${fmt(a[1])} t.`,
      ListingClosed: () => `Listing #${a[0]} is closed (sold out or cancelled).`,
      InsufficientListing: () => `Only ${fmt(a[0])} t left in this listing; ${fmt(a[1])} t requested.`,
      WrongPayment: () => `Send exactly ${ethers.formatEther(a[0])} ETH for this purchase.`,
      NotSeller: () => `Only the seller can cancel this listing.`,
      NothingToWithdraw: () => `No sale proceeds to withdraw.`,
      WithdrawFailed: () => `The ETH transfer to the seller failed.`,
      ReentrancyGuardReentrantCall: () => `Blocked a re-entrant call into the marketplace.`,
    };
    return { name: parsed.name, text: (texts[parsed.name] || (() => parsed.name))() };
  }

  // ---- wallet
  let signer = null;
  async function connect() {
    if (!window.ethereum) throw new Error("No wallet found. Install MetaMask to send transactions.");
    const hex = "0x" + cfg.chainId.toString(16);
    try {
      await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId: hex }] });
    } catch (err) {
      if (err.code === 4902 && cfg.chainId === 31337) {
        await window.ethereum.request({
          method: "wallet_addEthereumChain",
          params: [{ chainId: hex, chainName: "Hardhat Local", rpcUrls: [cfg.rpc], nativeCurrency: { name: "ETH", symbol: "ETH", decimals: 18 } }],
        });
      } else throw err;
    }
    const bp = new ethers.BrowserProvider(window.ethereum);
    signer = await bp.getSigner();
    return signer;
  }
  const write = () => (signer ? new ethers.Contract(cfg.address, cfg.abi, signer) : null);
  const writeMarket = () => (signer && cfg.market ? new ethers.Contract(cfg.market.address, cfg.market.abi, signer) : null);

  return { cfg, STATUS, iface, read, market, readProvider, tier, fmt, fmtCompact, short, esc, explorer, loadBatches, loadRetirements, loadListings, logs, blockTimes, humanError, connect, write, writeMarket, getSigner: () => signer };
})();
