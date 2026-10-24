---
target: web/satellite.html
total_score: 21
max_score: 32
na_heuristics: 5,9
p0_count: 0
p1_count: 2
target_identity: "file:C:\\Users\\rayan\\Downloads\\CarbonGuard\\carbonguard\\web\\satellite.html"
target_fingerprint: "sha256:ac0ea855a74519d71c0137ea603c66ded3d2bd724f8d7ec4cd8e2e3c6e232885"
target_path: "C:\\Users\\rayan\\Downloads\\CarbonGuard\\carbonguard\\web\\satellite.html"
timestamp: 2026-10-22T19-07-40Z
slug: web-satellite-html
---
Baseline critique of CarbonGuard web/ (dual-agent). Scores: dashboard 25/40, sandbox 30/40, satellite 21/32 (n/a 5,9), certificate 21/32 (n/a 5,7).
P1: climate problem not stated on dashboard; synthetic KPI numbers unlabelled; attack verdict understated (13px, jargon first); sandbox delta 6->64 not shown and slider below fold; satellite to-scale squares tiny and loss hard to see on video.
P2: text at 11-12px dominates index (161 elements <=12px); status pill contrast fails in light (amber 3.2:1, green 3.76:1); certificate word-break:break-all splits prose; contributions bars in brand green; satellite chart 9px; reject has no confirmation; skipped headings h1->h3 on sandbox/satellite.
Detector: overused-font x4, cramped-padding x2 (false positive), skipped-heading x2. No console errors, no overflow at 375, network hosts all allowed.
