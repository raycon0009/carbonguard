# Demo video script (5:00)

Six beats, each mapped to the judging rubric. The voice-over is 594 words, which is about 4:15 at a calm 140 words a minute, leaving ~45 s for clicks, pauses and the live freeze. Every beat fits its slot at that pace; beat 4 has ~15 s spare for the freeze. Every number below is what the pages show (HANDOFF §9); don't round them differently on camera.

**Recording plan.** Record the screen and the voice separately. Record each beat as its own clip, then cut them together under the voice. If a take goes wrong, redo only that beat.

**Wording rules.** Scores are "statistical risk indicators, not allegations". Satellite checks are "yearly monitoring", never "real-time". Don't name any real project as High risk except Alto Mayo, which the demo flips on purpose.

---

## Before each take

Three terminals, each started in the `carbonguard` folder. Terminals 1 and 3 keep running for the whole session; terminal 2 is for one-off commands.

1. Terminal 1 (the blockchain): `npm run chain`. The first time, answer `n` to Hardhat's usage-data prompt.
2. Terminal 2 (control): `npm run demo:local` loads the demo and finishes in about 30 s. It's a reset, not a server: run it again only after `demo:monitor` has frozen Alto Mayo (or after a MetaMask buy, retire or vote) and you want another clean take. The attack buttons and everything else are read-only and need no reset.
3. Terminal 3 (the website): `npm run web`.
4. Browser: Chrome or Edge, one window, 1920×1080, light theme, zoom 100–110%, bookmarks bar hidden, no other tabs, notifications off.
5. Open the five pages in order, one tab each, or all at once from PowerShell:

   ```powershell
   start http://127.0.0.1:8080/story.html; start "http://127.0.0.1:8080/sandbox.html?preset=VCS902"; start http://127.0.0.1:8080/satellite.html; start http://127.0.0.1:8080/index.html; start "http://127.0.0.1:8080/certificate.html?id=1"
   ```

   After any `demo:local`, press F5 in every tab so it reads the fresh contracts.
6. Have terminal 2 ready with `npm run demo:monitor` typed but not run.

---

## Beat 1 · 0:00–0:45 · The problem
*Rubric: Climate Impact, Storytelling*

**Screen**
- `story.html`. Let the hero load: the Kariba map plays 2001 → 2024 with both areas drawn to scale. Don't move the mouse.
- After the map finishes, scroll slowly to **"Kariba is not an outlier"** and stop on the three research figures and the 1.04 billion t line.

**Voice-over**
> Kariba, a forest project in Zimbabwe, was credited with thirty-four million tonnes of CO₂ for deforestation it said it prevented. Those credits imply a hundred and twenty-four thousand hectares of forest saved. Satellites saw about twelve hundred.
>
> Kariba isn't an outlier. Peer-reviewed studies found most rainforest credits they sampled didn't reflect real reductions, and cookstove projects over-credited about nine times. And when credits go on chain, the same tonne can be tokenised, sold or claimed twice.
>
> Buyers can't tell good credits from bad ones. So money stops reaching the projects that really work.

**Caption (backup):** 124,011 ha credited. 1,231 ha seen by satellite.

---

## Beat 2 · 0:45–1:40 · How it works: the AI score
*Rubric: Innovation, Technical Execution*

**Screen**
- `sandbox.html?preset=VCS902`. The score shows **6 · Low risk**. Hold for a second.
- Click **Apply measured gap (99%)**. The score counts to **64 · Medium**, with "+58 in total from satellite evidence".
- Point the cursor at **Reasons it would write on chain** ("Satellite shows 99% less avoided forest loss than claimed"), then at **✓ Matches the Python model's score**.

**Voice-over**
> CarbonGuard puts an explainable AI quality gate in front of the market. Every credit batch gets a risk score from zero to a hundred, and the reasons behind it.
>
> Here's Kariba on registry data alone. Our model scored it six, low risk. That's a miss, and we report it.
>
> Now add our satellite measurement. The same frozen model now scores it sixty-four: a public warning, with the reason written in plain words. It stays just below the freeze line at seventy, because satellite evidence is its only red flag.
>
> This pre-check runs entirely in your browser. Nothing you type leaves the page, and it matches our Python pipeline exactly on all six thousand one hundred and seven real projects.

**Caption (backup):** Registry data only: 6. With satellite evidence: 64.

---

## Beat 3 · 1:40–2:15 · The satellite evidence
*Rubric: Innovation, Climate Impact*

**Screen**
- `satellite.html` (Kariba). Press **Play** (or space). Let it run through the shaded **credited 2011–2019** band.
- When it ends, hover over the **99%** figure, then the two to-scale squares (124,011 ha vs 1,231 ha).

**Voice-over**
> This is the evidence: real tree-cover loss from the Hansen Global Forest Change data, thirty-metre resolution, year by year, inside the project and in a ring around it.
>
> Forest loss was low before the project and stayed about the same low rate during it, inside and outside. Even using the method most favourable to the project, ninety-nine percent of its credits aren't backed by forest the record shows was saved.

**Caption (backup):** Yearly satellite monitoring: 99% of credits not backed.

---

## Beat 4 · 2:15–3:35 · The contract guards, live
*Rubric: Technical Execution, Practical Usefulness*

**Screen**
- `index.html`. Hold on the first viewport: **8.2M tCO₂e frozen as high-risk · 67.5% of supply kept away from buyers**.
- Click the three buttons in **Try to cheat the market**, one at a time, pausing on each **BLOCKED BY THE CONTRACT** result:
  1. **Re-bridge existing serials** → "Double tokenisation blocked … already on chain as batch #1."
  2. **Sell frozen credits** → "Quality gate: batch #16 is Flagged and cannot be moved or retired."
  3. **Make a compliance claim** → "Double claiming blocked: batch #2 has no Article 6 corresponding adjustment …"
- Move to the **Marketplace** card. Alto Mayo (VCS944, batch #22) is at **66 · LIVE**.
- Run `npm run demo:monitor` (off screen, or in a terminal beside the browser). Within one 12-second refresh, Alto Mayo's score counts to **86**, its stamp lands **FROZEN** and the listing shows **Suspended**. If the wait feels long, use a jump cut.

**Voice-over**
> The score lives on chain, in an ERC-1155 contract where one token is one tonne. Anything scored above seventy is frozen until independent verifiers review it. In this demo ledger, that's eight point two million tonnes kept away from buyers.
>
> Let's try to cheat. First, bridge registry serials that are already on chain, the failure that made Verra ban tokenising retired credits. The contract blocks it and names the batch that already holds them.
>
> Second, sell credits the AI froze. Blocked.
>
> Third, use a credit for a national or airline compliance claim when the host country made no Paris Agreement corresponding adjustment. Blocked. No double claiming.
>
> And it keeps watching. This is Alto Mayo in Peru, real registry data, listed for sale at sixty-six. A new yearly satellite measurement arrives… the oracle re-scores it to eighty-six, the contract freezes it, and the listing is suspended. Nobody can buy it now.

**Caption (backup):** Double tokenising, double selling, double claiming: all revert.

---

## Beat 5 · 3:35–4:25 · Can you trust it? Real-world impact
*Rubric: Climate Impact, Practical Usefulness*

**Screen**
- `index.html#trust` ("Can you trust the AI?"). Hold on **6,107 · 143 · 53%**, then the line **1.04 billion t … 375 million t not yet retired**.
- Scroll to **Where it fails · AUC 0.56**. Hold for two seconds.
- Switch to `certificate.html?id=1` (Contoso Airlines, 14,893 tCO₂e, AI risk 5). Click **Re-verify on chain** and let the six ticks land.

**Voice-over**
> We ran the frozen model on six thousand one hundred and seven real registry projects. Those it rates medium or high risk issued over a billion tonnes, and three hundred and seventy-five million of them are still for sale today. These are statistical risk indicators, not allegations.
>
> We also show where it fails: on California forest offsets it's no better than chance, because their problem leaves no trace in registry data.
>
> When a buyer retires clean credits, they're burned on chain and get a public certificate with the AI score and model hash at that moment. Don't trust the page: one click re-checks every claim against the contract.

**Caption (backup):** 375 million t from Medium/High-risk projects still for sale.

---

## Beat 6 · 4:25–5:00 · Who uses it, and the close
*Rubric: Practical Usefulness, Storytelling*

**Screen**
- Back to the top of `story.html`, or a title card with the tagline and the repository link: **github.com/raycon0009/carbonguard**.

**Voice-over**
> Registries and bridges can run CarbonGuard before tokenising. Buyers can screen credits before they pay. National Article 6 registries can enforce corresponding adjustments.
>
> Next, we'll extend satellite measurement to every forest project with a published boundary, and move the oracle to a decentralised network.
>
> CarbonGuard. Every tonne scored by AI. Every tonne counted once.

**Caption (backup):** Every tonne scored by AI. Every tonne counted once.

---

## Tips
- Rehearse once with a timer. If you run long, cut words rather than speaking faster. The easiest cuts are the second paragraph of beat 3 and the last paragraph of beat 2.
- Keep the cursor still while you talk; move it only to point.
- Record the voice in a quiet room, phone close to your mouth, one beat per file.
