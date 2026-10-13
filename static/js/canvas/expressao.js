/* Campo de expressão (EDV-02): destaque de {{ }}, prévia do valor e inserção de variáveis; editor de código
   monoespaçado com numeração de linhas e Tab. Dado do usuário só entra no DOM por textContent / value. */
(function (raiz) {
  "use strict";

  function criar(tag, classe, texto) {
    var e = document.createElement(tag);
    if (classe) e.className = classe;
    if (texto !== undefined) e.textContent = texto;
    return e;
  }

  /* Divide o texto em pedaços {t, tipo}: texto | chave ({{ }}) | variavel ($x) | texto-lit ('..') | numero. */
  function destacar(texto) {
    var saida = [], re = /\{\{|\}\}/g, dentro = false, ultimo = 0, m;
    function interno(trecho) {
      var r = /(\$[A-Za-z_]\w*|'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|\b\d+(?:\.\d+)?\b)/g, u = 0, x;
      while ((x = r.exec(trecho))) {
        if (x.index > u) saida.push({ t: trecho.slice(u, x.index), tipo: "ex" });
        var tipo = x[0][0] === "$" ? "variavel" : /^\d/.test(x[0]) ? "numero" : "literal";
        saida.push({ t: x[0], tipo: tipo });
        u = x.index + x[0].length;
      }
      if (u < trecho.length) saida.push({ t: trecho.slice(u), tipo: "ex" });
    }
    while ((m = re.exec(texto))) {
      if (m[0] === "{{" && !dentro) {
        if (m.index > ultimo) saida.push({ t: texto.slice(ultimo, m.index), tipo: "texto" });
        saida.push({ t: "{{", tipo: "chave" }); dentro = true; ultimo = m.index + 2;
      } else if (m[0] === "}}" && dentro) {
        interno(texto.slice(ultimo, m.index)); saida.push({ t: "}}", tipo: "chave" }); dentro = false; ultimo = m.index + 2;
      }
    }
    if (ultimo < texto.length) { if (dentro) interno(texto.slice(ultimo)); else saida.push({ t: texto.slice(ultimo), tipo: "texto" }); }
    return saida;
  }

  function pintar(espelho, texto) {
    espelho.replaceChildren();
    destacar(texto).forEach(function (p) {
      var s = criar("span", "expr__" + p.tipo, p.t);
      espelho.appendChild(s);
    });
    espelho.appendChild(document.createTextNode("​")); // mantém a altura da última linha vazia
  }

  function ehExpressao(v) { return /\{\{/.test(v || "") || /^=/.test(v || ""); }

  var ultimoCampo = null; // último campo de expressão focado: destino das variáveis

  function inserirNoCursor(texto) {
    var alvo = ultimoCampo;
    if (!alvo || !document.body.contains(alvo)) return false;
    var ini = alvo.selectionStart == null ? alvo.value.length : alvo.selectionStart;
    var fim = alvo.selectionEnd == null ? ini : alvo.selectionEnd;
    var antes = alvo.value.slice(0, ini), depois = alvo.value.slice(fim);
    // Dentro de {{ }} insere só a variável; fora, envolve.
    var abertas = (antes.match(/\{\{/g) || []).length, fechadas = (antes.match(/\}\}/g) || []).length;
    var ins = abertas > fechadas ? texto : "{{ " + texto + " }}";
    alvo.value = antes + ins + depois;
    alvo.selectionStart = alvo.selectionEnd = antes.length + ins.length;
    alvo.dispatchEvent(new Event("input", { bubbles: true }));
    alvo.focus();
    return true;
  }

  /* opcoes: {id, valor, multilinha, mono, placeholder, max, aoMudar(v), previa(v) -> Promise<{ok,valor,erro,sem_dados}>} */
  function campoExpressao(opcoes) {
    var caixa = criar("div", "expr");
    var area = criar("div", "expr__area" + (opcoes.mono ? " expr__area--mono" : ""));
    var espelho = criar("div", "expr__espelho"); espelho.setAttribute("aria-hidden", "true");
    var entrada = criar("textarea", "expr__entrada");
    entrada.id = opcoes.id; entrada.rows = opcoes.multilinha ? 4 : 1; entrada.spellcheck = false;
    entrada.value = opcoes.valor || "";
    if (opcoes.max) entrada.maxLength = opcoes.max;
    if (opcoes.placeholder) entrada.placeholder = opcoes.placeholder;
    if (!opcoes.multilinha) entrada.addEventListener("keydown", function (ev) { if (ev.key === "Enter") ev.preventDefault(); });
    area.appendChild(espelho); area.appendChild(entrada);
    caixa.appendChild(area);
    var previaEl = criar("p", "expr__previa"); previaEl.hidden = true; previaEl.setAttribute("aria-live", "polite");
    caixa.appendChild(previaEl);

    var timer = null, seq = 0;
    function ajustar() {
      pintar(espelho, entrada.value);
      entrada.style.height = "auto";
      entrada.style.height = Math.max(entrada.scrollHeight, 36) + "px";
    }
    function atualizarPrevia() {
      var v = entrada.value;
      if (!opcoes.previa || !ehExpressao(v)) { previaEl.hidden = true; return; }
      var minha = ++seq;
      previaEl.hidden = false; previaEl.className = "expr__previa"; previaEl.textContent = "Calculando prévia…";
      opcoes.previa(v).then(function (r) {
        if (minha !== seq) return;
        if (r && r.ok) { previaEl.className = "expr__previa expr__previa--ok"; previaEl.textContent = "Prévia: " + (typeof r.valor === "string" ? r.valor : JSON.stringify(r.valor)); }
        else if (!r || r.sem_dados) { previaEl.className = "expr__previa"; previaEl.textContent = "Prévia: sem dados. Execute o fluxo em modo de teste."; }
        else { previaEl.className = "expr__previa expr__previa--erro"; previaEl.textContent = (r.erro || "Expressão inválida."); }
      }).catch(function () {
        if (minha === seq) { previaEl.className = "expr__previa"; previaEl.textContent = "Prévia indisponível."; }
      });
    }
    entrada.addEventListener("input", function () {
      ajustar();
      if (opcoes.aoMudar) opcoes.aoMudar(entrada.value);
      clearTimeout(timer); timer = setTimeout(atualizarPrevia, 450);
    });
    entrada.addEventListener("focus", function () { ultimoCampo = entrada; });
    ajustar();
    setTimeout(function () { ajustar(); atualizarPrevia(); }, 0);
    return caixa;
  }

  /* Lista de variáveis disponíveis (EDV-02). anteriores: [{titulo}]. */
  function listaVariaveis(anteriores) {
    var det = criar("details", "variaveis");
    det.appendChild(criar("summary", "variaveis__titulo", "Variáveis disponíveis"));
    var corpo = criar("div", "variaveis__corpo");
    function chip(expr, dica) {
      var b = criar("button", "variaveis__chip", expr); b.type = "button"; b.title = dica;
      b.addEventListener("mousedown", function (ev) { ev.preventDefault(); }); // não tira o foco do campo
      b.addEventListener("click", function () { inserirNoCursor(expr); });
      corpo.appendChild(b);
    }
    chip("$json", "Item atual");
    (anteriores || []).slice(0, 12).forEach(function (n) {
      chip("$('" + String(n.titulo).replace(/\\/g, "\\\\").replace(/'/g, "\\'") + "').first().json", "Primeiro item de " + n.titulo);
    });
    chip("$input.all()", "Todos os itens de entrada");
    chip("$itemIndex", "Posição do item atual");
    chip("$now", "Agora"); chip("$today", "Hoje");
    chip("$execution.id", "Número da execução"); chip("$workflow.name", "Nome do fluxo"); chip("$usuario.email", "E-mail de quem executa");
    det.appendChild(corpo);
    return det;
  }

  /* Editor de código monoespaçado: numeração de linhas, Tab insere 2 espaços (Esc depois Tab sai do campo). */
  function editorCodigo(opcoes) {
    var caixa = criar("div", "editor-codigo");
    var nums = criar("div", "editor-codigo__linhas"); nums.setAttribute("aria-hidden", "true");
    var entrada = criar("textarea", "editor-codigo__entrada");
    entrada.id = opcoes.id; entrada.spellcheck = false; entrada.value = opcoes.valor || "";
    entrada.setAttribute("wrap", "off"); entrada.setAttribute("autocapitalize", "off"); entrada.setAttribute("autocorrect", "off");
    if (opcoes.max) entrada.maxLength = opcoes.max;
    var escapou = false;
    function numerar() {
      var n = entrada.value.split("\n").length;
      var atual = nums.childElementCount;
      for (; atual < n; atual += 1) nums.appendChild(criar("span", "", String(atual + 1)));
      while (nums.childElementCount > n) nums.lastChild.remove();
      nums.scrollTop = entrada.scrollTop;
    }
    entrada.addEventListener("input", function () { numerar(); if (opcoes.aoMudar) opcoes.aoMudar(entrada.value); });
    entrada.addEventListener("scroll", function () { nums.scrollTop = entrada.scrollTop; });
    entrada.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") { escapou = true; return; }
      if (ev.key === "Tab" && !ev.shiftKey && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
        if (escapou) { escapou = false; return; }
        ev.preventDefault();
        var i = entrada.selectionStart, f = entrada.selectionEnd;
        entrada.value = entrada.value.slice(0, i) + "  " + entrada.value.slice(f);
        entrada.selectionStart = entrada.selectionEnd = i + 2;
        entrada.dispatchEvent(new Event("input", { bubbles: true }));
      } else escapou = false;
    });
    entrada.addEventListener("blur", function () { escapou = false; });
    caixa.appendChild(nums); caixa.appendChild(entrada);
    numerar();
    return caixa;
  }

  var API = { destacar: destacar, campoExpressao: campoExpressao, listaVariaveis: listaVariaveis, editorCodigo: editorCodigo, ehExpressao: ehExpressao, inserirNoCursor: inserirNoCursor };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  else raiz.ExpressaoUI = API;
})(typeof window !== "undefined" ? window : this);
