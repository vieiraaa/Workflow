/* Orb "solving" (thinking-orbs 0.3.2, MIT; D-039) desenhada direto no canvas, sem React, como no
   Monitor de IA: resolvePreset → MODE_FRAMES → paintFrame. A tinta é o --accent do tema
   (roxo no claro, ouro no escuro) e acompanha a troca de tema. */
import { r as resolvePreset, M as MODE_FRAMES, p as paintFrame } from "../vendor/thinking-orbs/0.3.2/engine.js";

const ROXO_EEM = { r: 79, g: 31, b: 92 };
const BASE = 64;  // preset afinado pelo autor; escalado para o tamanho exibido

function tintaDoTema() {
  const hex = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  return m ? { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) } : ROXO_EEM;
}

function montarOrb(canvas, estado) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const { mode, speed, opts } = resolvePreset(estado, BASE);
  const quadro = MODE_FRAMES[mode];
  const reduzido = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let raf = 0;

  const desenhar = (t) => {
    const css = canvas.clientWidth || BASE, dpr = Math.min(2, devicePixelRatio || 1), k = (css / BASE) * dpr;
    if (canvas.width !== Math.round(css * dpr)) canvas.width = canvas.height = Math.round(css * dpr);
    ctx.setTransform(k, 0, 0, k, 0, 0);
    ctx.clearRect(0, 0, BASE, BASE);
    paintFrame(ctx, quadro(BASE, t, opts), false, tintaDoTema());
  };
  const laco = () => { desenhar((performance.now() / 1000) * speed); raf = requestAnimationFrame(laco); };

  // Só anima enquanto visível (a tela de carregamento começa escondida).
  new IntersectionObserver(([e]) => {
    cancelAnimationFrame(raf);
    if (!e.isIntersecting) return;
    if (reduzido) desenhar(0.6); else laco();
  }).observe(canvas);
}

document.querySelectorAll("canvas[data-orb]").forEach((c) => montarOrb(c, c.dataset.orb));
