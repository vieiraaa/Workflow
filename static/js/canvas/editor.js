/* Editor de canvas (TEL-05). JS fino: converte Drawflow <-> grafo canônico e cuida da UX.
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
  var atualizadoEm = raiz.dataset.atualizadoEm;
  var status = raiz.dataset.status || "rascunho";
  var csrf = (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value || "";

  var el = function (id) { return raiz.querySelector("[data-" + id + "]"); };
  var areaCanvas = el("canvas"), inspector = el("inspector-corpo"), banner = el("banner");
  var btnSalvar = el("salvar"), chipStatus = el("status"), btnStatus = el("alternar-status");
  var chipPend = el("pendencias"), popPend = el("pendencias-lista"), dicaVazio = el("dica-vazio");

  var editor = new Drawflow(areaCanvas);
  editor.reroute = false;
  editor.zoom_max = 1.6; editor.zoom_min = 0.4;
  editor.key = function () {}; // Delete/Ctrl+S são tratados abaixo, com checagem de foco.
  editor.start();

  var carregando = true, sujo = false, selecionado = null, pendencias = [];

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
    dicaVazio.hidden = nosDoGrafo().length > 0;
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

  /* ---------- nós ---------- */
  function dfIdDe(cid) {
    var dados = editor.drawflow.drawflow.Home.data;
    return Object.keys(dados).filter(function (id) { return dados[id].data.cid === cid; })[0] || null;
  }
  function dadosDo(dfId) { return editor.drawflow.drawflow.Home.data[dfId].data; }
  function nosDoGrafo() { return C.extrair(editor.export()).nos; }

  function esqueleto(tipo) {
    var no = criar("div", "no");
    var ic = criar("div", "no__icone no__icone--" + tipo);
    ic.appendChild(icone(TIPOS[tipo].icone));
    var textos = criar("div", "no__textos");
    textos.appendChild(criar("div", "no__titulo"));
    textos.appendChild(criar("div", "no__resumo"));
    var erro = criar("span", "no__erro", "!");
    erro.hidden = true; erro.setAttribute("title", "Este nó tem pendências");
    no.appendChild(ic); no.appendChild(textos); no.appendChild(erro);
    return no.outerHTML;
  }
  function pintarNo(dfId) {
    var caixa = areaCanvas.querySelector("#node-" + dfId);
    if (!caixa) return;
    var d = dadosDo(dfId);
    caixa.querySelector(".no__titulo").textContent = d.titulo;
    caixa.querySelector(".no__resumo").textContent = C.resumo({ tipo: d.tipo, config: d.config });
    var pend = pendencias.filter(function (p) { return p.no === d.cid; });
    caixa.querySelector(".no__erro").hidden = pend.length === 0;
    caixa.classList.toggle("no--erro", pend.length > 0);
  }
  function adicionarNo(no) {
    var e = C.especificacao(no);
    var dfId = editor.addNode(e.nome, e.entradas, e.saidas, e.x, e.y, "no-" + e.nome, e.data, esqueleto(no.tipo), false);
    pintarNo(dfId);
    return dfId;
  }
  /* Centro visível do canvas; se já houver nó ali, desloca para a direita (e depois para baixo). */
  function posicaoLivre() {
    var r = areaCanvas.getBoundingClientRect();
    var x = Math.round((r.width / 2 - editor.canvas_x) / editor.zoom - 110);
    var y = Math.round((r.height / 2 - editor.canvas_y) / editor.zoom - 30);
    var nos = nosDoGrafo();
    function ocupado() {
      return nos.some(function (n) { return Math.abs(n.posicao.x - x) < 240 && Math.abs(n.posicao.y - y) < 90; });
    }
    for (var i = 0; i < 40 && ocupado(); i += 1) {
      x += 260;
      if (i % 4 === 3) { x -= 1040; y += 110; }
    }
    return { x: x, y: y };
  }
  function novoNo(tipo, posicao) {
    var ids = nosDoGrafo().map(function (n) { return n.id; });
    var dfId = adicionarNo({
      id: C.novoId(ids), tipo: tipo, titulo: TIPOS[tipo].titulo,
      posicao: posicao, config: C.configPadrao(tipo)
    });
    dicaVazio.hidden = true;
    selecionarNo(dfId);
    return dfId;
  }

  /* ---------- carregar grafo ---------- */
  function carregar(grafo) {
    carregando = true;
    editor.clear();
    var mapa = {};
    grafo.nos.forEach(function (no) { mapa[no.id] = adicionarNo(no); });
    grafo.arestas.forEach(function (a) {
      if (mapa[a.de] && mapa[a.para]) editor.addConnection(mapa[a.de], mapa[a.para], "output_1", "input_1");
    });
    carregando = false;
    dicaVazio.hidden = grafo.nos.length > 0;
  }

  /* ---------- zoom / ajustar ---------- */
  function ajustar() {
    var dados = editor.drawflow.drawflow.Home.data, ids = Object.keys(dados);
    if (!ids.length) { editor.zoom = 1; editor.zoom_last_value = 1; editor.canvas_x = 0; editor.canvas_y = 0; editor.zoom_refresh(); return; }
    var minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    ids.forEach(function (id) {
      var caixa = areaCanvas.querySelector("#node-" + id);
      var w = caixa ? caixa.offsetWidth : 220, h = caixa ? caixa.offsetHeight : 64;
      minx = Math.min(minx, dados[id].pos_x); miny = Math.min(miny, dados[id].pos_y);
      maxx = Math.max(maxx, dados[id].pos_x + w); maxy = Math.max(maxy, dados[id].pos_y + h);
    });
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

  /* ---------- pendências (GRF-05) ---------- */
  function aplicarPendencias(lista) {
    pendencias = lista || [];
    Object.keys(editor.drawflow.drawflow.Home.data).forEach(pintarNo);
    var globais = pendencias.filter(function (p) { return !p.no; });
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
    return globais;
  }

  /* ---------- inspector ---------- */
  function abrirPainel(nome, aberto) { raiz.classList.toggle("editor--" + nome, aberto); }

  function campoTexto(rotulo, valor, opcoes, aoMudar) {
    var caixa = criar("div", "campo");
    var id = "insp-" + opcoes.campo;
    var l = criar("label", "campo__rotulo", rotulo); l.setAttribute("for", id);
    var entrada = criar(opcoes.multilinha ? "textarea" : "input");
    entrada.id = id; entrada.value = valor || "";
    if (!opcoes.multilinha) entrada.type = "text";
    if (opcoes.max) entrada.maxLength = opcoes.max;
    if (opcoes.placeholder) entrada.placeholder = opcoes.placeholder;
    entrada.addEventListener("input", function () { aoMudar(entrada.value); });
    caixa.appendChild(l); caixa.appendChild(entrada);
    anexarErros(caixa, opcoes.campo);
    return caixa;
  }
  function anexarErros(caixa, campo) {
    if (!selecionado) return;
    var cid = dadosDo(selecionado).cid;
    pendencias.filter(function (p) { return p.no === cid && p.campo === campo; }).forEach(function (p) {
      caixa.classList.add("campo--erro");
      caixa.appendChild(criar("p", "campo__erro", p.mensagem));
    });
  }
  function editorPares(rotulo, campo, lista, aoMudar) {
    var caixa = criar("div", "campo");
    caixa.appendChild(criar("span", "campo__rotulo", rotulo));
    var corpo = criar("div", "pares");
    function emitir() {
      var itens = [];
      corpo.querySelectorAll(".par").forEach(function (linha) {
        var i = linha.querySelectorAll("input");
        itens.push({ nome: i[0].value, valor: i[1].value });
      });
      aoMudar(itens);
    }
    function linha(par) {
      var l = criar("div", "par");
      var n = criar("input"), v = criar("input");
      n.type = v.type = "text"; n.placeholder = "Nome"; v.placeholder = "Valor";
      n.value = par.nome; v.value = par.valor;
      n.setAttribute("aria-label", rotulo + ": nome"); v.setAttribute("aria-label", rotulo + ": valor");
      n.addEventListener("input", emitir); v.addEventListener("input", emitir);
      var rm = criar("button", "botao botao--icone"); rm.type = "button";
      rm.setAttribute("aria-label", "Remover"); rm.appendChild(icone("x", 16));
      rm.addEventListener("click", function () { l.remove(); emitir(); });
      l.appendChild(n); l.appendChild(v); l.appendChild(rm);
      return l;
    }
    (lista || []).forEach(function (p) { corpo.appendChild(linha(p)); });
    var add = criar("button", "botao botao--secundario", "Adicionar"); add.type = "button";
    add.addEventListener("click", function () {
      if (corpo.children.length >= 30) return;
      corpo.appendChild(linha({ nome: "", valor: "" })); emitir();
    });
    caixa.appendChild(corpo); caixa.appendChild(add);
    anexarErros(caixa, campo);
    return caixa;
  }

  function atualizarDados(dfId, mudar) {
    var d = C.clonar(dadosDo(dfId));
    mudar(d);
    editor.updateNodeDataFromId(dfId, d);
    pintarNo(dfId);
    marcarSujo();
  }

  function montarInspector(dfId) {
    inspector.replaceChildren();
    if (!dfId) {
      inspector.appendChild(criar("p", "inspector__vazio", "Selecione um nó para editar a configuração."));
      return;
    }
    var d = dadosDo(dfId);
    var form = criar("div", "inspector__form");
    form.appendChild(criar("h2", "card__titulo", TIPOS[d.tipo].rotulo));
    var geral = pendencias.filter(function (p) { return p.no === d.cid && !p.campo; });
    if (geral.length) {
      var alerta = criar("div", "alerta alerta--erro"); alerta.setAttribute("role", "alert");
      alerta.appendChild(icone("circle-alert", 16));
      alerta.appendChild(criar("span", "", geral.map(function (p) { return p.mensagem; }).join(" ")));
      form.appendChild(alerta);
    }
    form.appendChild(campoTexto("Título", d.titulo, { campo: "titulo", max: 80 }, function (v) {
      atualizarDados(dfId, function (x) { x.titulo = v; });
    }));
    if (d.tipo === "http") {
      var cm = criar("div", "campo");
      var lm = criar("label", "campo__rotulo", "Método"); lm.setAttribute("for", "insp-metodo");
      var sel = criar("select"); sel.id = "insp-metodo";
      C.METODOS.forEach(function (m) { var o = criar("option", "", m); o.value = m; if (m === d.config.metodo) o.selected = true; sel.appendChild(o); });
      sel.addEventListener("change", function () { atualizarDados(dfId, function (x) { x.config.metodo = sel.value; }); montarInspector(dfId); });
      var envoltorio = criar("div", "campo__select");
      envoltorio.appendChild(sel); envoltorio.appendChild(icone("chevron-down", 16));
      cm.appendChild(lm); cm.appendChild(envoltorio); anexarErros(cm, "metodo");
      form.appendChild(cm);
      form.appendChild(campoTexto("URL", d.config.url, { campo: "url", max: 2048, placeholder: "https://api.exemplo.com/recurso" }, function (v) {
        atualizarDados(dfId, function (x) { x.config.url = v; });
      }));
      form.appendChild(editorPares("Cabeçalhos", "headers", d.config.headers, function (itens) {
        atualizarDados(dfId, function (x) { x.config.headers = itens; });
      }));
      form.appendChild(editorPares("Parâmetros de consulta", "query", d.config.query, function (itens) {
        atualizarDados(dfId, function (x) { x.config.query = itens; });
      }));
      var corpo = campoTexto("Corpo (JSON)", d.config.corpo, { campo: "corpo", multilinha: true }, function (v) {
        atualizarDados(dfId, function (x) { x.config.corpo = v; });
      });
      corpo.appendChild(criar("p", "campo__ajuda", "Só para POST, PUT e PATCH. Use {{ anterior.corpo }} para valores do nó anterior."));
      form.appendChild(corpo);
    }
    var rm = criar("button", "botao botao--destrutivo", "Remover nó"); rm.type = "button";
    rm.addEventListener("click", function () { removerSelecionado(); });
    form.appendChild(rm);
    inspector.appendChild(form);
  }

  function selecionarNo(dfId) {
    selecionado = dfId;
    montarInspector(dfId);
    abrirPainel("inspector", !!dfId);
    abrirPainel("paleta", false);
  }
  function removerSelecionado() {
    if (!selecionado) return;
    editor.removeNodeId("node-" + selecionado);
  }

  /* ---------- eventos do Drawflow ---------- */
  editor.on("nodeSelected", function (id) { selecionarNo(String(id)); });
  editor.on("nodeUnselected", function () { selecionado = null; montarInspector(null); abrirPainel("inspector", false); });
  editor.on("nodeRemoved", function () {
    selecionado = null; montarInspector(null); abrirPainel("inspector", false); marcarSujo();
    dicaVazio.hidden = nosDoGrafo().length > 0;
  });
  ["nodeMoved", "connectionCreated", "connectionRemoved"].forEach(function (ev) { editor.on(ev, marcarSujo); });

  /* ---------- paleta ---------- */
  raiz.querySelectorAll("[data-paleta-tipo]").forEach(function (item) {
    var tipo = item.dataset.paletaTipo;
    item.addEventListener("click", function () {
      novoNo(tipo, posicaoLivre());
      abrirPainel("paleta", false);
    });
    item.addEventListener("dragstart", function (ev) { ev.dataTransfer.setData("text/plain", tipo); });
  });
  areaCanvas.addEventListener("dragover", function (ev) { ev.preventDefault(); });
  areaCanvas.addEventListener("drop", function (ev) {
    ev.preventDefault();
    var tipo = ev.dataTransfer.getData("text/plain");
    if (!TIPOS[tipo]) return;
    var r = areaCanvas.getBoundingClientRect();
    novoNo(tipo, {
      x: Math.round((ev.clientX - r.left - editor.canvas_x) / editor.zoom - 110),
      y: Math.round((ev.clientY - r.top - editor.canvas_y) / editor.zoom - 30)
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
    var tag = (document.activeElement && document.activeElement.tagName) || "";
    var emCampo = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") { ev.preventDefault(); salvar(); return; }
    if (ev.key === "Delete" && !emCampo) {
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
      body: JSON.stringify({ grafo: C.extrair(editor.export()), atualizado_em: atualizadoEm })
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

  /* ---------- início ---------- */
  var inicial = JSON.parse(document.getElementById("grafo-inicial").textContent);
  carregar(inicial);
  aplicarPendencias(JSON.parse((document.getElementById("pendencias-iniciais") || { textContent: "[]" }).textContent));
  atualizarStatus();
  montarInspector(null);
  setTimeout(ajustar, 0);
  window.editorFlux = { editor: editor, extrair: function () { return C.extrair(editor.export()); } };
})();
