# CarbonGuard

This is a hackathon entry (IEEE ClimateChain, Carbon Markets & Emissions Transparency track). An explainable AI risk score for carbon credits is written on chain, and a contract freezes high-risk batches and blocks double counting. **The only submission is a 5-minute demo video**, so features should serve a moment in the video.

**Read `docs/HANDOFF.md` before starting work.** It covers architecture, frontend structure, generated files, demo state, pitfalls already hit, key numbers and the to-do list. `README.md` is the public description.

## Rules
- Ask clarifying questions until scope is clear before non-trivial work.
- Report results honestly. Never tune the model to make a known project score higher. The model is frozen (`model_hash` 0x38a70794…), so retrain only with the user's OK.
- Ask before any download, and give the filename, source and size. Never commit `.env`. Use only a test-only wallet for Sepolia.
- Sandbox input never leaves the browser and never goes on chain.
- Run npm commands from this folder (`carbonguard/`), not its parent.

## Commands
```bash
npm run test:all        # AI tests + contract tests + release checks (all must pass)
npm run chain           # local chain on :8545
npm run demo:local      # deploy + push scores + seed (re-run before each recording take)
npm run demo:monitor    # live: Alto Mayo 66 -> 86, listing suspended
npm run web             # dashboard on http://127.0.0.1:8080
```
When test counts change, update "84 contract and integration tests" and "54 AI pipeline tests" in README.md (`npm run check` enforces this).

`web/` is static HTML with ethers.js. There is no build step. Don't hand-edit the generated files `deployment.js`, `model.js`, `real_world.js`, `costs.js`, `sandbox_model.js`, `satellite_map.js` and `batch_inputs.js`; regenerate them.
