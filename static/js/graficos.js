/* Gráficos da Home em SVG próprio (sem biblioteca). Dados vêm de json_script; textos por textContent. */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var ALTURA = 240, MARGEM = { e: 40, d: 8, t: 8, b: 28 }, BARRA_MAX = 24, SLOT_MIN = 18;

  function el(nome, attrs, pai) {
    var n = document.createElementNS(NS, nome);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (pai) pai.appendChild(n);
    return n;
  }
  function ticks(max) {
    if (max <= 4) { var t = []; for (var i = 0; i <= Math.max(max, 1); i++) t.push(i); return t; }
    var passo = Math.pow(10, Math.floor(Math.log10(max / 4))), r = max / 4 / passo;
    passo *= r <= 1 ? 1 : r <= 2 ? 2 : r <= 5 ? 5 : 10;
    var out = []; for (var v = 0; v <= max + passo - 1; v += passo) { out.push(v); if (v >= max) break; }
    return out;
  }
  /* Segmento com topo arredondado (4px) e base reta. */
  function segTopo(x, y, w, h, r) {
    r = Math.min(r, h, w / 2);
    return "M" + x + "," + (y + h) + "V" + (y + r) + "Q" + x + "," + y + " " + (x + r) + "," + y +
      "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) + "V" + (y + h) + "Z";
  }

  function empilhado(raiz, dados) {
    var area = raiz.querySelector("[data-grafico-area]");
    if (!area) return;
    var ativo = -1, tip;

    function desenhar() {
      area.textContent = "";
      var n = dados.length, largura = (area.clientWidth || 600) - MARGEM.e;
      var slot = Math.max(SLOT_MIN, (largura - MARGEM.d) / n);
      var w = Math.ceil(MARGEM.d + slot * n), h = ALTURA, topo = MARGEM.t, base = h - MARGEM.b;
      var eixoY = el("svg", { "class": "g-svg g-svg--eixo", width: MARGEM.e, height: h, "aria-hidden": "true" }, area);
      var rolagem = document.createElement("div"); rolagem.className = "g-rolagem"; area.appendChild(rolagem);
      var max = Math.max.apply(null, dados.map(function (d) { return d.sucesso + d.erro; }).concat([1]));
      var tk = ticks(max), teto = tk[tk.length - 1], esc = (base - topo) / teto;
      var total = dados.reduce(function (s, d) { return s + d.sucesso + d.erro; }, 0);

      var svg = el("svg", { "class": "g-svg", width: w, height: h, viewBox: "0 0 " + w + " " + h, role: "img", tabindex: "0",
        "aria-label": raiz.querySelector(".grafico__titulo").textContent + ": " + total + " execuções em " + n + " intervalos. Use as setas para percorrer; os dados completos estão em Ver dados." }, null);
      rolagem.appendChild(svg);
      var defs = el("defs", {}, svg);
      var pad = el("pattern", { id: "g-hachura", width: 5, height: 5, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
      el("rect", { "class": "g-hachura-fundo", width: 5, height: 5 }, pad);
      el("line", { "class": "g-hachura-linha", x1: 0, y1: 0, x2: 0, y2: 5 }, pad);

      tk.forEach(function (v) {
        var y = base - v * esc;
        el("line", { "class": v === 0 ? "g-eixo" : "g-grade", x1: 0, x2: w, y1: y, y2: y }, svg);
        var t = el("text", { "class": "g-tick", x: MARGEM.e - 8, y: y + 4, "text-anchor": "end" }, eixoY); t.textContent = v;
      });
      var cada = Math.ceil(56 / slot);
      dados.forEach(function (d, i) {
        var cx = slot * i + slot / 2, bw = Math.min(BARRA_MAX, slot * 0.6), x = cx - bw / 2;
        var alvo = el("rect", { "class": "g-alvo", "data-i": i, x: slot * i, y: topo, width: slot, height: base - topo }, svg);
        var hs = d.sucesso * esc, he = d.erro * esc, y = base;
        if (d.sucesso) {
          var topoS = !d.erro;
          y -= hs;
          if (topoS) el("path", { "class": "g-sucesso", d: segTopo(x, y, bw, hs, 4) }, svg);
          else el("rect", { "class": "g-sucesso", x: x, y: y, width: bw, height: Math.max(hs - 2, 0) }, svg);
        }
        if (d.erro) { y -= he; el("path", { "class": "g-erro", d: segTopo(x, y, bw, he, 4) }, svg); }
        if (i % cada === 0) { var r = el("text", { "class": "g-tick", x: cx, y: h - 8, "text-anchor": "middle" }, svg); r.textContent = d.rotulo; }
      });

      function mostrar(i) {
        svg.querySelectorAll(".g-alvo--ativo").forEach(function (a) { a.classList.remove("g-alvo--ativo"); });
        if (i < 0) { if (tip) tip.hidden = true; ativo = -1; return; }
        ativo = i;
        var alvo = svg.querySelector('.g-alvo[data-i="' + i + '"]'); alvo.classList.add("g-alvo--ativo");
        var d = dados[i];
        if (!tip) { tip = document.createElement("div"); tip.className = "g-tip"; tip.setAttribute("role", "status"); area.parentNode.appendChild(tip); }
        tip.textContent = "";
        var t = document.createElement("span"); t.className = "g-tip__titulo"; t.textContent = d.rotulo; tip.appendChild(t);
        [["sucesso", "Sucesso", d.sucesso], ["erro", "Erro", d.erro]].forEach(function (l) {
          var linha = document.createElement("span"); linha.className = "g-tip__linha";
          var c = document.createElement("span"); c.className = "g-tip__chave g-tip__chave--" + l[0];
          var nome = document.createElement("span"); nome.textContent = l[1];
          var v = document.createElement("span"); v.className = "g-tip__valor"; v.textContent = l[2];
          linha.appendChild(c); linha.appendChild(nome); linha.appendChild(v); tip.appendChild(linha);
        });
        tip.hidden = false;
        var cx = MARGEM.e + slot * i + slot / 2 - rolagem.scrollLeft, pw = tip.offsetWidth, lim = area.parentNode.clientWidth;
        var esq = cx + 20 + pw <= lim ? cx + 20 : Math.max(cx - 20 - pw, 0);
        tip.style.left = (esq + area.offsetLeft) + "px"; tip.style.top = (area.offsetTop + topo) + "px";
      }
      svg.addEventListener("pointermove", function (ev) { var a = ev.target.closest && ev.target.closest(".g-alvo"); if (a) mostrar(+a.getAttribute("data-i")); });
      svg.addEventListener("pointerleave", function () { if (document.activeElement !== svg) mostrar(-1); });
      svg.addEventListener("focus", function () { mostrar(ativo < 0 ? n - 1 : ativo); });
      svg.addEventListener("blur", function () { mostrar(-1); });
      svg.addEventListener("keydown", function (ev) {
        var novo = { ArrowRight: ativo + 1, ArrowLeft: ativo - 1, Home: 0, End: n - 1 }[ev.key];
        if (novo === undefined) return;
        ev.preventDefault(); mostrar(Math.min(Math.max(novo, 0), n - 1));
      });
      if (rolagem.scrollWidth > rolagem.clientWidth) rolagem.scrollLeft = rolagem.scrollWidth;
    }
    desenhar();
    var ultima = area.clientWidth, tempo;
    if (window.ResizeObserver) new ResizeObserver(function () {
      if (area.clientWidth === ultima) return;
      clearTimeout(tempo); tempo = setTimeout(function () { ultima = area.clientWidth; desenhar(); }, 120);
    }).observe(area);
  }

  function barras(raiz) {
    var itens = raiz.querySelectorAll(".barras__barra"), max = 1;
    itens.forEach(function (b) { max = Math.max(max, +b.getAttribute("data-valor")); });
    itens.forEach(function (b) { b.style.width = (+b.getAttribute("data-valor") / max * 100) + "%"; });
  }

  document.querySelectorAll("[data-grafico]").forEach(function (raiz) {
    var tipo = raiz.getAttribute("data-tipo"), fonte = document.getElementById(raiz.getAttribute("data-dados")), dados = [];
    try { dados = JSON.parse(fonte.textContent) || []; } catch (e) {}
    if (!dados.length) return;
    if (tipo === "empilhado") empilhado(raiz, dados); else barras(raiz);
  });

  /* Trocar período: mantém o quadro, reduz opacidade e mostra "Atualizando…" até a página recarregar. */
  document.addEventListener("click", function (ev) {
    var link = ev.target.closest && ev.target.closest("[data-home] .segmentado__opcao");
    if (!link || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey) return;
    var home = link.closest("[data-home]"), aviso = home.querySelector("[data-home-carregando]");
    home.setAttribute("aria-busy", "true"); if (aviso) aviso.hidden = false;
  });
  window.addEventListener("pageshow", function (ev) {
    if (!ev.persisted) return;
    document.querySelectorAll("[data-home]").forEach(function (h) { h.removeAttribute("aria-busy"); var a = h.querySelector("[data-home-carregando]"); if (a) a.hidden = true; });
  });
})();
