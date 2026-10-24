# CarbonGuard: developer handoff

This file is for picking up development in a new session without re-deriving context. `README.md` is the public description (problem, results, test table, commands). This file covers what the README doesn't: how the pieces fit, conventions, generated-file contracts, pitfalls already hit, and what's left to do.

Last updated: 2026-10-23 (frontend redesign "Registry Ledger", then the differentiators: score history + in-browser re-check, real-world tonnes figure, certificate re-verify, portfolio check; the Sepolia + GitHub Pages prep was then removed at the user's request).

---

## 1. Context

- **What it is.** An entry in the IEEE ClimateChain Global Hackathon, track *Carbon Markets & Emissions Transparency*. It's an online hackathon and **the only thing submitted is a 5-minute demo video**.
- **Judging rubric.** Climate Impact; Innovation & Creativity; Technical Execution; Practical Usefulness; Presentation & Storytelling. The video must clearly show the climate problem, how the solution works, and the real-world environmental impact.
- **Track examples.** Blockchain credit verification, real-time emissions tracking, smart contracts preventing double counting, transparent trading platforms. The marketplace covers the last one.
- **Consequence.** Every build should serve a moment in the video. Features that can't be shown are post-submission work.
- **The pitch.** "Every tonne scored by AI. Every tonne counted once." An explainable AI risk score is written on chain. A contract freezes high-risk batches and makes double tokenisation, double selling and double claiming impossible. The story leans into honest results: the AI missed Kariba on registry data alone; satellite evidence fixed that.

## 2. Ground rules (agreed with the user, keep following them)

1. **Ask before non-trivial work.** The user's global CLAUDE.md asks for clarifying questions (AskUserQuestion) until scope is unambiguous. Don't assume defaults on decisions that are theirs.
2. **Honest results.** Never tune the model so a specific known project scores higher. Fix principled causes and report numbers exactly as they come out, misses included. If a test has to be loosened, say so explicitly.
3. **Model is frozen for now.** Not retrained in recent builds. `model_hash` is `0x38a70794…1f43` and `data_hash` is `0x0290524a…85bd`. A retrain changes the hash everywhere (on chain, `web/model.js`, `web/sandbox_model.js`), so only retrain deliberately and with the user's OK.
4. **Downloads.** Ask before downloading anything (state filename, source and size). The connection is slow (~70 KB/s): prefer partial reads.
5. **No public deployment.** The demo runs only on the local Hardhat chain. Sepolia and GitHub Pages were removed on 2026-10-23 (faucet trouble; the user chose to skip it), so nothing may claim a hosted site, a testnet deployment or Etherscan verification. `.env` stays git-ignored and `npm run check` still verifies no keys are in the repo. The user creates the GitHub repo themselves.
6. **Data.** Raw external data stays git-ignored in `ai/data/external/`.
7. **Sandbox privacy.** Anything a user types into the sandbox must never leave the browser or go on chain. A test enforces this.
8. **Wording.** Scores are "statistical risk indicators, not allegations". Real projects nobody has investigated are never shown by name with a High score as an example (the sandbox uses a fictional over-issuer for that). Satellite checks are framed as yearly monitoring, not "real-time".
9. **Out of scope.** Don't build corporate emissions tracking.

## 3. Layout and data flow

Everything lives in `C:\Users\rayan\Downloads\CarbonGuard\carbonguard\`. The parent folder contains only this project.

> **Run npm commands from `carbonguard/`, not the parent.** The user hit `ENOENT package.json` by running `npm run demo:local` one level up.

```
Registry data (Berkeley VROD xlsx) ─┐                      ┌─> ai/real_world/*  (scores for 6,107 real projects)
Synthetic generator (420 projects) ─┼─> ai/train_and_score.py ─┼─> ai/model/*.joblib + model_meta.json (hashes)
Satellite (Hansen, cached .npz) ────┘   weak labels → GBM + IsolationForest ─┼─> ai/data/projects_scored.json
                                                                           └─> web/sandbox_model.js (via ai/web_model.py)
ai/data/projects_scored.json ──> scripts/oracle_push_scores.js ──> CarbonGuard.sol (21 demo batches) + web/model.js
scripts/seed_demo.js ──> retirements, verifier panel, marketplace listings, Alto Mayo demo batch (#22)
scripts/monitor_satellite.js ──> re-scores Alto Mayo 66 → 86 (freezes it, suspends its listing)
web/*.html ──(ethers.js, read-only RPC; MetaMask for writes)──> chain
```

### Toolchain
- Node v22.18, Hardhat 2.22, OpenZeppelin 5.x, Solidity 0.8.24 (optimizer 200, viaIR, cancun).
- Python 3.13. Versions are pinned in `ai/requirements.txt`, because a different sklearn or joblib changes the model file and so its hash.
- Satellite measurement needs extra packages from `ai/requirements-satellite.txt` (rasterio etc.). They're only needed for `npm run satellite`. `npm run map` reads the cached arrays.

## 4. Contracts

### `contracts/CarbonGuard.sol`
ERC-1155 + AccessControl. One token id = one project-vintage batch; one token = 1 tCO₂e.

- **Roles:** `REGISTRY_ROLE` (registerBatch), `ORACLE_ROLE` (setRiskScore), `VERIFIER_ROLE` (verifierDecision), `DEFAULT_ADMIN_ROLE` (setRequiredApprovals).
- **Status:** `Pending → Active (score ≤ 70) / Flagged (> 70)`. `Flagged → verifier panel → Active or Rejected` (Rejected is final). The oracle can only tighten: it can freeze an Active batch, never unfreeze a Flagged one.
- **Transfer gate:** `_update` blocks every transfer and burn of a non-Active batch.
- **Functions:** `registerBatch(BatchInput, owner)`, `setRiskScore(id, score, reasons, modelHash, dataHash)`, `verifierDecision(id, approve, note)`, `setRequiredApprovals(n)`, `retire(id, amount, beneficiary, purpose, complianceClaim)`.
- **Views:** `getBatch`, `getVotes`, `hasVoted`, `isTradable`, `retirementCount`, `getRetirement`, `batchCount`, `totalIssued`, `totalRetired`.
- **Errors:** UnknownBatch, InvalidSerialRange, AlreadyTokenized(existing, from, to), ScoreOutOfRange, AlreadyReviewed, NotFlagged, NotTradable(id, status), ZeroAmount, NoCorrespondingAdjustment, AlreadyVoted, InvalidThreshold.

### `contracts/CarbonMarket.sol` (example venue)
- **Functions:** `list(tokenId, amount, pricePerTonne)`, `buy(listingId, amount)` (payable, nonReentrant), `cancel`, `withdraw` (pull payments).
- **Views:** `listingCount`, `getListing`, `isLive`, `proceeds(address)`, `carbonGuard()`.
- **Escrow:** none. The seller keeps custody until a sale, so credits frozen while listed never get stuck in the market.
- **Tradability:** `isTradable` is checked both at listing and at purchase. CarbonGuard's own gate is a second, independent block.
- **Errors:** CreditsFrozen, ZeroAmount, MarketNotApproved, InsufficientBalance, ListingClosed, InsufficientListing, WrongPayment(expected, sent), NotSeller, NothingToWithdraw, WithdrawFailed.

### Test-only
`contracts/test/ReentrantTrader.sol` is an attacker mock. It's excluded from coverage (`.solcover.js`) and from Slither (`--filter-paths "node_modules|contracts/test"` in CI).

### Measured gas (`npm run gas` → `docs/costs.md`, `web/costs.js`)

| Action | Gas | Budget |
|---|---|---|
| Retire | ~289k | — |
| List | 172,168 | 200k |
| Buy | 108,599 | 150k |

Budgets are enforced in `test/pipeline.integration.test.js`.

## 5. Frontend (`web/`): static, no build step, no backend

Serve with `npm run web` (http-server on :8080, cache off). Pages load ethers 6.13.4 from cdnjs, plus Google Fonts (Newsreader, Inter Tight, JetBrains Mono).

**Design system: "Registry Ledger"** (redesigned 2026-10-23; the pre-redesign copy is at `..\web_before_redesign\`). Read [`DESIGN.md`](../DESIGN.md) before touching any page: tokens, type scale, components (ledger head, figure line, score + tier rail, stamp, gate, credited-vs-observed squares) and the only four allowed motion moments. Colour carries meaning only: `--low` = tradable/observed, `--med` = warning, `--high` = frozen/credited-but-unobserved. Light is the primary theme for the video; dark is a full peer. `PRODUCT.md` is the product record the impeccable skill reads; `.impeccable/critique/` holds the baseline critique snapshots.

| File | Role |
|---|---|
| `story.html` | **New.** The story intro (Persuade). Hero: "Credited for saving 124,011 hectares of forest. Satellites saw 1,231." with the real Kariba map (from `satellite_map.js`) playing 2001→2024 once, and both areas drawn to scale on it. Then the gap line, research context, three proofs (AI score, satellite evidence, contract guards) and "where it fails". Loads `real_world.js`, `satellite_map.js`, `motion.js`. Every page's logo links here. |
| `index.html` | Dashboard ("Live ledger"). Answers "what is CarbonGuard protecting right now?" in the first viewport: figure line (frozen tonnes lead) → demo-ledger label → impact line → ledger entry → Marketplace beside "Try to cheat the market" → Credit batches → "Can you trust the AI?" (real-world results, California AUC 0.56, fairness, model, provenance hashes) → Retired and certified. Render functions: `renderKpis`, `renderImpact`, `renderRealWorld`, `renderFairness`, `renderRows`, `renderListings`, `renderFeed`, `renderModel`, `openDrawer`, `simulate`, `send`, `review`, `openBuy`, `openModal`, plus `flashRow` and `noteChanges`. `refresh()` reloads from chain every **12 s**, diffs against the previous state (`prevBatches`, `prevLive`) and re-renders a table only when its signature (`rowsSig`, `listSig`, `feedSig`) changes. A batch whose score or status changed counts its score, re-lands its stamp and washes its row; the `#entry` line names the change. KPI figures count up on first load only. Reject needs a second click. Rows are keyboard-focusable (Enter opens the drawer). The trust section adds the aggregate tonnes line (`#rwTonnes`, from `tonnes_by_tier`). **Drawer: score history + re-check.** `showHistory` reads `RiskScored`, `VerifierVote` and `VerifierDecision` events for the batch (`CG.logs`, chunked) and lists them with block times. "Re-check in this browser" lazy-loads `sandbox_model.js`, `scorer.js` and `batch_inputs.js`, re-runs every score and compares number, reasons and model hash. Real batches (Alto Mayo 66 and 86) reproduce exactly; synthetic batches show the final-model score beside the out-of-fold one, with the reason (see §8). |
| `motion.js` | **New.** `CGM = {reduced, countTo, land, close, rail}`, WAAPI and rAF only, every helper respecting `prefers-reduced-motion`. Used by the dashboard and story page. `sandbox.html` has its own inline copy (privacy test). |
| `common.js` | Unchanged except two additions: `CG.logs(filter)` (event logs from the deploy block) and `CG.blockTimes(events)`. `CG` module: config, read provider and contracts (`read`, `market`), `loadBatches` / `loadRetirements` / `loadListings`, `humanError` (turns every revert into a sentence), wallet `connect` (auto-adds Hardhat network), `write()` / `writeMarket()`, formatters `fmt`, `fmtCompact`, `short`, `esc` (always escape on-chain strings). |
| `certificate.html` | Public retirement certificate, `?id=N`, read live from chain. Now also shows the project name (for satellite-measured projects), a cars-per-year equivalent (`impact.js`), the batch's current risk reasons, and a link back. Loads `impact.js`, `real_world.js`, `model.js` and `motion.js` too. **"Re-verify on chain"** re-reads six claims one by one (retirement exists, the burn `TransferSingle` to the zero address in the retirement transaction, batch retired total, risk below 70, model hash = model card, compliance ⇒ corresponding adjustment). |
| `sandbox.html` | Score pre-check. Loads **only** `sandbox_model.js` and `scorer.js` (no ethers, no network). The score is the hero, with the satellite slider directly under it. A ghost tick marks the same project's score without satellite data, and a delta line reads, for example, "+58 from satellite evidence". The project picker shows registry-only presets; `?preset=VCS902-sat` loads Kariba with the measured gap applied. When the slider sits at the rounded measured gap, the exact measured value is scored, so the "matches the Python model" line stays true. Uses a `<div>`, not a `<form>`. **Portfolio check** (bottom): a CSV (choose, drop, or the fictional example) is read with the File API and every row scored in the page; tonnes by tier, a share bar, a table sorted by risk, and "Inspect" loads a row into the instrument. Required columns: `holding, tonnes_held, project_type, first_vintage, last_vintage, total_issued, total_retired, max_to_median_issuance, buffer_pool_pct`; optional `est_annual_reductions` (blank = issuance matches it), `satellite_gap_pct` (positive %), `verifier_changes` (blank = 0). The template downloads from a Blob URL. |
| `scorer.js` | JS port of the model: `CGScorer = {scoreRaw, engineer, tier, fmt, roundHalfEven}`. `scoreRaw(M, raw)` returns `{risk, tier, reasons, effects, features, p, anomaly}`. |
| `satellite.html` | Animated forest-loss map (canvas + SVG outlines), play/pause (space bar too), year scrubber with a labelled "credited 2011–2019" band, huge gap figure, to-scale credited-vs-observed squares (moved off the map into the side panel), stats, yearly-rate chart with round ticks and a before/during average sentence, method as a numbered list. Supports `?project=VCS902\|VCS944\|VCS1748`; its sandbox link uses the `-sat` preset. |
| `style.css` | One stylesheet for all pages, rewritten. Tokens first (colour, type `--fs-*`, layout `--page-max --gutter --gap --radius --control-h --row-pad --header-h`, motion `--ease-out --dur-*`); recording mode (Build 4) should retune tokens only. Dark mode via `prefers-color-scheme` + `[data-theme]`. Sections are marked `/* sandbox */`, `/* satellite evidence */`, `/* certificate */`, `/* story intro */`. Below 760 px, `table.cards` turns tables into two-line rows and the nav becomes a horizontally scrolling second header row. Phone width (375 px) must not overflow. |

### Generated data files
Don't edit these by hand; regenerate them with the command listed.

| File | Global | Written by |
|---|---|---|
| `deployment.js` | `CG_CONFIG` (address, chainId, rpc, explorer, abi, `market: {address, abi}`) for the **local** chain | `scripts/deploy.js` |
| `batch_inputs.js` | `CG_BATCH_INPUTS` (registry inputs per demo project; real projects carry one input version per score the oracle writes) | `scripts/oracle_push_scores.js` (also `npm run export:inputs`, no chain needed). A test checks it is current. |
| `model.js` | `CG_MODEL` (model card, hashes, metrics) | `scripts/oracle_push_scores.js` |
| `real_world.js` | `CG_REAL_WORLD` (6,107-project results, satellite table, watchlist, fairness) | `ai/validate_real_world.py` |
| `costs.js` | `CG_COSTS` | `scripts/gas_report.js` |
| `impact.js` | `CG_IMPACT`, hand-written constants. Every number needs a source URL (tested). | — |
| `sandbox_model.js` (0.9 MB) | `CG_SANDBOX` (trees, presets, hashes) | `ai/web_model.py` (also run at the end of `npm run score`) |
| `satellite_map.js` (3.1 MB) | `CG_SAT` (sprite PNGs as data URIs, outlines, stats) | `ai/satellite/make_map.py` (`npm run map`). It also writes `docs/media/*_timelapse.gif`. |

### Cross-links between pages
- Every page shares one header: the logo → `story.html`, then nav "The problem · Live ledger · Pre-check · Satellite evidence" (`aria-current` on the current page). The certificate has the same nav plus "← Live ledger".
- Story → dashboard, sandbox (`?preset=VCS902`), satellite, and `index.html#trust`.
- Trust section → "See the satellite evidence" (satellite).
- Sandbox ↔ satellite link to each other (`satellite.html?project=…`, `sandbox.html?preset=…-sat`).
- Certificates are linked from the retirements table, the drawer and the retire modal.

### Dashboard tags
"Real project data · demo serials" (`realTag`) is shown on batches whose project ID has a satellite measurement in `CG_REAL_WORLD`. Currently that's Alto Mayo, batch #22.

## 6. Demo state and accounts

- Hardhat account #0 is admin, registry, oracle and verifier. Accounts #1 and #2 are extra verifiers (2-of-3 panel). Account #3 is the demo buyer.
- The keys are public Hardhat keys, printed by `npm run chain`. To use them in MetaMask, import #0.
- `npm run demo:local` produces this state (it was last run 2026-10-23 after the redesign rehearsal, so Alto Mayo is currently Live):

| Item | State |
|---|---|
| Batches #1–#21 | Demo batches: 9 Low, 5 Medium, 7 High. |
| Retirements | Three, plus a compliance retirement from #1. |
| #15 | Rejected by the panel. |
| #16 | 1 of 2 approvals. |
| Listings #0 / #1 | 5,000 t of a Low batch and 5,000 t of a Medium batch at 0.001 ETH/t; #3 bought 250 t. |
| #22 | Alto Mayo (VCS944) at its registry-only score 66, with 20,000 t listed. |

- `npm run demo:monitor` pushes Alto Mayo's satellite score of 86. The batch becomes Flagged and the listing shows Suspended within one 12-second refresh. `demo:local` deliberately doesn't run this, so the flip can be shown live. **Re-run `demo:local` before every recording take.**
- Background processes (started by Claude in the previous session; they die with a reboot or the session):
  - `npx hardhat node` on :8545
  - `npx --yes http-server web -p 8080 -c-1`

  If the chain restarts, run `demo:local` again: `deployment.js` is rewritten with the new address.

## 7. Verify ("all green")

```bash
npm run test:all     # 54 AI tests (pytest) + 84 contract/integration tests (Hardhat) + 8 release checks
npm run coverage     # 100% on CarbonGuard.sol and CarbonMarket.sol (81 passing, 1 pending under coverage)
```

- **Release checks** (`scripts/check_release.js`): no keys in the repo; `.env` is ignored; a LICENSE exists; hashes match the model and data; `web/model.js` matches the model card; **README test counts match**; deployment config is valid; no file over 50 MB.
- **README test counts.** When you add or remove tests, update "84 contract and integration tests" and "54 AI pipeline tests" in `README.md`. Also update the counts in `docs/pitch-deck.md` and `PROJECT_SUMMARY.md`, which aren't checked.
- **Tests that guard the frontend:**
  - `test/sandbox.parity.test.js`: JS score and reasons equal Python for all 6,107 projects (~1 s); hashes match; presets; no network or storage APIs in the sandbox page.
  - `test/pipeline.integration.test.js`: on-chain data equals the model output; the ABI in `deployment.js` equals the compiled ABI (includes the market); every contract error has a `humanError` message; attack simulator calls replay; gas budgets; impact constants are sourced.
  - `ai/tests/test_satellite_map.py`: the map conserves lost pixels and matches `satellite.json`.
- **Browser check** (built-in browser pane): load each page, confirm there are no console errors, and that there's no horizontal overflow at 375 px. Requests should go only to localhost, fonts.googleapis.com/gstatic and cdnjs.
- **Never verified yet:**
  - MetaMask write flows from the dashboard (Buy, Retire, verifier vote).
  - Slither. It runs only in GitHub CI and isn't installed locally.

## 8. Pitfalls already hit (don't re-learn these)

### sklearn → JS parity (`ai/web_model.py`, `web/scorer.js`)
- **float32 inputs.** sklearn casts inputs to float32 and compares them against float64 thresholds, so use `Math.fround(x) <= threshold`.
- **Leaf path lengths.** For IsolationForest, export per-tree `estimators_features_` (it can be a column permutation). Precompute each leaf's path as `_decision_path_lengths + _average_path_length_per_tree - 1`. The denominator is `n_estimators * _average_path_length([max_samples])`, and the score is `-2^(-depths/denom)`.
- **Tree sum.** For GBM: `raw = init_.constant_`, then add `lr * value` tree by tree, in sklearn's order.
- **Rounding.** `np.round` rounds half to even. Python's `.0f`, `.1f` and `.0%` also round exact ties to even, but JS `toFixed` doesn't. `fmt` handles this with `toFixed(d+25)` tie detection.
- **Reason order.** Reasons are sorted descending with a stable sort.
- **Speed inside node `vm`.** Global lookups like `Math` are slow there (20+ s), so `scorer.js` copies Math functions locally, and the test context is just `vm.createContext({ window })`.
- **Model numbers.** Thresholds and leaf values are exported at full float64 precision.

### Satellite map
- **Shading.** Shade cells by the **share** of land lost, never "any loss in the cell"; the latter exaggerates loss up to 250×.
- **Encoding.** Values are sqrt-encoded 8-bit and stored as a sprite PNG in a data URI.
- **Fading.** The area outside the 2–20 km ring is faded (`FADE=0.6`).
- **3-D coordinates.** Alto Mayo's boundary has them, so unpack points as `x, y, *_`.
- **Map resolution.** Kariba is 974×613 cells of 16×16 pixels.
- **No basemap.** There's no imagery basemap; land and water come from the Hansen `datamask`, and the page says so.

### Other
- **Scoring None values.** `ts.score_new` failed on a None satellite value; cast the column to float first.
- **Test helpers.** `ai/tests/helpers.py` patches `ts.WEB_MODEL` to a temp folder so tests don't overwrite `web/sandbox_model.js`.
- **Seeded listings.** The first version listed two Medium batches with huge amounts, which looked wrong. Now it lists one Low and one Medium, 5,000 t each.
- **Phone width.** The dashboard header overflowed by 8 px at 375 px. It was fixed by tightening header gap, link size and button padding; re-check after any header change.
- **Heredoc and sed edits.** These failed silently once and the old code was regenerated. Prefer the Edit tool, and check the output after any regeneration.

### Frontend redesign (2026-10-23)
- **The flip must stay in the first viewport.** With the ledger entry shown, the suspended Alto Mayo listing (the 3rd marketplace row) sits just above the fold at 1440×900. Adding anything above the marketplace pushes it below; re-check with `demo:local` → open the dashboard → `demo:monitor`.
- **Don't re-render tables on every refresh.** `renderRows` / `renderListings` / `renderFeed` compare a signature first. If you add a displayed field, add it to the signature, or the table won't update.
- **Sandbox words.** The privacy test's regex rejects the bare word `ethers`, `fetch(`, `<form`, `localStorage` and any `http(s)://` outside `<a href>` and the Google Fonts `<link>` tags, even in comments or copy.
- **impeccable's detector reports false low-contrast warnings.** Its static scan pairs the dark-mode text tokens (#e9eeea, #b3bdb7, #97a29c) with the light-mode `#ffffff` sheet. In the real render each theme uses its own pair, and light mode measures 5:1 or better. Check contrast in the browser rather than from the static scan.
- **Phone tables.** `table.cards` rows are CSS grids below 760 px. Give each cell its `c-score`, `c-proj`, `c-st`, `c-num`, `c-act` or `c-hide` class, or it lands in the wrong place.
- **Rehearsing leaves Alto Mayo frozen.** Every `demo:monitor` run does; re-run `npm run demo:local` before each recording take.

### Differentiators (2026-10-23)
- **Synthetic on-chain scores are out-of-fold.** `projects_scored.json` scores come from 5-fold `cross_val_predict`, so the final frozen model reproduces only some of them exactly (182 of 420; in the demo set, 13 of 21 match and the other 8 differ by 1–4 points). Reasons match for all 420. Two Medium demo batches (#10 VCS1146 69 → 73, #12 GS1122 68 → 72) would be High under the final model, and #10 is listed on the marketplace. The re-check says so openly; the user chose this over re-pushing final-model scores. Real projects are scored with the final model and reproduce exactly.
- **The chain stores scores, reasons and hashes, not inputs.** The re-check proves the published inputs + this model give the on-chain score; it says the inputs come from the registry/our data.
- **Class-name clash.** `.inputs` already styles the sandbox's inputs section (`margin-top: 48px`); the drawer's inputs table uses `.rc-inputs`.
- **Sandbox portfolio code** is inline and must keep passing the privacy test (no `fetch(`, no `http(s)://` in code or copy, no bare word `ethers`).

## 9. Key numbers (keep consistent everywhere)

### Synthetic test set
- AUC **0.977** vs 0.929 for the rules alone.
- High-tier precision **98.2%**.
- Problem projects caught (Medium or High): **98.1%**.

### Real projects (6,107)
- 143 High (2.3%), 1,217 Medium (19.9%).
- 53% of REDD+ tonnes rated Medium or High.
- Fairness: the largest unexplained regional gap is 1.4 points (synthetic) and 3.7 points (real).
- California (65 projects): AUC **0.56**, no better than chance. This is reported openly.
- Tonnes behind the tiers (`tonnes_by_tier`, aggregate only, no project named): the 1,360 Medium or High projects issued **1.04 billion t**; **375 million t** of that is not yet retired, so still for sale. High alone: 143 projects, 250 million t issued, 127 million t not yet retired. Shown on the story page and in the dashboard trust section, always with "statistical risk indicators, not allegations".

### Satellite measurements

| Project | Gap | Score: registry only → with satellite |
|---|---|---|
| Kariba VCS902 | 99% | 6 → 64 Medium |
| Alto Mayo VCS944 | 77% | 66 → 86 High |
| Southern Cardamom VCS1748 | 59% | 33 → 80 High |
| Kasigau VCS612 | not measurable | 13 |

Kariba's credits imply about 124,011 ha of forest saved; the satellite record shows 1,231 ha.

### Training
420 synthetic + 6,038 real projects, equal total weight per source. 69 judged projects are held out.

### Sandbox presets
Kariba 6 / 64, Alto Mayo 66 / 86, Southern Cardamom 33 / 80, Typical Wind 43 (Medium, chosen by a fixed rule and left as is), Cookstoves 6, Landfill 9, fictional over-issuer 82, blank 5.

### Tiers
Low < 35, Medium 35–70, High > 70 (frozen). This is the same in Python (`tier()`), JS and Solidity, and a test checks it.

## 10. Known stale content (fix when touching these files)

- **`docs/demo-script.md`** is the old **3:00** script. It's being replaced by build 5. Its numbers are stale: it says "7.6 million tonnes" (the dashboard now shows 8.2M blocked), "5.9 times" and "78%". It doesn't mention the sandbox, satellite page or marketplace.
- **`docs/pitch-deck.md`** slide 4 has old metrics (AUC 0.986 vs 0.933, 98.6%, 100%). The current figures are in §9.
- **`PROJECT_SUMMARY.md`** architecture diagram says satellite data is "simulated". It's now real Hansen data for four projects (simulated only for the synthetic set).

## 11. What's next

### Before submission (agreed order)
1. **Build 4: dashboard recording mode.** Larger text and a clean layout for screen capture (for example `?record=1`, which hides the wallet clutter, bumps font sizes and fixes the width at 1080p). Design details are not decided yet, so ask the user.
2. **Build 5: timed 5-minute video script.** Map it to the rubric (problem → how it works → real-world impact) and replace `docs/demo-script.md`. It should feature the sandbox (Kariba 6 → 64), the satellite time-lapse, the attack simulator, and the live Alto Mayo flip (`demo:monitor`) on the marketplace card. Frame satellite checks as yearly monitoring.
3. **Recommended:** a MetaMask dry run of Buy, Retire and verifier vote on the local chain.
4. Fix the stale docs in §10.
5. **GitHub repo: done (2026-10-24).** Public at https://github.com/raycon0009/carbonguard, `main` branch, commits as `raycon0009` with the GitHub noreply email (repo-local git config). Code only: there is no hosted site and no Sepolia deployment. Never commit `.env`.

### Post-submission ideas
These were discussed but not started:
- A real-project explorer for all 6,107 scored projects (conflicts with the naming rule; needs the user's decision).
- Satellite measurement at scale for every forest project with a published boundary.
- A signed or multi-signer oracle (Chainlink Functions), and an input hash written with each score so the re-check covers the inputs too.
- Forest-inventory data for improved forest management projects (the California miss).

## 12. Where the previous conversation lives

The full transcript of the session that built builds 1–3 is `C:\Users\rayan\.claude\projects\C--Users-rayan-Downloads-CarbonGuard\cadce364-5336-40f9-81f0-10130566cf64.jsonl`. The approved plan for builds 1–3 is `C:\Users\rayan\.claude\plans\pasted-content-id-9966-i-d-go-ancient-charm.md`.
