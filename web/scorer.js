// CarbonGuard risk model, in the browser. A line-by-line port of
// ai/train_and_score.py (engineer, explain, blend, tier) running the exact
// trees exported by ai/web_model.py into sandbox_model.js. Pure computation:
// no network access. test/sandbox.parity.test.js checks it reproduces the
// Python scores and reasons for all 6,107 real projects.
(function (root) {
  "use strict";
  // Local copies: global lookups are slow in sandboxed contexts (e.g. node's vm in the tests).
  const { fround, max, min, round, abs, pow, trunc } = Math;

  // sklearn compares float32 copies of the inputs with float64 thresholds.
  // `cols` maps a tree's feature index to a column of x (isolation trees see a subset).
  function leaf(t, x, cols) {
    let n = 0;
    while (t.left[n] !== -1) {
      const f = cols ? cols[t.feature[n]] : t.feature[n];
      n = fround(x[f]) <= t.threshold[n] ? t.left[n] : t.right[n];
    }
    return n;
  }

  function gbmPredict(M, x) {
    const g = M.gbm;
    let raw = g.init;
    for (const t of g.trees) raw += g.learning_rate * t.value[leaf(t, x)];
    return raw;
  }

  function isoScoreSamples(M, xNumeric) {
    let depths = 0;
    for (const t of M.iso.trees) depths += t.path[leaf(t, xNumeric, t.features)];
    return -pow(2, -(depths / M.iso.denominator));
  }

  const clip = (v, lo, hi) => min(max(v, lo), hi);

  // np.round: round half to even.
  function roundHalfEven(v) {
    const r = round(v);
    return abs(v % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
  }

  // Python's f"{v:.{d}f}": exact decimal value, ties to even (JS toFixed rounds ties up).
  function fmt(v, d) {
    const s = v.toFixed(d + 25);
    const cut = s.indexOf(".") + (d ? d + 1 : 0);
    const rest = s.slice(s.indexOf(".") + d + 1);
    if (/^50*$/.test(rest)) {
      const head = s.slice(0, cut).replace(/\.$/, "");
      if (Number(head[head.length - 1]) % 2 === 0) return head;
    }
    return v.toFixed(d);
  }

  function engineer(M, r) {
    const years = max(r.last_vintage - r.first_vintage + 1, 1);
    const isForest = M.forestry.includes(r.project_type);
    const sat = r.satellite_cover_delta_pct;
    return {
      over_issuance_ratio: r.total_issued / max(r.est_annual_reductions * years, 1),
      satellite_gap_pct: sat === null || sat === undefined || Number.isNaN(sat) ? 0 : max(-sat, 0),
      issuance_spike: r.max_to_median_issuance,
      vintage_age: M.current_year - r.first_vintage,
      retirement_rate: r.total_retired / max(r.total_issued, 1),
      buffer_shortfall: isForest ? max(15 - r.buffer_pool_pct, 0) : 0,
      verifier_changes: r.verifier_changes,
      type_overcrediting_history: M.history_of_overcrediting.includes(r.project_type) ? 1 : 0,
      type_low_additionality: M.low_additionality.includes(r.project_type) ? 1 : 0,
    };
  }

  const IS_ABNORMAL = {
    over_issuance_ratio: (v) => v > 1.2,
    satellite_gap_pct: (v) => v > 15,
    issuance_spike: (v) => v > 2.2,
    vintage_age: (v) => v > 12,
    retirement_rate: (v) => v < 0.35,
    buffer_shortfall: (v) => v > 0,
    verifier_changes: (v) => v >= 2,
    type_overcrediting_history: (v) => v === 1,
    type_low_additionality: (v) => v === 1,
  };

  function reasonText(feature, f, r) {
    const v = f[feature];
    switch (feature) {
      case "over_issuance_ratio": return `Issued ${fmt(v, 1)}x its own ex-ante estimate`;
      case "satellite_gap_pct": return `Satellite shows ${fmt(v, 0)}% less avoided forest loss than claimed`;
      case "issuance_spike": return `Issuance spike: peak year ${fmt(v, 1)}x the median year`;
      case "vintage_age": return `Old vintage (${trunc(r.first_vintage)}) - weak additionality`;
      case "retirement_rate": return `Only ${fmt(v * 100, 0)}% of credits ever retired - possible dumping`;
      case "buffer_shortfall": return `Thin permanence buffer (${fmt(r.buffer_pool_pct, 0)}% vs 15% norm)`;
      case "verifier_changes": return `Auditor changed ${trunc(v)} times`;
      case "type_overcrediting_history": return `${r.project_type} has documented over-crediting`;
      case "type_low_additionality": return `${r.project_type} rarely needs carbon finance`;
    }
  }

  function vector(M, f) {
    return M.features.map((k) => f[k]);
  }

  // Score one raw registry-style project (same fields as ai/data/real_projects.csv).
  function scoreRaw(M, r, topK = 3, minEffect = 0.03) {
    const f = engineer(M, r);
    const x = vector(M, f);
    const p = gbmPredict(M, x);
    // Counterfactual effect: risk drop when one feature is reset to the clean median.
    const effects = M.features.map((k, i) => {
      const xc = x.slice();
      xc[i] = M.clean_baseline[k];
      return { feature: k, effect: p - gbmPredict(M, xc) };
    });
    const ranked = effects.slice().sort((a, b) => b.effect - a.effect); // stable
    const abnormal = ranked.filter((e) => IS_ABNORMAL[e.feature](f[e.feature]));
    let top = abnormal.filter((e) => e.effect > minEffect).slice(0, topK);
    if (!top.length && p >= 0.5) top = abnormal.slice(0, topK);
    const reasons = top.map((e) => reasonText(e.feature, f, r));

    const [lo, hi] = M.anomaly_range;
    const anomaly = (-isoScoreSamples(M, M.numeric.map((k) => f[k])) - lo) / (hi - lo);
    const risk = clip(roundHalfEven(100 * (0.8 * clip(p, 0, 1) + 0.2 * clip(anomaly, 0, 1))), 0, 100);
    return { risk, tier: tier(risk), reasons, effects, features: f, p, anomaly };
  }

  function tier(score) {
    return score > 70 ? "High" : score >= 35 ? "Medium" : "Low";
  }

  root.CGScorer = { scoreRaw, engineer, tier, fmt, roundHalfEven };
})(typeof window !== "undefined" ? window : globalThis);
