/* Formulário de função: editor de entradas em linhas (gera o JSON escondido) e campos de liberação.
   A validação é do servidor; aqui só UX. Dados do usuário entram por .value/textContent, nunca por innerHTML. */
(function () {
  "use strict";
  var form = document.querySelector("[data-form-funcao]");
  if (!form) return;
  var MAX = 10;

  var liberar = form.querySelector("[data-liberar]");
  var blocos = form.querySelectorAll("[data-liberar-para]");
  function aplicarLiberar() {
    blocos.forEach(function (b) { b.hidden = b.getAttribute("data-liberar-para") !== liberar.value; });
  }
  if (liberar) { liberar.addEventListener("change", aplicarLiberar); aplicarLiberar(); }

  var raiz = form.querySelector("[data-entradas]");
  var lista = raiz.querySelector("[data-entradas-lista]");
  var vazio = raiz.querySelector("[data-entradas-vazio]");
  var botaoAdd = raiz.querySelector("[data-entrada-adicionar]");
  var json = form.querySelector("[data-entradas-json]");
  var modelo = document.querySelector("[data-entrada-modelo]");

  function f(linha, nome) { return linha.querySelector('[data-f="' + nome + '"]'); }

  function ajustarTipo(linha) {
    var tipo = f(linha, "tipo").value;
    var padrao = f(linha, "padrao"), padraoBool = f(linha, "padrao-bool");
    linha.querySelector("[data-so-lista]").hidden = tipo !== "lista";
    padraoBool.hidden = tipo !== "booleano";
    padrao.hidden = tipo === "booleano";
    padrao.placeholder = tipo === "data" ? "AAAA-MM-DD, hoje ou ontem" : tipo === "numero" ? "ex.: 10" : "";
  }

  function lerLinha(linha) {
    var tipo = f(linha, "tipo").value;
    var e = {
      nome: f(linha, "nome").value.trim(), rotulo: f(linha, "rotulo").value.trim(), tipo: tipo,
      obrigatoria: f(linha, "obrigatoria").checked, padrao: null, opcoes: []
    };
    var bruto = tipo === "booleano" ? f(linha, "padrao-bool").value : f(linha, "padrao").value.trim();
    if (bruto !== "") {
      if (tipo === "numero" && !isNaN(Number(bruto))) e.padrao = Number(bruto);
      else if (tipo === "booleano") e.padrao = bruto === "true";
      else e.padrao = bruto;
    }
    if (tipo === "lista") {
      e.opcoes = f(linha, "opcoes").value.split("\n").map(function (o) { return o.trim(); }).filter(Boolean);
    }
    return e;
  }

  function sincronizar() {
    var linhas = lista.querySelectorAll("[data-entrada]");
    json.value = JSON.stringify(Array.prototype.map.call(linhas, lerLinha));
    vazio.hidden = linhas.length > 0;
    botaoAdd.disabled = linhas.length >= MAX;
    linhas.forEach(function (l, i) {
      l.setAttribute("aria-label", "Entrada " + (i + 1));
    });
  }

  function ligar(linha) {
    var n = lista.querySelectorAll("[data-entrada]").length + "-" + Date.now();
    linha.querySelectorAll(".campo").forEach(function (campo) {
      var ctl = campo.querySelector("[data-f]"), rot = campo.querySelector("label");
      if (ctl && rot) { ctl.id = "ent-" + ctl.getAttribute("data-f") + "-" + n; rot.setAttribute("for", ctl.id); }
    });
    linha.addEventListener("input", sincronizar);
    linha.addEventListener("change", function (ev) { if (ev.target === f(linha, "tipo")) ajustarTipo(linha); sincronizar(); });
    linha.querySelector("[data-entrada-remover]").addEventListener("click", function () { linha.remove(); sincronizar(); });
    ajustarTipo(linha);
  }

  function adicionar(dados) {
    var linha = modelo.content.firstElementChild.cloneNode(true);
    lista.appendChild(linha);
    if (dados) {
      f(linha, "nome").value = dados.nome || "";
      f(linha, "rotulo").value = dados.rotulo || "";
      f(linha, "tipo").value = dados.tipo || "texto";
      f(linha, "obrigatoria").checked = !!dados.obrigatoria;
      var p = dados.padrao;
      if (p !== null && p !== undefined) {
        if (dados.tipo === "booleano") f(linha, "padrao-bool").value = p ? "true" : "false";
        else f(linha, "padrao").value = String(p);
      }
      f(linha, "opcoes").value = (dados.opcoes || []).join("\n");
    }
    ligar(linha);
    sincronizar();
    return linha;
  }

  botaoAdd.addEventListener("click", function () { adicionar().querySelector("[data-f=nome]").focus(); });

  var inicial = [];
  try { inicial = JSON.parse(json.value || "[]"); } catch (e) { inicial = []; }
  if (Array.isArray(inicial)) inicial.slice(0, MAX).forEach(adicionar);
  sincronizar();

  form.addEventListener("submit", sincronizar);
})();
