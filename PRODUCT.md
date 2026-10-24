# Product
<!-- impeccable:product-schema 1 -->

## Platform
web

## Users
- **Hackathon judges** (IEEE ClimateChain, Carbon Markets & Emissions Transparency track) who see the product only through a 5-minute demo video recorded at 1080p. They must understand the climate problem, how CarbonGuard works and its real-world impact, without clicking anything themselves.
- **Intended real users** (the product's story, not current users): registries and tokenisation bridges screening credits before bridging; corporate buyers screening credits and publishing retirement certificates; national Article 6 registries; auditors and journalists reading scores, reasons and model hashes on chain.

## Product Purpose
A quality gate for carbon credits. An explainable AI model scores every credit batch for over-crediting risk; the score, its top-3 reasons and the model and data hashes are written on chain. A smart contract freezes batches scoring above 70 until independent human verifiers decide, and makes double tokenisation, double selling and double claiming impossible. Success for the submission: a judge remembers "credits claimed vs forest actually saved", sees a credit get frozen live, and trusts the AI because its misses are shown.

## Positioning
"Every tonne scored by AI. Every tonne counted once." The AI can only tighten (freeze), never loosen; only humans unfreeze. Real satellite evidence (Hansen Global Forest Change) is measured against real registry projects, and the results are reported honestly, including where the model fails (California AUC 0.56).

## Operating Context
- The demo runs on a local Hardhat chain (`npm run demo:local`), with a live beat (`npm run demo:monitor`) that re-scores Alto Mayo 66 → 86 by yearly satellite monitoring, freezing its batch and suspending its marketplace listing within one 12 s refresh.
- Pages: dashboard (`index.html`), score pre-check sandbox (`sandbox.html`, browser-only), satellite evidence (`satellite.html`), public retirement certificate (`certificate.html?id=N`), and a story intro.
- Read-only for judges: an attack simulator runs static calls against the live contract with no wallet. Wallet writes (buy, retire, verifier vote) exist but are secondary.

## Capabilities and Constraints
- Static HTML/CSS/JS, no build step, served by `npm run web`. External requests only to fonts.googleapis.com, fonts.gstatic.com and cdnjs.cloudflare.com (ethers 6.13.4).
- Generated data files must not be hand-edited: `deployment.js`, `model.js`, `real_world.js`, `costs.js`, `sandbox_model.js`, `satellite_map.js`.
- The sandbox page may load only `sandbox_model.js` and `scorer.js`, with no network, storage or wallet APIs (enforced by `test/sandbox.parity.test.js`).
- Tiers: Low < 35, Medium 35–70, High > 70 (frozen). The model is frozen (`model_hash` 0x38a70794…1f43).
- Light and dark modes are both required. No horizontal overflow at 375 px.

## Brand Commitments
- Name: CarbonGuard. Tagline: "Every tonne scored by AI. Every tonne counted once."
- Wording: scores are "statistical risk indicators, not allegations". Uninvestigated real projects are never shown by name with a High score as an example. Satellite checks are "yearly monitoring", never "real-time".
- Honest results are part of the brand: misses are shown, never hidden or tuned away.

## Evidence on Hand
- Real data: 6,107 scored registry projects (Berkeley VROD v2026-08), satellite measurements for Kariba, Alto Mayo and Southern Cardamom (Kasigau not measurable), fairness results, model card. See `web/real_world.js`, `web/model.js`, `web/satellite_map.js`, and `docs/HANDOFF.md` §9 for the canonical figures.
- Kariba: credits imply about 124,011 ha of forest saved; satellites show 1,231 ha (99% gap), and Verra found 15.2M excess credits out of 26.8M issued.
- Demo batches #1–#21 are synthetic, calibrated to published research; batch #22 carries Alto Mayo's real data with illustrative serials.
- Absent, and never to be fabricated: users, customers, testimonials, partner logos, adoption figures, or any vanity metric.

## Product Principles
1. Every visible feature serves a moment in the 5-minute video.
2. Show the mechanism working on live data rather than describing it.
3. Honesty sells: show the misses and limits next to the wins.
4. Colour carries meaning (risk tier, frozen vs tradable, credited vs observed), never decoration.
5. Credit every data source on the page that uses it.
