# CarbonGuard design system: Registry Ledger

One visual world for every page in `web/`: the carbon registry's own ledger. Tonnes are entries, serial ranges are line items, a freeze is a stamp on the ledger, and the gap between *credited* and *observed* is the one comparison everything leads to. Light is primary (the video); dark mode is a full peer.

Tokens live on `:root` in `web/style.css`. Never hard-code a colour, size or duration in a page; recording mode (Build 4) will retune the tokens only.

## Colour: meaning only

Chrome is ink on paper. Hue appears only where it carries one of three meanings.

| Role | Token | Light | Dark | Means |
|---|---|---|---|---|
| Ground | `--paper` | #F4F5F1 | #0E1311 | page |
| Sheet | `--sheet` | #FFFFFF | #151B18 | tables, panels |
| Well | `--well` | #ECEEE8 | #1C2420 | inset areas, tracks |
| Ink | `--ink` | #121A16 | #E9EEEA | primary text, heavy rules, primary button |
| Ink 2 | `--ink-2` | #46514B | #B3BDB7 | secondary text (≥ 7:1) |
| Ink 3 | `--ink-3` | #5D6862 | #97A29C | meta, labels (≥ 4.5:1) |
| Rule | `--rule` | #D8DCD3 | #29322D | row rules, borders |
| Low · tradable · **observed** | `--low` / `--low-soft` | #1D6A47 / #E0EFE6 | #62C493 / #15301F | passed the gate; forest the satellite saw |
| Medium · warning | `--med` / `--med-soft` | #8A5900 / #F6EBD3 | #E2B158 / #33270F | tradable with a public warning |
| High · frozen · **credited, unobserved** | `--high` / `--high-soft` | #B02A1A / #FAE3DE | #F28472 / #3A1914 | frozen by the contract; tonnes credited but not seen |

- `--brand` is an alias of `--low` and is used only for the mark and links.
- Credited vs observed is always drawn the same way: credited = `--high`, dashed outline, no fill; observed = `--low`, solid fill.
- Red is a signal, not a texture: one red mark per object.

## Type

| Face | Job | Source |
|---|---|---|
| **Newsreader** (opsz 6–72, 400–600) | Display only: page titles, section titles, headline figures (scores, tonnes, the gap), certificate names | Google Fonts |
| **Inter Tight** (400–600) | Everything you read or operate: body, tables, labels, buttons | Google Fonts |
| **JetBrains Mono** (400–500) | Machine data only: serials, hashes, addresses, revert names | Google Fonts |

All figures use `font-variant-numeric: tabular-nums lining-nums`.

| Token | Size / line | Use |
|---|---|---|
| `--fs-meta` | 13 / 18 | labels, captions, sources (floor: nothing smaller) |
| `--fs-body` | 15 / 24 | body, table cells, buttons |
| `--fs-lead` | 17 / 26 | lead sentences, findings |
| `--fs-h3` | 20 / 26 | block titles (sans 600) |
| `--fs-h2` | 30 / 34 | section titles (serif 500) |
| `--fs-h1` | 40 / 44 | page title, lead figure (serif) |
| `--fs-figure` | 64 / 60 | the one hero figure per page: sandbox score, satellite gap |
| `--fs-display` | clamp(40px, 4.4vw, 64px) | story intro headline only |

Labels are sentence case. Tracked uppercase is reserved for the status **stamp**.

## Layout tokens

`--page-max: 1320px`, `--gutter: 32px` (16 px under 640 px), `--gap: 24px`, `--radius: 6px` (tight: cards and controls share it), `--radius-sm: 4px`, `--control-h: 38px`, `--row-pad: 14px`. Surfaces separate with a 1 px `--rule` line or one tone step, never a shadow. Shadows are only for what floats (drawer, modal, toast).

## Components

- **Ledger head.** Every section opens with a double rule (2 px ink, then 1 px ink 3 px below) above a serif title and one sentence. It is the accounting "totals" rule, and it replaces cards as the page structure.
- **Figure line.** KPIs are a run of figures on one ledger line, divided by 1 px rules: a serif figure with a grey sans unit and label. The answer figure (tonnes frozen) leads at `--fs-h1` in `--high`; the others sit at 28 px in ink. No tiles, icons or sparklines.
- **Score.** A serif numeral in its tier colour, followed by a 0–100 tier rail with ticks at 35 and 70. The same component appears in tables (small), the drawer (medium) and the sandbox (`--fs-figure`).
- **Stamp.** The status mark: a 1.5 px outline rectangle, 12 px uppercase sans 600, tracked +0.06em, in the status colour, with no fill. Labels: TRADABLE (low), FROZEN (high), REJECTED (high, struck), PENDING (ink 3), LIVE (low), SUSPENDED (high). One stamp per row.
- **Gate.** The attack simulator's verdict: a sheet that closes over the attempt (clip from the top), with "Blocked by the contract" + the `humanError` sentence as a serif headline and the revert name in mono beneath.
- **Credited vs observed.** Two squares drawn to scale (area = hectares). Credited is dashed `--high`, observed is solid `--low`. Used on the story intro, satellite page and dashboard trust section.
- **Buttons.** Primary: ink fill, paper text (one per view). Secondary: sheet with a 1 px rule border. Text actions: ink with an underline on hover. Height `--control-h`.
- **Tables.** No header band, no zebra. 13 px grey sentence-case headers, 15 px cells, numbers right-aligned in tabular figures, 1 px row rules. Below 760 px, `table.cards` turns each row into a two-line card: score on the left, project and figure in the middle, stamp and action on the right. Cells declare their slot with `c-score`, `c-proj`, `c-st`, `c-num`, `c-act` or `c-hide`.
- **Header.** Mark (shield in ink) linking to the story page, then the four-page nav ("The problem · Live ledger · Pre-check · Satellite evidence") with the current page on a well-tone pill. Below 760 px the nav becomes a second row that scrolls sideways inside itself.
- **Sub-headings.** A heading that must be an `h2` for document order but reads as a block title uses `h2.h3` (sans 17 px, 600).

## Motion

Motion means state change. Nothing performs an entrance except first-load KPI figures.

| Token | Value |
|---|---|
| `--ease-out` | cubic-bezier(0.23, 1, 0.32, 1) |
| `--ease-in-out` | cubic-bezier(0.77, 0, 0.175, 1) |
| `--dur-fast` | 160ms (hover, press, tabs) |
| `--dur` | 240ms (drawer, modal, stamp, gate) |
| `--dur-count` | 900ms (number count) |

The signature moments, the only ones allowed:

1. **Status flip** (dashboard refresh): a batch or listing whose score or status changed counts its score old → new, its stamp lands (scale 1.18 → 1, opacity 0 → 1, `--dur`), and its row holds a `--high-soft` wash that fades over 2.4 s. A one-line ledger entry above the marketplace names the change. Rows that did not change are not re-rendered.
2. **Gate closes** (attack simulator): the verdict sheet clips in from the top (`--dur`, `--ease-out`), then the headline appears.
3. **Sandbox score**: the score counts between values (`--dur-count`, cut short when interrupted), the tier rail moves with `transform: scaleX`, and the tier stamp re-lands when the tier changes.
4. **KPI figures**: count up from 0 on first load only.

CSS transitions and WAAPI only, with no libraries. Under `prefers-reduced-motion: reduce`, numbers jump to their final value, nothing scales or clips, and only short colour fades remain.
