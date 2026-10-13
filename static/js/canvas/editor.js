/* Editor de canvas v2 (TEL-05, EDV-01..03). JS fino: converte Drawflow <-> grafo canônico v2 e cuida da UX.
   Toda validação é do servidor; as pendências voltam e são mostradas no nó certo (GRF-05).
   Dado do usuário só entra no DOM por textContent / value. */
(function () {
  "use strict";
  var raiz = document.querySelector("[data-editor]");
  if (!raiz || typeof Drawflow === "undefined") return;

  var C = window.ConversorGrafo;
  var TIPOS = C.TIPOS;
  var sprite = raiz.dataset.sprite;
  var urlSalvar = raiz.dataset.urlSalvar;
  var urlStatus = raiz.dataset.urlStatus;
  var urlExecutarNo = raiz.dataset.urlExecutarNo || "";
  var urlPrevia = raiz.dataset.urlPrevia || "";
  var urlCredenciais = raiz.dataset.urlCredenciais || "";
  var podeCodigo = raiz.dataset.podeCodigo !== "false";
  var atualizadoEm = raiz.dataset.atualizadoEm;
  var status = raiz.dataset.status || "rascunho";
  var csrf = (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value || "";

  function lerJson(id, padrao) {
    var e = document.getElementById(id);
    if (!e) return padrao;
    try { return JSON.parse(e.textContent); } catch (_) { return padrao; }
  }
  var credenciais = lerJson("credenciais-lista", []);

  var el = function (id) { return raiz.querySelector("[data-" + id + "]"); };
  var areaCanvas = el("canvas"), inspector = el("inspector-corpo"), banner = el("banner");
  var btnSalvar = el("salvar"), chipStatus = el("status"), btnStatus = el("alternar-status");
  var chipPend = el("pendencias"), popPend = el("pendencias-lista"), dicaVazio = el("dica-vazio");
  var listaPaleta = el("paleta-lista"), buscaPaleta = el("paleta-busca"), vazioPaleta = el("paleta-vazia");

  var editor = new Drawflow(areaCanvas);
  editor.reroute = false;
  editor.zoom_max = 1.6; editor.zoom_min = 0.4;
  editor.key = function () {}; // Delete/Ctrl+S são tratados abaixo, com checagem de foco.
  editor.start();

  var carregando = true, sujo = false, selecionado = null, pendencias = [];
  var resultados = {};      // cid -> resultado do último teste (executar este nó)
  var contagemArestas = []; // [{de, saida, para, entrada, itens}]
  var multi = {};           // dfId -> true (seleção múltipla com Shift)

  /* ---------- utilidades de DOM ---------- */
  function criar(tag, classe, texto) {
    var e = document.createElement(tag);
    if (classe) e.className = classe;
    if (texto !== undefined) e.textContent = texto;
    return e;
  }
  function icone(nome, tamanho) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icone icone--" + (tamanho || 20));
    svg.setAttribute("aria-hidden", "true");
    var uso = document.createElementNS("http://www.w3.org/2000/svg", "use");
    uso.setAttribute("href", sprite + "#" + nome);
    svg.appendChild(uso);
    return svg;
  }
  function avisar(tag, texto) { if (window.mostrarToast) window.mostrarToast(tag, texto); }

  /* ---------- estado sujo / status ---------- */
  function marcarSujo() {
    if (carregando) return;
    sujo = true;
    dicaVazio.hidden = todosOsNos().length > 0;
  }
  function marcarLimpo() { sujo = false; }
  window.addEventListener("beforeunload", function (ev) {
    if (sujo) { ev.preventDefault(); ev.returnValue = ""; }
  });

  function atualizarStatus() {
    chipStatus.className = "badge badge--" + (status === "ativo" ? "ativo" : "rascunho");
    chipStatus.textContent = status === "ativo" ? "Ativo" : "Rascunho";
    btnStatus.querySelector("span").textContent = status === "ativo" ? "Voltar para rascunho" : "Ativar";
  }

  /* ---------- acesso aos dados do Drawflow ---------- */
  function dadosTodos() { return editor.drawflow.drawflow.Home.data; }
  function dfIdDe(cid) {
    var dados = dadosTodos();
    return Object.keys(dados).filter(function (id) { return dados[id].data.cid === cid; })[0] || null;
  }
  function dadosDo(dfId) { return dadosTodos()[dfId].data; }
  function grafoAtual() { return C.extrair(editor.export()); }
  function todosOsNos() { var g = grafoAtual(); return g.nos.concat(g.notas); }
  function caixaDe(dfId) { return areaCanvas.querySelector("#node-" + dfId); }

  /* ---------- nós ---------- */
  function esqueleto(tipo) {
    var info = C.tipoDe(tipo);
    var no = criar("div", "no");
    var ic = criar("div", "no__icone no__icone--" + info.grupo);
    ic.appendChild(icone(info.icone));
    var textos = criar("div", "no__textos");
    textos.appendChild(criar("div", "no__titulo"));
    textos.appendChild(criar("div", "no__resumo"));
    var marcas = criar("div", "no__marcas");
    var fixo = criar("span", "no__fixo"); fixo.hidden = true; fixo.title = "Dados fixos"; fixo.appendChild(icone("pin", 16));
    var itens = criar("span", "no__itens"); itens.hidden = true;
    var erro = criar("span", "no__erro", "!");
    erro.hidden = true; erro.setAttribute("title", "Este nó tem pendências");
    marcas.appendChild(fixo); marcas.appendChild(itens); marcas.appendChild(erro);
    no.appendChild(ic); no.appendChild(textos); no.appendChild(marcas);
    return no.outerHTML;
  }
  function esqueletoNota() {
    var nota = criar("div", "nota");
    nota.appendChild(criar("div", "nota__texto"));
    var alca = criar("span", "nota__alca"); alca.setAttribute("aria-hidden", "true");
    nota.appendChild(alca);
    return nota.outerHTML;
  }

  function pintarNota(dfId) {
    var caixa = caixaDe(dfId); if (!caixa) return;
    var d = dadosDo(dfId), nota = caixa.querySelector(".nota");
    nota.className = "nota nota--" + d.cor;
    nota.querySelector(".nota__texto").textContent = d.texto;
    var t = C.tamanhoNota(d.tamanho);
    nota.style.width = t.l + "px"; nota.style.height = t.a + "px";
  }

  function pintarNo(dfId) {
    var d = dadosDo(dfId);
    if (d.tipo === "nota") return pintarNota(dfId);
    var caixa = caixaDe(dfId);
    if (!caixa) return;
    caixa.querySelector(".no__titulo").textContent = d.titulo;
    caixa.querySelector(".no__resumo").textContent = C.resumo({ tipo: d.tipo, config: d.config });
    var pend = pendencias.filter(function (p) { return p.no === d.cid; });
    caixa.querySelector(".no__erro").hidden = pend.length === 0;
    caixa.classList.toggle("no--erro", pend.length > 0);
    caixa.classList.toggle("no--desativado", !!d.desativado);
    var fixo = caixa.querySelector(".no__fixo"); fixo.hidden = !(d.fixos && d.fixos.length);
    var r = resultados[d.cid], itens = caixa.querySelector(".no__itens");
    itens.hidden = !r;
    caixa.classList.toggle("no--teste-ok", !!r && !r.erro);
    caixa.classList.toggle("no--teste-erro", !!r && !!r.erro);
    if (r) {
      var n = r.itens_saida == null ? 0 : r.itens_saida;
      itens.textContent = r.erro ? "erro" : n + (n === 1 ? " item" : " itens");
    }
  }

  /* Portas: quantidade e rótulos seguem o tipo/config (EDV-01). */
  function rotularPortas(dfId, p) {
    var caixa = caixaDe(dfId); if (!caixa) return;
    [].forEach.call(caixa.querySelectorAll(".outputs .output"), function (e, i) {
      var r = p.saidas[i] || "";
      e.setAttribute("data-rotulo", r); e.setAttribute("title", r || "Saída"); e.setAttribute("data-indice", String(i));
    });
    [].forEach.call(caixa.querySelectorAll(".inputs .input"), function (e, i) {
      var r = p.entradas.length > 1 ? (p.entradas[i] || "") : "";
      e.setAttribute("data-rotulo", r); e.setAttribute("title", r || "Entrada"); e.setAttribute("data-indice", String(i));
    });
    var n = Math.max(p.saidas.length, p.entradas.length, 1);
    caixa.style.setProperty("--portas", String(n));
    caixa.classList.toggle("no--multi-portas", n > 1);
  }
  function sincronizarPortas(dfId) {
    var d = dadosDo(dfId);
    if (d.tipo === "nota") return;
    var p = C.portas(d.tipo, d.config, d.em_erro);
    var no = editor.getNodeFromId(dfId);
    var nOut = Object.keys(no.outputs).length, nIn = Object.keys(no.inputs).length;
    while (nOut < p.saidas.length) { editor.addNodeOutput(dfId); nOut += 1; }
    while (nOut > p.saidas.length) { editor.removeNodeOutput(dfId, "output_" + nOut); nOut -= 1; }
    while (nIn < p.entradas.length) { editor.addNodeInput(dfId); nIn += 1; }
    while (nIn > p.entradas.length) { editor.removeNodeInput(dfId, "input_" + nIn); nIn -= 1; }
    rotularPortas(dfId, p);
    editor.updateConnectionNodes("node-" + dfId);
  }

  function adicionarNo(no) {
    var e = C.especificacao(no);
    var dfId = editor.addNode(e.nome, e.entradas, e.saidas, e.x, e.y, "no-" + e.nome, e.data, esqueleto(no.tipo), false);
    rotularPortas(dfId, { entradas: e.rotulosEntrada, saidas: e.rotulosSaida });
    pintarNo(dfId);
    return dfId;
  }
  function adicionarNota(nota) {
    var e = C.especificacaoNota(nota);
    var dfId = editor.addNode("nota", 0, 0, e.x, e.y, "no-nota", e.data, esqueletoNota(), false);
    pintarNota(dfId);
    prepararAlcaNota(dfId);
    return dfId;
  }

  /* Redimensionar nota: alça própria (o Drawflow usaria o gesto como arrasto do nó). */
  function prepararAlcaNota(dfId) {
    var caixa = caixaDe(dfId), alca = caixa.querySelector(".nota__alca");
    function parar(ev) { ev.stopPropagation(); }
    ["mousedown", "touchstart"].forEach(function (nome) { alca.addEventListener(nome, parar); });
    alca.addEventListener("pointerdown", function (ev) {
      ev.stopPropagation(); ev.preventDefault();
      var d0 = C.tamanhoNota(dadosDo(dfId).tamanho), x0 = ev.clientX, y0 = ev.clientY;
      alca.setPointerCapture(ev.pointerId);
      function mover(e2) {
        var l = d0.l + (e2.clientX - x0) / editor.zoom, a = d0.a + (e2.clientY - y0) / editor.zoom;
        var d = C.clonar(dadosDo(dfId)); d.tamanho = C.tamanhoNota({ l: l, a: a });
        editor.updateNodeDataFromId(dfId, d); pintarNota(dfId);
      }
      function soltar() {
        alca.removeEventListener("pointermove", mover); alca.removeEventListener("pointerup", soltar);
        alca.removeEventListener("pointercancel", soltar); marcarSujo();
      }
      alca.addEventListener("pointermove", mover); alca.addEventListener("pointerup", soltar); alca.addEventListener("pointercancel", soltar);
    });
  }

  /* Nós novos seguem a linha do último nó (mesmo y, à direita); sem nós, vai ao centro visível. */
  function posicaoLivre() {
    var nos = grafoAtual().nos;
    var x, y;
    if (nos.length) {
      var ultimo = nos.reduce(function (a, b) { return b.posicao.x > a.posicao.x ? b : a; });
      x = ultimo.posicao.x + 260; y = ultimo.posicao.y;
    } else {
      var r = areaCanvas.getBoundingClientRect();
      x = Math.round((r.width / 2 - editor.canvas_x) / editor.zoom - 110);
      y = Math.round((r.height / 2 - editor.canvas_y) / editor.zoom - 30);
    }
    function ocupado() {
      return nos.some(function (n) { return Math.abs(n.posicao.x - x) < 240 && Math.abs(n.posicao.y - y) < 90; });
    }
    for (var i = 0; i < 40 && ocupado(); i += 1) {
      x += 260;
      if (i % 4 === 3) { x -= 1040; y += 110; }
    }
    return { x: x, y: y };
  }
  /* Ao soltar perto da linha de outro nó (até 40px), alinha o y com ele. */
  function alinharY(y) {
    var alvo = grafoAtual().nos.reduce(function (melhor, n) {
      return Math.abs(n.posicao.y - y) < Math.abs(melhor - y) ? n.posicao.y : melhor;
    }, Infinity);
    return Math.abs(alvo - y) <= 40 ? alvo : y;
  }
  function novoNo(tipo, posicao) {
    var g = grafoAtual();
    if (tipo === "nota") {
      var idn = C.novoId(g.nos.map(function (n) { return n.id; }).concat(g.notas.map(function (n) { return n.id; })));
      var dfn = adicionarNota({ id: idn, texto: "Escreva uma nota…", cor: "amarela", posicao: posicao, tamanho: { l: 240, a: 140 } });
      dicaVazio.hidden = true; marcarSujo(); selecionarNo(dfn);
      return dfn;
    }
    if (tipo === "gatilho" && g.nos.some(function (n) { return n.tipo === "gatilho"; })) {
      avisar("warning", "O fluxo já tem um gatilho. Use um só.");
      return null;
    }
    var ids = g.nos.map(function (n) { return n.id; }).concat(g.notas.map(function (n) { return n.id; }));
    var dfId = adicionarNo({
      id: C.novoId(ids), tipo: tipo, titulo: C.tituloUnico(TIPOS[tipo].titulo, g.nos.map(function (n) { return n.titulo; })),
      posicao: posicao, config: C.configPadrao(tipo)
    });
    sincronizarPortas(dfId);
    dicaVazio.hidden = true;
    marcarSujo();
    selecionarNo(dfId);
    return dfId;
  }

  /* ---------- carregar grafo ---------- */
  function carregar(grafo) {
    carregando = true;
    editor.clear();
    selecionado = null; multi = {}; montarInspector(null);
    var g = C.migrar(grafo);
    var mapa = {};
    g.notas.forEach(function (n) { adicionarNota(n); });
    g.nos.forEach(function (no) { mapa[no.id] = adicionarNo(no); });
    g.arestas.forEach(function (a) {
      var de = mapa[a.de], para = mapa[a.para];
      if (!de || !para) return;
      var o = "output_" + (a.saida + 1), i = "input_" + (a.entrada + 1);
      var nd = editor.getNodeFromId(de), np = editor.getNodeFromId(para);
      if (nd.outputs[o] && np.inputs[i]) editor.addConnection(de, para, o, i);
    });
    carregando = false;
    dicaVazio.hidden = g.nos.length > 0 || g.notas.length > 0;
    desenharContagens();
  }

  /* ---------- zoom / ajustar ---------- */
  function ajustar() {
    var dados = dadosTodos(), ids = Object.keys(dados);
    if (!ids.length) { editor.zoom = 1; editor.zoom_last_value = 1; editor.canvas_x = 0; editor.canvas_y = 0; editor.zoom_refresh(); return; }
    var minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    ids.forEach(function (id) {
      var caixa = caixaDe(id);
      var w = caixa ? caixa.offsetWidth : 220, h = caixa ? caixa.offsetHeight : 64;
      minx = Math.min(minx, dados[id].pos_x); miny = Math.min(miny, dados[id].pos_y);
      maxx = Math.max(maxx, dados[id].pos_x + w); maxy = Math.max(maxy, dados[id].pos_y + h);
    });
    minx -= 40; maxx += 100; // folga para os rótulos das alças (verdadeiro, regra N...)
    var r = areaCanvas.getBoundingClientRect(), margem = 48, topo = 72;
    var z = Math.min(1, (r.width - margem) / (maxx - minx), (r.height - margem - topo) / (maxy - miny));
    z = Math.max(window.innerWidth <= 800 ? 0.65 : editor.zoom_min, z);
    editor.zoom = z;
    editor.zoom_last_value = z; // zoom_refresh() reescala canvas_x/y por zoom/zoom_last_value
    editor.canvas_x = (r.width - (maxx - minx) * z) / 2 - minx * z;
    if ((maxx - minx) * z > r.width - margem) editor.canvas_x = margem / 2 - minx * z; // não cabe: alinha ao primeiro nó
    editor.canvas_y = topo + (r.height - topo - margem / 2 - (maxy - miny) * z) / 2 - miny * z;
    editor.zoom_refresh();
  }

  /* ---------- contagem de itens nas arestas (MV2-07, EDV-03) ---------- */
  function desenharContagens() {
    areaCanvas.querySelectorAll(".aresta-rotulo").forEach(function (e) { e.remove(); });
    if (!contagemArestas.length) return;
    contagemArestas.forEach(function (a) {
      var de = dfIdDe(a.de), para = dfIdDe(a.para);
      if (!de || !para) return;
      var svg = areaCanvas.querySelector("svg.connection.node_out_node-" + de + ".node_in_node-" + para + ".output_" + (a.saida + 1) + ".input_" + (a.entrada + 1));
      var caminho = svg && svg.querySelector(".main-path");
      if (!caminho || !caminho.getTotalLength) return;
      var ponto = caminho.getPointAtLength(caminho.getTotalLength() / 2);
      var ns = "http://www.w3.org/2000/svg";
      var g = document.createElementNS(ns, "g"); g.setAttribute("class", "aresta-rotulo");
      var texto = document.createElementNS(ns, "text");
      texto.textContent = String(a.itens) + (a.itens === 1 ? " item" : " itens");
      texto.setAttribute("x", ponto.x); texto.setAttribute("y", ponto.y); texto.setAttribute("text-anchor", "middle"); texto.setAttribute("dominant-baseline", "central");
      g.appendChild(texto); svg.appendChild(g);
    });
  }

  /* ---------- pendências (GRF-05) ---------- */
  function aplicarPendencias(lista) {
    pendencias = lista || [];
    Object.keys(dadosTodos()).forEach(pintarNo);
    var total = pendencias.length;
    chipPend.hidden = total === 0;
    chipPend.querySelector("span").textContent = total + (total === 1 ? " pendência" : " pendências");
    popPend.replaceChildren();
    pendencias.forEach(function (p) {
      var b = criar("button", "pendencia", p.mensagem);
      b.type = "button";
      if (p.no) b.addEventListener("click", function () { var id = dfIdDe(p.no); if (id) selecionarNo(id); popPend.hidden = true; });
      popPend.appendChild(b);
    });
    if (!total) popPend.hidden = true;
    if (selecionado) montarInspector(selecionado);
  }

  /* ---------- inspector ---------- */
  function abrirPainel(nome, aberto) { raiz.classList.toggle("editor--" + nome, aberto); }

  function atualizarDados(dfId, mudar) {
    var antes = C.clonar(dadosDo(dfId));
    var d = C.clonar(antes);
    mudar(d);
    editor.updateNodeDataFromId(dfId, d);
    if (d.tipo === "nota") pintarNota(dfId);
    else {
      var pa = JSON.stringify(C.portas(antes.tipo, antes.config, antes.em_erro)), pd = JSON.stringify(C.portas(d.tipo, d.config, d.em_erro));
      if (pa !== pd) sincronizarPortas(dfId);
      pintarNo(dfId);
    }
    marcarSujo();
  }

  function previaDeExpressao(expr, campo) {
    var d = selecionado ? dadosDo(selecionado) : null;
    if (!urlPrevia || !d) return Promise.resolve({ ok: false, sem_dados: true });
    return fetch(urlPrevia, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ no_id: d.cid, campo: campo || "", expressao: expr })
    }).then(function (r) {
      if (r.status === 429) return { ok: false, erro: "Muitas prévias em pouco tempo. Aguarde um instante." };
      return r.json().catch(function () { return {}; });
    }).then(function (c) {
      if (c && c.ok) return { ok: true, valor: c.valor, texto: c.texto };
      if (c && c.erro && c.erro.indexOf("Execute o fluxo em teste") === 0) return { ok: false, sem_dados: true };
      return { ok: false, erro: (c && c.erro) || "Expressão inválida." };
    });
  }

  function montarInspector(dfId) {
    inspector.replaceChildren();
    if (!dfId) {
      var vz = criar("div", "inspector__vazio");
      vz.appendChild(criar("p", "", "Selecione um nó para editar a configuração."));
      inspector.appendChild(vz);
      return;
    }
    var d = dadosDo(dfId);
    var pend = pendencias.filter(function (p) { return p.no === d.cid; });
    var ctxBase = {
      sprite: sprite, atual: function () { return C.clonar(dadosDo(dfId)); }, pendencias: pend,
      aoMudar: function (fn) { atualizarDados(dfId, fn); },
      acoes: { remover: removerSelecionado, duplicar: function () { duplicar([dfId]); } }
    };
    if (d.tipo === "nota") { window.InspectorNos.montarNota(inspector, Object.assign(ctxBase, { dados: C.clonar(d) })); return; }
    var grafo = grafoAtual();
    ctxBase.acoes.executarNo = urlExecutarNo ? function () { executarNo(dfId); } : null;
    ctxBase.acoes.fixar = function (saida) { atualizarDados(dfId, function (x) { x.fixos = C.clonar(saida); }); montarInspector(dfId); };
    ctxBase.acoes.limpar = function () { atualizarDados(dfId, function (x) { x.fixos = null; }); montarInspector(dfId); };
    window.InspectorNos.montar(inspector, Object.assign(ctxBase, {
      dados: C.clonar(d), credenciais: credenciais, podeCodigo: podeCodigo, urlCredenciais: urlCredenciais,
      anteriores: C.anteriores(grafo, d.cid), previa: previaDeExpressao, resultado: resultados[d.cid] || null,
      aoMudarPortas: function () { /* portas já sincronizadas por atualizarDados */ }
    }));
  }

  function selecionarNo(dfId) {
    selecionado = dfId;
    montarInspector(dfId);
    abrirPainel("inspector", !!dfId);
    abrirPainel("paleta", false);
  }
  function removerSelecionado() {
    var alvos = Object.keys(multi);
    if (!alvos.length && selecionado) alvos = [selecionado];
    alvos.forEach(function (id) { if (dadosTodos()[id]) editor.removeNodeId("node-" + id); });
    multi = {};
  }

  /* ---------- duplicar / copiar / colar (EDV-03) ---------- */
  function trecho(dfIds) {
    var g = grafoAtual(), cids = {};
    dfIds.forEach(function (id) { if (dadosTodos()[id]) cids[dadosDo(id).cid] = true; });
    return {
      formato: "construtor-workflows-trecho", versao: 2,
      nos: g.nos.filter(function (n) { return cids[n.id]; }).map(function (n) { var x = C.clonar(n); x.fixos = (g.dados_fixos || {})[n.id]; return x; }),
      arestas: g.arestas.filter(function (a) { return cids[a.de] && cids[a.para]; }),
      notas: g.notas.filter(function (n) { return cids[n.id]; })
    };
  }
  function inserirTrecho(t, deslocar) {
    if (!t || t.formato !== "construtor-workflows-trecho" || t.versao !== 2) return false;
    var g = grafoAtual();
    var ids = g.nos.map(function (n) { return n.id; }).concat(g.notas.map(function (n) { return n.id; }));
    var titulos = g.nos.map(function (n) { return n.titulo; });
    var mapa = {}, criados = [], tem = false;
    (t.nos || []).slice(0, 50).forEach(function (n) {
      if (!TIPOS[n.tipo] || (n.tipo === "gatilho" && g.nos.some(function (x) { return x.tipo === "gatilho"; }))) return;
      var novo = C.novoId(ids); ids.push(novo); mapa[n.id] = novo;
      var titulo = C.tituloUnico(String(n.titulo || TIPOS[n.tipo].titulo).slice(0, 80), titulos); titulos.push(titulo);
      var dfId = adicionarNo({
        id: novo, tipo: n.tipo, titulo: titulo, posicao: { x: Math.round((n.posicao || {}).x || 0) + deslocar, y: Math.round((n.posicao || {}).y || 0) + deslocar },
        config: Object.assign(C.configPadrao(n.tipo), C.clonar(n.config || {})), desativado: n.desativado, executar_uma_vez: n.executar_uma_vez, em_erro: n.em_erro, fixos: n.fixos
      });
      sincronizarPortas(dfId); criados.push(dfId); tem = true;
    });
    (t.notas || []).slice(0, 20).forEach(function (n) {
      var novo = C.novoId(ids); ids.push(novo);
      criados.push(adicionarNota({ id: novo, texto: String(n.texto || "").slice(0, 5000), cor: n.cor, tamanho: n.tamanho, posicao: { x: ((n.posicao || {}).x || 0) + deslocar, y: ((n.posicao || {}).y || 0) + deslocar } }));
      tem = true;
    });
    (t.arestas || []).forEach(function (a) {
      var de = mapa[a.de] && dfIdDe(mapa[a.de]), para = mapa[a.para] && dfIdDe(mapa[a.para]);
      if (!de || !para) return;
      var o = "output_" + (a.saida + 1), i = "input_" + (a.entrada + 1);
      if (editor.getNodeFromId(de).outputs[o] && editor.getNodeFromId(para).inputs[i]) editor.addConnection(de, para, o, i);
    });
    if (tem) { marcarSujo(); dicaVazio.hidden = true; if (criados.length === 1) selecionarNo(criados[0]); }
    return tem;
  }
  function selecaoAtual() {
    var ids = Object.keys(multi);
    return ids.length ? ids : (selecionado ? [selecionado] : []);
  }
  function duplicar(dfIds) {
    var ids = (dfIds || selecaoAtual()).filter(function (id) { return dadosTodos()[id] && dadosDo(id).tipo !== "gatilho"; });
    if (!ids.length) { avisar("warning", "O gatilho não pode ser duplicado."); return; }
    inserirTrecho(trecho(ids), 40);
  }

  document.addEventListener("copy", function (ev) {
    if (emCampo() || !selecaoAtual().length) return;
    ev.clipboardData.setData("text/plain", JSON.stringify(trecho(selecaoAtual())));
    ev.preventDefault();
    avisar("success", "Copiado. Cole em qualquer fluxo com Ctrl+V.");
  });
  document.addEventListener("paste", function (ev) {
    if (emCampo()) return;
    var texto = (ev.clipboardData && ev.clipboardData.getData("text/plain")) || "";
    var t; try { t = JSON.parse(texto); } catch (_) { return; }
    if (inserirTrecho(t, 40)) ev.preventDefault();
    else if (t && t.formato === "construtor-workflows-trecho") avisar("error", "Não foi possível colar este trecho.");
  });
  function emCampo() {
    var tag = (document.activeElement && document.activeElement.tagName) || "";
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
  }

  /* ---------- eventos do Drawflow ---------- */
  editor.on("nodeSelected", function (id) {
    selecionarNo(String(id));
  });
  editor.on("nodeUnselected", function () { selecionado = null; montarInspector(null); abrirPainel("inspector", false); });
  editor.on("nodeRemoved", function () {
    selecionado = null; montarInspector(null); abrirPainel("inspector", false); marcarSujo();
    dicaVazio.hidden = todosOsNos().length > 0;
  });
  editor.on("nodeMoved", function () { marcarSujo(); desenharContagens(); });
  editor.on("connectionCreated", function () { marcarSujo(); desenharContagens(); });
  editor.on("connectionRemoved", marcarSujo);

  /* Shift+clique: seleção múltipla (para copiar, duplicar e remover juntos). */
  areaCanvas.addEventListener("mousedown", function (ev) {
    var caixa = ev.target.closest && ev.target.closest(".drawflow-node");
    if (!ev.shiftKey || !caixa) { if (!ev.shiftKey && !caixa) limparMulti(); return; }
    var id = caixa.id.replace("node-", "");
    if (multi[id]) { delete multi[id]; caixa.classList.remove("multi"); } else { multi[id] = true; caixa.classList.add("multi"); }
  }, true);
  function limparMulti() {
    Object.keys(multi).forEach(function (id) { var c = caixaDe(id); if (c) c.classList.remove("multi"); });
    multi = {};
  }

  /* ---------- paleta agrupada com busca (EDV-01) ---------- */
  function montarPaleta() {
    listaPaleta.replaceChildren();
    var grupos = C.GRUPOS.concat([{ id: "canvas", rotulo: "Canvas" }]);
    grupos.forEach(function (gr) {
      var itens = gr.id === "canvas" ? ["nota"] : C.ORDEM_TIPOS.filter(function (t) { return TIPOS[t].grupo === gr.id; });
      if (!itens.length) return;
      var secao = criar("section", "paleta__grupo"); secao.dataset.grupo = gr.id;
      secao.appendChild(criar("h3", "paleta__grupo-titulo", gr.rotulo));
      itens.forEach(function (t) {
        var info = t === "nota" ? { rotulo: "Nota", icone: "sticky-note", grupo: "canvas", busca: "nota sticky comentario anotacao" } : TIPOS[t];
        var b = criar("button", "paleta__item"); b.type = "button"; b.draggable = true; b.dataset.paletaTipo = t;
        b.dataset.busca = (info.rotulo + " " + (info.busca || "")).toLowerCase();
        var ic = criar("span", "no__icone no__icone--" + info.grupo); ic.appendChild(icone(info.icone));
        b.appendChild(ic); b.appendChild(criar("span", "paleta__rotulo", info.rotulo));
        b.addEventListener("click", function () { novoNo(t, posicaoLivre()); abrirPainel("paleta", false); });
        b.addEventListener("dragstart", function (ev) { ev.dataTransfer.setData("text/plain", t); });
        secao.appendChild(b);
      });
      listaPaleta.appendChild(secao);
    });
  }
  function filtrarPaleta() {
    var q = buscaPaleta.value.trim().toLowerCase(), total = 0;
    listaPaleta.querySelectorAll(".paleta__grupo").forEach(function (secao) {
      var visiveis = 0;
      secao.querySelectorAll(".paleta__item").forEach(function (b) {
        var ok = !q || b.dataset.busca.indexOf(q) >= 0; b.hidden = !ok; if (ok) visiveis += 1;
      });
      secao.hidden = visiveis === 0; total += visiveis;
    });
    vazioPaleta.hidden = total > 0;
  }
  buscaPaleta.addEventListener("input", filtrarPaleta);
  buscaPaleta.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") {
      var primeiro = listaPaleta.querySelector(".paleta__item:not([hidden])");
      if (primeiro) { ev.preventDefault(); primeiro.click(); }
    }
  });
  areaCanvas.addEventListener("dragover", function (ev) { ev.preventDefault(); });
  areaCanvas.addEventListener("drop", function (ev) {
    ev.preventDefault();
    var tipo = ev.dataTransfer.getData("text/plain");
    if (!TIPOS[tipo] && tipo !== "nota") return;
    var r = areaCanvas.getBoundingClientRect();
    novoNo(tipo, {
      x: Math.round((ev.clientX - r.left - editor.canvas_x) / editor.zoom - 110),
      y: alinharY(Math.round((ev.clientY - r.top - editor.canvas_y) / editor.zoom - 30))
    });
  });

  /* ---------- toolbar ---------- */
  raiz.addEventListener("click", function (ev) {
    var alvo = ev.target.closest("[data-acao]");
    if (!alvo) return;
    var acao = alvo.dataset.acao;
    if (acao === "salvar") salvar();
    else if (acao === "zoom-mais") editor.zoom_in();
    else if (acao === "zoom-menos") editor.zoom_out();
    else if (acao === "ajustar") ajustar();
    else if (acao === "paleta") { abrirPainel("paleta", !raiz.classList.contains("editor--paleta")); abrirPainel("inspector", false); }
    else if (acao === "fechar-painel") { abrirPainel("paleta", false); abrirPainel("inspector", false); }
    else if (acao === "pendencias") popPend.hidden = !popPend.hidden;
    else if (acao === "status") alternarStatus();
    else if (acao === "recarregar") { sujo = false; window.location.reload(); }
  });

  document.addEventListener("keydown", function (ev) {
    var tecla = (ev.key || "").toLowerCase();
    if ((ev.ctrlKey || ev.metaKey) && tecla === "s") { ev.preventDefault(); salvar(); return; }
    if (emCampo()) return;
    if ((ev.ctrlKey || ev.metaKey) && tecla === "d") { ev.preventDefault(); duplicar(); return; }
    if (ev.key === "Delete" || ev.key === "Backspace") {
      if (editor.connection_selected) editor.removeConnection();
      else removerSelecionado();
    }
  });

  /* ---------- salvar / status ---------- */
  function mensagensDe(corpo) {
    return ((corpo && corpo.erros) || []).map(function (e) { return e.mensagem; }).filter(Boolean);
  }
  function salvar() {
    if (btnSalvar.getAttribute("aria-busy") === "true") return Promise.resolve(false);
    btnSalvar.setAttribute("aria-busy", "true");
    return fetch(urlSalvar, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ grafo: grafoAtual(), atualizado_em: atualizadoEm })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (corpo) { return { r: r, corpo: corpo }; });
    }).then(function (x) {
      btnSalvar.removeAttribute("aria-busy");
      if (x.r.status === 409) {
        banner.querySelector("span").textContent = mensagensDe(x.corpo)[0] || "Este fluxo foi alterado por outra pessoa. Recarregue para continuar.";
        banner.hidden = false;
        return false;
      }
      if (!x.r.ok || x.corpo.ok === false) {
        var msgs = mensagensDe(x.corpo);
        avisar("error", msgs.length ? msgs.join(" ") : "Não foi possível salvar. Tente novamente.");
        return false;
      }
      atualizadoEm = x.corpo.atualizado_em || atualizadoEm;
      if (x.corpo.status && x.corpo.status !== status) { status = x.corpo.status; atualizarStatus(); }
      marcarLimpo();
      aplicarPendencias(x.corpo.pendencias);
      var n = (x.corpo.pendencias || []).length;
      avisar(n || x.corpo.voltou_para_rascunho ? "warning" : "success", x.corpo.voltou_para_rascunho ? "Fluxo salvo com pendências e voltou para rascunho." : n ? "Fluxo salvo com " + n + (n === 1 ? " pendência." : " pendências.") : "Fluxo salvo.");
      return true;
    }).catch(function () {
      btnSalvar.removeAttribute("aria-busy");
      avisar("error", "Sem conexão com o servidor. Tente novamente.");
      return false;
    });
  }
  function alternarStatus() {
    var novo = status === "ativo" ? "rascunho" : "ativo";
    var pronto = sujo ? salvar() : Promise.resolve(true);
    pronto.then(function (ok) {
      if (!ok) return;
      var dados = new URLSearchParams(); dados.set("status", novo);
      return fetch(urlStatus, {
        method: "POST", credentials: "same-origin",
        headers: { "Accept": "application/json", "X-CSRFToken": csrf, "Content-Type": "application/x-www-form-urlencoded" },
        body: dados.toString()
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (corpo) {
          if (!r.ok || corpo.ok === false) {
            aplicarPendencias(corpo.pendencias || []);
            avisar("error", novo === "ativo" ? "Corrija as pendências para ativar o fluxo." : "Não foi possível alterar o status.");
            return;
          }
          status = novo; atualizarStatus();
          if (corpo.atualizado_em) atualizadoEm = corpo.atualizado_em;
          avisar("success", novo === "ativo" ? "Fluxo ativado." : "Fluxo voltou para rascunho.");
        });
      });
    });
  }

  /* ---------- executar este nó (MV2-06) ---------- */
  function aplicarResultado(corpo) {
    resultados = {};
    var nos = corpo.nos || {};
    Object.keys(nos).forEach(function (cid) { resultados[cid] = nos[cid]; });
    contagemArestas = corpo.arestas || [];
    Object.keys(dadosTodos()).forEach(pintarNo);
    desenharContagens();
    if (selecionado) montarInspector(selecionado);
  }
  /* MV2-14: o POST devolve {ok, execucao, url_detalhe}; os dados por nó vêm do detalhe (json_script "resultado-teste"). */
  function buscarResultado(urlDetalhe) {
    return fetch(urlDetalhe, { credentials: "same-origin", headers: { "Accept": "text/html" } }).then(function (r) {
      if (!r.ok) return null;
      return r.text().then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var e = doc.getElementById("nos-execucao"), g = doc.getElementById("grafo-execucao");
        if (!e) return null;
        try {
          var lista = JSON.parse(e.textContent), nos = {}, arestas = [];
          lista.forEach(function (n) {
            nos[n.no_id] = { status: n.status, itens_entrada: n.itens_entrada, itens_saida: n.itens_saida, saida: n.saida || [], erro: n.erro, logs: n.logs || [] };
          });
          if (g) arestas = JSON.parse(g.textContent).arestas || [];
          return { nos: nos, arestas: arestas };
        } catch (_) { return null; }
      });
    }).catch(function () { return null; });
  }
  function executarNo(dfId) {
    var d = dadosDo(dfId);
    var botao = inspector.querySelector("[data-acao-no=executar-no]");
    function fim() { if (botao) botao.removeAttribute("aria-busy"); }
    if (botao) botao.setAttribute("aria-busy", "true");
    var pronto = sujo ? salvar() : Promise.resolve(true);
    pronto.then(function (ok) {
      if (!ok) { fim(); return; }
      var dados = new URLSearchParams(); dados.set("no_id", d.cid);
      return fetch(urlExecutarNo, {
        method: "POST", credentials: "same-origin",
        headers: { "Accept": "application/json", "X-CSRFToken": csrf, "Content-Type": "application/x-www-form-urlencoded" },
        body: dados.toString()
      }).then(function (r) {
        return r.json().catch(function () { return null; }).then(function (corpo) {
          if (!corpo || !r.ok || corpo.ok === false) {
            fim();
            if (corpo && corpo.pendencias && corpo.pendencias.length) { aplicarPendencias(corpo.pendencias); avisar("error", "Corrija as pendências do fluxo antes de executar este nó."); return; }
            avisar("error", (corpo && mensagensDe(corpo)[0]) || "Não foi possível executar este nó."); return;
          }
          if (corpo.nos) { fim(); aplicarResultado(corpo); return; }
          return buscarResultado(corpo.url_detalhe).then(function (res) {
            fim();
            if (!res) { avisar("success", "Teste concluído. Abra o detalhe da execução para ver os dados."); return; }
            aplicarResultado(res);
            var r0 = resultados[d.cid];
            avisar(r0 && r0.erro ? "error" : "success", r0 && r0.erro ? "O nó falhou no teste. Veja os detalhes no painel." : "Teste concluído. Veja os dados no painel.");
          });
        });
      });
    }).catch(function () { fim(); avisar("error", "Sem conexão com o servidor. Tente novamente."); });
  }

  /* Executar (EXE-13): salva antes se houver alterações; só então envia o POST. */
  var formExecutar = raiz.querySelector("[data-executar]");
  if (formExecutar) {
    formExecutar.addEventListener("submit", function (ev) {
      if (!sujo) return;
      ev.preventDefault();
      var botao = formExecutar.querySelector("button");
      botao.setAttribute("aria-busy", "true");
      salvar().then(function (ok) {
        botao.removeAttribute("aria-busy");
        if (ok) { sujo = false; formExecutar.submit(); }
      });
    }, true);
  }

  /* Painel do relatório de importação: dispensar só esconde (o servidor guarda). */
  var painelRel = raiz.querySelector("[data-relatorio-importacao]");
  if (painelRel) painelRel.addEventListener("click", function (ev) {
    if (ev.target.closest("[data-dispensar-relatorio]")) painelRel.hidden = true;
  });

  /* ---------- início ---------- */
  montarPaleta();
  var inicial = JSON.parse(document.getElementById("grafo-inicial").textContent);
  carregar(inicial);
  aplicarPendencias(lerJson("pendencias-iniciais", []));
  atualizarStatus();
  montarInspector(null);
  setTimeout(ajustar, 0);
  window.editorFlux = {
    editor: editor,
    extrair: grafoAtual,
    carregar: carregar,
    aplicarResultado: aplicarResultado
  };
})();
