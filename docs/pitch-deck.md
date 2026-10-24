# Pitch deck outline (8 slides, ordered to match the judging criteria)

1. **Title.** CarbonGuard: *Every tonne scored by AI. Every tonne counted once.* Name, track (Carbon Markets & Emissions Transparency), and the GitHub repository link.

2. **The climate problem** (*Climate Impact*)
   - One stat per line: most REDD+ credits sampled didn't deliver (Science 2023) · cookstoves over-credited about 9x (Nature Sustainability 2024) · fewer than 16% of assessed credits were real reductions (Nature Communications 2024).
   - Three kinds of double counting: tokenisation (the Verra ban in 2022), selling, and claiming (Article 6).
   - The consequence: buyers lose trust and money stops reaching real projects.

3. **The solution in one picture.** Use the mermaid diagram from the README: registry data and satellite data go into the AI score and its reasons, then the oracle, then the contract, which leads to tradable / frozen / human review, and finally to retirement and a certificate.

4. **AI that explains itself** (*Innovation*, *Technical Execution*)
   - Weak supervision from research red flags, gradient boosting and an IsolationForest anomaly detector.
   - A screenshot of a High-risk row with its three reasons.
   - Metrics: AUC 0.986 vs. 0.933 for the rules alone · 98.6% High-tier precision · 100% of problem projects caught.
   - The `ai/charts/risk_by_type.png` chart.

5. **The blockchain guarantees** (*Technical Execution*)
   - A table of the 4 guards and the contract mechanism behind each.
   - Model provenance: the score, reasons, model hash and data hash all live on chain.
   - 84 contract tests + 54 AI tests, 100% branch coverage, a 300-step randomized invariant test.
   - Trained on 6,038 real registry projects plus synthetic data; judged only on held-out projects.
   - Real satellite data (Hansen, 30 m) on official boundaries: Kariba 99% of credits unbacked (score 6 → 64), Alto Mayo 77% (66 → 86, frozen), Southern Cardamom 59% (33 → 80, frozen).
   - Honest negative result: no better than chance on 65 California forest projects (AUC 0.56), because baseline-setting errors need forest-inventory data.
   - 2-of-3 human verifier panel, a regional-bias check (max 4.9-point gap on real data), and retirement for under 1 cent on Base.

6. **Demo.** A screenshot or GIF of the attack simulator and the certificate, plus a QR code linking to the GitHub repository, whose README shows how to run it locally.

7. **Practical usefulness and scale** (*Practical Usefulness*)
   - Users: registries and bridges, corporate buyers, Article 6 national registries, auditors.
   - Cost: no GPU and no paid API, the model trains in seconds, and it runs on an L2 for cents per transaction.
   - Roadmap: real Berkeley data plus the Global Forest Watch API, a Chainlink Functions oracle, a registry partnership, and ICVCM CCP label integration.

8. **Impact and close.** "Carbon markets fail when nobody can see what's inside a credit. CarbonGuard makes that visible, and makes counting the same tonne twice impossible." Add contacts and the GitHub link.

**Design tips:** use one idea per slide, large numbers, the dashboard's green / amber / red tier colours, and as little text as possible.
