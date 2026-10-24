// Shared motion helpers for the dashboard, story and certificate pages (see DESIGN.md, Motion).
// sandbox.html keeps its own inline copy: its privacy test allows only sandbox_model.js and scorer.js.
const CGM = (() => {
  const EASE = "cubic-bezier(0.23, 1, 0.32, 1)";
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const easeOut = (t) => 1 - Math.pow(1 - t, 4); // close to --ease-out, for number counts

  // Count a number from `from` to `to`. A new call on the same element cuts the old one short.
  function countTo(el, from, to, fmt = (v) => String(Math.round(v)), dur = 900) {
    if (!el) return;
    cancelAnimationFrame(el._cgRaf);
    if (reduced() || from === to) { el.textContent = fmt(to); return; }
    const t0 = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - t0) / dur);
      el.textContent = fmt(t < 1 ? from + (to - from) * easeOut(t) : to);
      if (t < 1) el._cgRaf = requestAnimationFrame(step);
    };
    el._cgRaf = requestAnimationFrame(step);
  }

  // A status stamp landing on the ledger.
  function land(el) {
    if (!el || reduced()) return;
    el.animate([{ transform: "scale(1.18)", opacity: 0 }, { transform: "scale(1)", opacity: 1 }], { duration: 240, easing: EASE });
  }

  // A sheet closing over its content from the top (the attack gate, the ledger entry).
  function close(el) {
    if (!el || reduced()) return;
    el.animate([{ clipPath: "inset(0 0 100% 0)" }, { clipPath: "inset(0 0 0 0)" }], { duration: 240, easing: EASE });
  }

  // Move a tier rail from one score to another.
  function rail(el, from, to) {
    if (!el) return;
    el.style.setProperty("--v", from / 100);
    el.getBoundingClientRect();
    el.style.setProperty("--v", to / 100);
  }

  return { reduced, countTo, land, close, rail };
})();
