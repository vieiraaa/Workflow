/* Desenho do fluxo como foi executado (TEL-07, EXE-15): só leitura, a partir do snapshot mascarado.
   Reaproveita as classes do nó do editor (.no, .no__icone, .no__titulo, .no__resumo). Sem innerHTML:
   todo texto entra por textContent (SEG-13). */
(function () {
  "use strict";
  var raiz = document.getElementById("fluxo-executado");
  var fonte = document.getElementById("grafo-execucao");
  if (!raiz || !fonte) return;

  var grafo;
  try { grafo = JSON.parse(fonte.textContent); } catch (e) { return; }
  var nos = (grafo && grafo.nos) || [];
  var arestas = (grafo && grafo.arestas) || [];
  var palco = raiz.querySelector("[data-palco]");
  var vazio = raiz.querySelector("[data-fluxo-vazio]");
  if (!palco || !nos.length) { if (vazio) vazio.hidden = false; return; }

  var SPRITE = raiz.dataset.sprite;
  var ICONES = { gatilho: "zap", http: "globe", saida: "flag" };
  var ROTULO = { sucesso: "Sucesso", erro: "Erro", nao_executado: "Não executado" };
  var LARG = 220, ALT = 64, MARGEM = 24, NS = "http://www.w3.org/2000/svg";

  function criar(tag, classe, texto) {
    var e = document.createElement(tag);
    if (classe) e.className = classe;
    if (texto !== undefined) e.textContent = texto;
    return e;
  }
  function icone(nome) {
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "icone icone--20");
    svg.setAttribute("aria-hidden", "true");
    var uso = document.createElementNS(NS, "use");
    uso.setAttribute("href", SPRITE + "#" + nome);
    svg.appendChild(uso);
    return svg;
  }
  function resumoDe(n) {
    if (n.tipo === "http" && n.status !== "nao_executado" && (n.metodo || n.host)) {
      return [n.metodo, n.host, n.http_status ? "→ " + n.http_status : ""].filter(Boolean).join(" ");
    }
    if (n.status === "nao_executado") return ROTULO.nao_executado;
    return n.duracao_texto ? n.duracao_texto : ROTULO[n.status] || "";
  }

  var vertical = null, larguraHorizontal = null, mundo = null, larguraTotal = 0, alturaTotal = 0;
  var LIMITE_ESCALA = 0.6;

  /* Posições: as do snapshot (horizontal) ou, se precisariam encolher demais, uma coluna na ordem de x. */
  function posicionar(emColuna) {
    var ordenados = nos.slice().sort(function (a, b) { return (Number(a.posicao && a.posicao.x) || 0) - (Number(b.posicao && b.posicao.x) || 0); });
    if (emColuna) {
      ordenados.forEach(function (n, i) { n._x = 0; n._y = i * (ALT + 36); });
    } else {
      nos.forEach(function (n) { var p = n.posicao || {}; n._x = Number(p.x) || 0; n._y = Number(p.y) || 0; });
    }
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nos.forEach(function (n) {
      minX = Math.min(minX, n._x); minY = Math.min(minY, n._y);
      maxX = Math.max(maxX, n._x + LARG); maxY = Math.max(maxY, n._y + ALT);
    });
    nos.forEach(function (n) { n._x = n._x - minX + MARGEM; n._y = n._y - minY + MARGEM; });
    larguraTotal = maxX - minX + 2 * MARGEM; alturaTotal = maxY - minY + 2 * MARGEM;
  }

  function desenhar(emColuna) {
    posicionar(emColuna);
    vertical = emColuna;
    if (mundo) palco.removeChild(mundo);
    mundo = criar("div", "fluxo-exec__mundo");
    mundo.style.width = larguraTotal + "px"; mundo.style.height = alturaTotal + "px";
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "fluxo-exec__arestas");
    svg.setAttribute("width", larguraTotal); svg.setAttribute("height", alturaTotal);
    svg.setAttribute("aria-hidden", "true");
    mundo.appendChild(svg);

    var porId = {};
    nos.forEach(function (n) {
      porId[n.id] = n;
      var b = criar("button", "fluxo-exec__no fluxo-exec__no--" + n.status);
      b.type = "button";
      b.style.left = n._x + "px"; b.style.top = n._y + "px";
      b.dataset.no = n.id;
      b.setAttribute("aria-label", (n.ordem ? "Nó " + n.ordem + ": " : "Nó não executado: ") + n.titulo +
        ", " + (ROTULO[n.status] || "") + ". Ver detalhes.");
      var no = criar("div", "no");
      var ic = criar("div", "no__icone no__icone--" + n.tipo);
      ic.appendChild(icone(ICONES[n.tipo] || "workflow"));
      var textos = criar("div", "no__textos");
      textos.appendChild(criar("div", "no__titulo", n.titulo));
      textos.appendChild(criar("div", "no__resumo", resumoDe(n)));
      no.appendChild(ic); no.appendChild(textos);
      if (n.ordem) no.appendChild(criar("span", "fluxo-exec__ordem", String(n.ordem)));
      if (n.ordem && n.duracao_texto) b.title = n.duracao_texto;
      b.appendChild(no);
      mundo.appendChild(b);
    });

    arestas.forEach(function (a) {
      var de = porId[a.de], para = porId[a.para];
      if (!de || !para) return;
      var d;
      if (emColuna) {
        var cx = LARG / 2, y1 = de._y + ALT, y2 = para._y, dy = Math.max(16, Math.abs(y2 - y1) / 2);
        d = "M" + (de._x + cx) + " " + y1 + " C" + (de._x + cx) + " " + (y1 + dy) + " " + (para._x + cx) + " " + (y2 - dy) + " " + (para._x + cx) + " " + y2;
      } else {
        var x1 = de._x + LARG, y1h = de._y + ALT / 2, x2 = para._x, y2h = para._y + ALT / 2;
        var dx = Math.max(40, Math.abs(x2 - x1) / 2);
        d = "M" + x1 + " " + y1h + " C" + (x1 + dx) + " " + y1h + " " + (x2 - dx) + " " + y2h + " " + x2 + " " + y2h;
      }
      var path = document.createElementNS(NS, "path");
      path.setAttribute("d", d);
      path.setAttribute("class", "fluxo-exec__aresta" + (para.status === "nao_executado" ? " fluxo-exec__aresta--inativa" : ""));
      svg.appendChild(path);
    });
    palco.appendChild(mundo);
  }

  /* Enquadra: reduz para caber na largura; se ficaria pequeno demais, passa para uma coluna. */
  function enquadrar() {
    var disp = palco.clientWidth;
    if (!disp) return;
    if (larguraHorizontal === null) { posicionar(false); larguraHorizontal = larguraTotal; }
    var emColuna = disp / larguraHorizontal < LIMITE_ESCALA;
    if (emColuna !== vertical) desenhar(emColuna);
    var escala = Math.min(1, disp / larguraTotal);
    mundo.style.transform = "scale(" + escala + ")";
    palco.style.height = Math.ceil(alturaTotal * escala) + "px";
  }
  enquadrar();
  if (window.ResizeObserver) new ResizeObserver(enquadrar).observe(palco);
  else window.addEventListener("resize", enquadrar);
  var cartao = raiz.closest("details");
  if (cartao) cartao.addEventListener("toggle", enquadrar);

  /* Clique no nó: abre o bloco do nó em "Nós executados" e rola até ele. */
  palco.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-no]");
    if (!b) return;
    var alvo = document.querySelector('[data-no-exec="' + (window.CSS && CSS.escape ? CSS.escape(b.dataset.no) : b.dataset.no) + '"]');
    if (!alvo) return;
    alvo.open = true;
    var reduzido = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    alvo.scrollIntoView({ behavior: reduzido ? "auto" : "smooth", block: "start" });
    var resumo = alvo.querySelector("summary");
    if (resumo) resumo.focus({ preventScroll: true });
  });
})();
