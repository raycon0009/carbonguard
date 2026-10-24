# CarbonGuard: Project Summary

## 1. What it does (in one minute)

Each carbon credit is supposed to equal **one tonne of CO₂ removed or avoided, counted once**. In practice, many credits are over-claimed, and the same tonne can be counted twice in three ways: tokenised twice, sold twice, or claimed by two parties.

CarbonGuard fixes this with two layers:

1. **AI checks quality.** A machine-learning model gives every credit batch a 0–100 fraud and over-crediting risk score, plus the top 3 reasons in plain English.
2. **Blockchain enforces the rules.** A smart contract on Ethereum:
   - freezes high-risk credits (score > 70) until a human verifier reviews them
   - refuses to bring the same registry serial numbers on chain twice (**no double tokenisation**)
   - burns credits when they're retired, so they can't be resold (**no double selling**)
   - allows a credit to back a compliance claim (NDC or CORSIA) only if the host country made a Paris Agreement Article 6 corresponding adjustment (**no double claiming**)

Every retirement produces a **public certificate**, read live from the blockchain, that shows who retired how many tonnes, from which project, and which AI model scored it.

**Track:** Carbon Markets & Emissions Transparency, IEEE ClimateChain Global Hackathon.

---

## 2. Architecture

```
 ┌──────────────────────┐     ┌────────────────────────────┐
 │ Registry project data│     │ Satellite forest data      │
 │ (Verra, Gold Std,    │     │ (simulated; Global Forest  │
 │  ACR, CAR schema)    │     │  Watch in production)      │
 └──────────┬───────────┘     └─────────────┬──────────────┘
            └──────────────┬────────────────┘
                           ▼
        ┌───────────────────────────────────────┐
        │  AI LAYER  (Python, scikit-learn)     │   ai/
        │  1. Feature engineering               │
        │  2. Weak labels from expert red flags │
        │  3. Gradient Boosting + IsolationForest│
        │  4. Counterfactual explanations       │
        │  5. SHA-256 of model + data           │
        └──────────────────┬────────────────────┘
                           │ score, reasons, model hash, data hash
                           ▼
        ┌───────────────────────────────────────┐
        │  ORACLE BRIDGE  (Node.js / ethers)    │   scripts/oracle_push_scores.js
        │  registerBatch() → setRiskScore()     │
        └──────────────────┬────────────────────┘
                           ▼
        ┌───────────────────────────────────────┐
        │  SMART CONTRACT  (Solidity, ERC-1155) │   contracts/CarbonGuard.sol
        │  Pending → Active (≤70) / Flagged (>70)│
        │  Flagged → verifier → Active/Rejected │
        │  retire() = burn + certificate record │
        └──────────────────┬────────────────────┘
                           │ read-only RPC or MetaMask
                           ▼
        ┌───────────────────────────────────────┐
        │  WEB APP  (HTML + ethers.js, no build)│   web/
        │  Dashboard · attack simulator ·       │
        │  retire / review · certificate page   │
        └───────────────────────────────────────┘
```

### Tech stack

| Layer | Tools |
|---|---|
| AI | Python, pandas, scikit-learn (GradientBoostingRegressor, IsolationForest), matplotlib |
| Blockchain | Solidity 0.8.24, OpenZeppelin (ERC-1155, AccessControl), Hardhat (local chain) |
| Oracle / scripts | Node.js, ethers v6 |
| Frontend | Plain HTML/CSS/JS, ethers.js from a CDN, MetaMask |
| Testing | Hardhat + Chai (84 contract, marketplace, invariant, sandbox-parity and integration tests, 100% coverage) + pytest (54 AI pipeline tests, incl. real-world, satellite, satellite map and fairness) + CI with Slither |

### Folder map

| Path | Purpose |
|---|---|
| `ai/generate_data.py` | Creates the 420-project dataset (synthetic, using the registry column layout) |
| `ai/train_and_score.py` | Trains the model, scores projects, writes reasons and hashes |
| `ai/model/model_meta.json` | Model card: version, hashes, metrics, feature importance |
| `contracts/CarbonGuard.sol` | The smart contract |
| `test/CarbonGuard.test.js` | Contract tests |
| `scripts/deploy.js` | Deploys the contract and writes `web/deployment.js` |
| `scripts/oracle_push_scores.js` | Puts AI scores on chain |
| `scripts/seed_demo.js` | Creates demo retirements and runs guard checks |
| `web/index.html`, `web/certificate.html` | Dashboard and public certificate |

---

## 3. How each part works

### AI risk model
- **Features:** credits issued compared with the project's own estimate, vintage age, issuance spikes, retirement rate, buffer-pool shortfall, auditor changes, project-type history, and the satellite forest-cover gap.
- **Problem: no fraud labels exist.** So we use **weak supervision**. Seven rules taken from research (for example "issued more than 1.5× its estimate" or "satellite shows more than 30% less forest saved than claimed") each give soft evidence. These are combined into a probability that the project is suspicious.
- **Model:** gradient boosting learns from those soft labels and generalises them. An IsolationForest catches unusual projects that none of the rules describe. Final score = `100 × (0.8 × model + 0.2 × anomaly)`.
- **Tiers:** Low (below 35), Medium (35–70), High (above 70; frozen on chain).
- **Explanations:** for each feature, we reset it to a typical clean value and measure how much the risk drops. The 3 biggest drops become the reasons.
- **Results:** AUC 0.986 against the hidden ground truth (rules alone: 0.933). 98.6% of High-tier projects are genuinely bad, and 100% of problem projects score Medium or above.

### Smart contract
- **ERC-1155:** one token id = one project-vintage batch, and one token = 1 tCO₂e.
- **Roles:** `REGISTRY_ROLE` brings credits on chain and reviews flags. `ORACLE_ROLE` posts AI scores.
- **Status life cycle:** `Pending` → `Active` or `Flagged` → (verifier) `Active` or `Rejected`. Only `Active` credits can move or be retired; this is enforced in the `_update` hook.
- **Serial-range registry:** stores the ranges already on chain per (registry, project, vintage). Any overlap reverts with `AlreadyTokenized`.
- **`retire()`:** burns the tokens and stores a record with the beneficiary, purpose, amount, claim type, risk score and model hash.

### Web app
- Reads everything directly from the chain. There is no backend or database.
- The **attack simulator** runs three cheating attempts as dry runs (static calls) and shows each revert in plain language.
- With MetaMask connected, you can retire credits and act as the verifier.
- `certificate.html?id=N` is a shareable proof page that anyone can verify.

---

## 4. Key concepts (glossary)

| Term | Meaning |
|---|---|
| **Carbon credit** | A certificate representing 1 tonne of CO₂ reduced or removed |
| **Registry** | An organisation that issues credits (Verra, Gold Standard, ACR, CAR) |
| **Vintage** | The year the emission reduction happened |
| **Retirement** | Using a credit to offset emissions; it must then never be reused |
| **Over-crediting** | Issuing more credits than the real climate benefit |
| **Additionality** | Whether the project would have happened anyway without carbon money |
| **Buffer pool** | Credits held back as insurance against reversal (for example a forest fire) |
| **Double tokenisation** | The same registry credits turned into blockchain tokens twice |
| **Double claiming** | A country and a company both counting the same tonne |
| **Article 6 / corresponding adjustment** | Paris Agreement rule: the host country removes the tonne from its own tally when the credit is sold abroad |
| **Oracle** | Trusted bridge that brings off-chain data (here, AI scores) onto the blockchain |
| **Weak supervision** | Training a model on labels generated by expert rules instead of hand-labelled data |

---

## 5. Limitations and next steps
- Training uses 420 **synthetic** projects (calibrated to research) plus 6,038 **real** Berkeley-database projects. Real satellite measurements cover four REDD+ projects so far, and the model can't yet detect California-style baseline errors (AUC 0.56). **Next:** satellite measurement for every forest project with a published boundary, plus forest-inventory data.
- The oracle is a single key. **Next:** Chainlink Functions or a multi-signer oracle.
- **Deployment:** a local Hardhat chain for the demo; an Ethereum L2 (Base, Arbitrum or Polygon) for cheap real-world use.
