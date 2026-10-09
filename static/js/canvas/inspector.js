/* Inspector por tipo (EDV-02): monta o formulário de um nó a partir de EsquemasNos. JS fino: só edita a config;
   a validação é do servidor e volta como pendência por campo. Dado do usuário só entra por value / textContent. */
(function (raiz) {
  "use strict";
  var E = raiz.EsquemasNos, C = raiz.ConversorGrafo, X = raiz.ExpressaoUI;
  var contador = 0;

  function criar(tag, classe, texto) {
    var e = document.createElement(tag);
    if (classe) e.className = classe;
    if (texto !== undefined) e.textContent = texto;
    return e;
  }

  function montar(alvo, ctx) {
    alvo.replaceChildren();
    var d = ctx.dados;
    var form = criar("div", "inspector__form");
    var tipoInfo = C.tipoDe(d.tipo);

    function icone(nome, tam) {
      var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "icone icone--" + (tam || 16)); svg.setAttribute("aria-hidden", "true");
      var u = document.createElementNS("http://www.w3.org/2000/svg", "use");
      u.setAttribute("href", ctx.sprite + "#" + nome); svg.appendChild(u);
      return svg;
    }
    function id(c) { return "insp-" + String(c).replace(/\W+/g, "-"); }
    function mudar(fn, recarrega) { ctx.aoMudar(fn); if (recarrega) montar(alvo, Object.assign({}, ctx, { dados: ctx.atual() })); }
    function atual() { return ctx.atual().config; }
    function pendenciasDe(campo) {
      return (ctx.pendencias || []).filter(function (p) { return p.campo && (p.campo === campo || String(campo).indexOf(p.campo + ".") === 0 || p.campo.indexOf(campo + ".") === 0); });
    }
    function comErros(caixa, campo) {
      pendenciasDe(campo).forEach(function (p) {
        caixa.classList.add("campo--erro");
        caixa.appendChild(criar("p", "campo__erro", p.mensagem));
      });
      return caixa;
    }
    function rotulo(caixa, texto, para) {
      var l = criar("label", "campo__rotulo", texto); if (para) l.setAttribute("for", para); caixa.appendChild(l);
    }
    function ajuda(caixa, texto) { if (texto) caixa.appendChild(criar("p", "campo__ajuda", texto)); }
    function bloqueado() { return d.tipo === "codigo" && !ctx.podeCodigo; }

    /* ----- controles ----- */
    function texto(f, base, opcoes) {
      opcoes = opcoes || {};
      var caixa = criar("div", "campo"), i = id(f.c);
      rotulo(caixa, f.rotulo, i);
      var inp = criar("input"); inp.type = "text"; inp.id = i; inp.value = valor(f, base) || "";
      if (f.max) inp.maxLength = f.max; if (f.placeholder) inp.placeholder = f.placeholder;
      inp.disabled = bloqueado();
      inp.addEventListener("input", function () { mudar(function (x) { E.definirEm(x.config, caminho(f, base), inp.value); }); });
      caixa.appendChild(inp); ajuda(caixa, f.ajuda);
      return comErros(caixa, caminho(f, base));
    }
    function numero(f, base) {
      var caixa = criar("div", "campo"), i = id(f.c);
      rotulo(caixa, f.rotulo, i);
      var inp = criar("input"); inp.type = "number"; inp.id = i; inp.inputMode = "numeric";
      if (f.min != null) inp.min = f.min; if (f.max != null) inp.max = f.max;
      var v = valor(f, base); inp.value = v == null ? "" : v;
      inp.addEventListener("input", function () {
        var n = inp.value === "" ? "" : Number(inp.value);
        mudar(function (x) { E.definirEm(x.config, caminho(f, base), n); }, f.recarrega);
      });
      caixa.appendChild(inp); ajuda(caixa, f.ajuda);
      return comErros(caixa, caminho(f, base));
    }
    function selecao(f, base, opcoesFixas) {
      var caixa = criar("div", "campo"), i = id(f.c);
      rotulo(caixa, f.rotulo, i);
      var sel = criar("select"); sel.id = i;
      (opcoesFixas || f.opcoes).forEach(function (o) {
        var op = criar("option", "", o[1]); op.value = o[0]; if (String(valor(f, base)) === String(o[0])) op.selected = true; sel.appendChild(op);
      });
      sel.disabled = bloqueado();
      sel.addEventListener("change", function () { mudar(function (x) { E.definirEm(x.config, caminho(f, base), sel.value); if (f.aoMudar) f.aoMudar(x.config, sel.value); }, f.recarrega); });
      var env = criar("div", "campo__select"); env.appendChild(sel); env.appendChild(icone("chevron-down"));
      caixa.appendChild(env); ajuda(caixa, f.ajuda);
      return comErros(caixa, caminho(f, base));
    }
    function alternar(rot, marcado, aoMudar, ajudaTexto) {
      var caixa = criar("div", "campo");
      var l = criar("label", "toggle"); l.appendChild(criar("span", "", rot));
      var inp = criar("input"); inp.type = "checkbox"; inp.checked = !!marcado; inp.disabled = bloqueado();
      inp.addEventListener("change", function () { aoMudar(inp.checked); });
      l.appendChild(inp); l.appendChild(criar("span", "toggle__trilho"));
      caixa.appendChild(l); ajuda(caixa, ajudaTexto);
      return caixa;
    }
    function expressao(f, base, semRotulo) {
      var caixa = criar("div", "campo"), i = id(f.c);
      if (!semRotulo) rotulo(caixa, f.rotulo, i);
      caixa.appendChild(X.campoExpressao({
        id: i, valor: valor(f, base) || "", multilinha: f.multilinha, mono: f.mono, placeholder: f.placeholder, max: f.max,
        aoMudar: function (v) { mudar(function (x) { E.definirEm(x.config, caminho(f, base), v); }); },
        previa: ctx.previa
      }));
      ajuda(caixa, f.ajuda);
      return comErros(caixa, caminho(f, base));
    }
    function codigo(f) {
      var caixa = criar("div", "campo"), i = id(f.c);
      rotulo(caixa, f.rotulo, i);
      if (bloqueado()) {
        var av = criar("div", "alerta alerta--aviso"); av.appendChild(icone("shield-check"));
        av.appendChild(criar("span", "", "Só administradores editam o nó Código."));
        caixa.appendChild(av);
      }
      var ed = X.editorCodigo({ id: i, valor: valor(f), max: f.max, aoMudar: function (v) { mudar(function (x) { x.config[f.c] = v; }); } });
      if (bloqueado()) ed.querySelector("textarea").readOnly = true;
      caixa.appendChild(ed); ajuda(caixa, f.ajuda);
      return comErros(caixa, f.c);
    }
    function lista(f) {
      var caixa = criar("div", "campo"); caixa.appendChild(criar("span", "campo__rotulo", f.rotulo));
      var corpo = criar("div", "pares");
      function emitir() {
        var itens = [].map.call(corpo.querySelectorAll("input"), function (i) { return i.value; });
        mudar(function (x) { x.config[f.c] = itens; });
      }
      function linha(v) {
        var l = criar("div", "par par--simples"), inp = criar("input"); inp.type = "text"; inp.value = v; inp.placeholder = f.placeholder || "";
        inp.setAttribute("aria-label", f.rotulo); inp.addEventListener("input", emitir);
        l.appendChild(inp); l.appendChild(removerBtn(function () { l.remove(); emitir(); })); return l;
      }
      (valor(f) || []).forEach(function (v) { corpo.appendChild(linha(v)); });
      caixa.appendChild(corpo);
      caixa.appendChild(botaoAdicionar("Adicionar campo", function () { if (corpo.children.length < 30) { corpo.appendChild(linha("")); emitir(); } }));
      return comErros(caixa, f.c);
    }
    function removerBtn(fn) {
      var b = criar("button", "botao botao--icone"); b.type = "button"; b.setAttribute("aria-label", "Remover");
      b.appendChild(icone("x")); b.addEventListener("click", fn); return b;
    }
    function botaoAdicionar(rot, fn) {
      var b = criar("button", "botao botao--secundario", rot); b.type = "button"; b.addEventListener("click", fn); return b;
    }
    function pares(f) {
      var caixa = criar("div", "campo"); caixa.appendChild(criar("span", "campo__rotulo", f.rotulo));
      var corpo = criar("div", "pares");
      function emitir() {
        var itens = [].map.call(corpo.querySelectorAll(".par"), function (l) { var i = l.querySelectorAll("input"); return { nome: i[0].value, valor: i[1].value }; });
        mudar(function (x) { E.definirEm(x.config, f.c, itens); });
      }
      function linha(p) {
        var l = criar("div", "par"), n = criar("input"), v = criar("input");
        n.type = v.type = "text"; n.placeholder = "Nome"; v.placeholder = "Valor"; n.value = p.nome; v.value = p.valor;
        n.setAttribute("aria-label", f.rotulo + ": nome"); v.setAttribute("aria-label", f.rotulo + ": valor");
        n.addEventListener("input", emitir); v.addEventListener("input", emitir);
        l.appendChild(n); l.appendChild(v); l.appendChild(removerBtn(function () { l.remove(); emitir(); })); return l;
      }
      (valor(f) || []).forEach(function (p) { corpo.appendChild(linha(p)); });
      caixa.appendChild(corpo);
      caixa.appendChild(botaoAdicionar("Adicionar", function () { if (corpo.children.length < 30) { corpo.appendChild(linha({ nome: "", valor: "" })); emitir(); } }));
      return comErros(caixa, f.c);
    }
    function tabela(f) {
      var caixa = criar("div", "campo"); caixa.appendChild(criar("span", "campo__rotulo", f.rotulo));
      var corpo = criar("div", "tabela-campos");
      (valor(f) || []).forEach(function (_, idx) {
        var cartao = criar("div", "linha-campos");
        f.colunas.forEach(function (col) {
          var sub = { c: f.c + "." + idx + "." + col.c, rotulo: col.rotulo, opcoes: col.opcoes, placeholder: col.placeholder };
          var ctrl = col.k === "select" ? selecao(sub, "", col.opcoes) : col.k === "expr" ? expressao(sub, "") : texto(sub, "");
          cartao.appendChild(ctrl);
        });
        cartao.appendChild(removerBtn(function () { mudar(function (x) { x.config[f.c].splice(idx, 1); }, true); }));
        corpo.appendChild(cartao);
      });
      caixa.appendChild(corpo);
      caixa.appendChild(botaoAdicionar("Adicionar", function () {
        if ((valor(f) || []).length >= (f.max || 50)) return;
        mudar(function (x) { (x.config[f.c] = x.config[f.c] || []).push(C.clonar(f.novo)); }, true);
      }));
      return comErros(caixa, f.c);
    }
    function condicoes(f, base) {
      var prefixo = base ? base + "." : "";
      var caixa = criar("div", "campo"); if (f.rotulo) caixa.appendChild(criar("span", "campo__rotulo", f.rotulo));
      var lista = E.valorEm(atual(), prefixo + "condicoes") || [];
      var corpo = criar("div", "condicoes");
      lista.forEach(function (cond, idx) {
        var linha = criar("div", "condicao"), p = prefixo + "condicoes." + idx + ".";
        linha.appendChild(expressao({ c: p + "esquerda", rotulo: "Valor 1", placeholder: "{{ $json.campo }}" }, ""));
        linha.appendChild(selecao({ c: p + "operador", rotulo: "Condição", recarrega: true }, "", E.OPERADORES));
        if (!E.unario(cond.operador)) linha.appendChild(expressao({ c: p + "direita", rotulo: "Valor 2" }, ""));
        linha.appendChild(selecao({ c: p + "tipo", rotulo: "Tipo" }, "", E.TIPOS_VALOR));
        if (lista.length > 1) {
          var rm = removerBtn(function () { mudar(function (x) { E.valorEm(x.config, prefixo + "condicoes").splice(idx, 1); }, true); });
          rm.classList.add("condicao__remover"); linha.appendChild(rm);
        }
        corpo.appendChild(linha);
      });
      caixa.appendChild(corpo);
      if (lista.length > 1) caixa.appendChild(selecao({ c: prefixo + "combinar", rotulo: "Combinar condições com", recarrega: false }, "", [["e", "E (todas)"], ["ou", "OU (qualquer uma)"]]));
      caixa.appendChild(botaoAdicionar("Adicionar condição", function () {
        if (lista.length >= 20) return;
        mudar(function (x) { E.valorEm(x.config, prefixo + "condicoes").push(C.condicaoPadrao()); }, true);
      }));
      return comErros(caixa, prefixo ? prefixo + "condicoes" : "condicoes");
    }
    function regras(f) {
      var caixa = criar("div", "campo"); caixa.appendChild(criar("span", "campo__rotulo", f.rotulo));
      (atual().regras || []).forEach(function (_, idx) {
        var bloco = criar("div", "regra");
        var cab = criar("div", "regra__cab"); cab.appendChild(criar("strong", "", "Regra " + (idx + 1) + " · saída " + (idx + 1)));
        if ((atual().regras || []).length > 1) cab.appendChild(removerBtn(function () { mudar(function (x) { x.config.regras.splice(idx, 1); }, true); }));
        bloco.appendChild(cab);
        bloco.appendChild(texto({ c: "regras." + idx + ".rotulo", rotulo: "Rótulo da saída (opcional)", max: 40, placeholder: "regra " + (idx + 1) }, ""));
        bloco.appendChild(condicoes({ rotulo: "" }, "regras." + idx));
        caixa.appendChild(bloco);
      });
      if ((atual().regras || []).length < f.max) caixa.appendChild(botaoAdicionar("Adicionar regra", function () {
        mudar(function (x) { x.config.regras.push({ condicoes: [C.condicaoPadrao()], combinar: "e", rotulo: "" }); }, true);
      }));
      return comErros(caixa, "regras");
    }
    function credencial(f) {
      var nomes = ctx.credenciais || [];
      var caixa = criar("div", "campo"), i = id("credencial");
      rotulo(caixa, f.rotulo, i);
      var sel = criar("select"); sel.id = i;
      var atualNome = atual().credencial || "";
      var op0 = criar("option", "", "Nenhuma"); op0.value = ""; sel.appendChild(op0);
      var achou = false;
      nomes.forEach(function (n) { var o = criar("option", "", n); o.value = n; if (n === atualNome) { o.selected = true; achou = true; } sel.appendChild(o); });
      if (atualNome && !achou) { var o = criar("option", "", atualNome + " (não encontrada)"); o.value = atualNome; o.selected = true; sel.appendChild(o); }
      sel.addEventListener("change", function () { mudar(function (x) { x.config.credencial = sel.value || null; }); });
      var env = criar("div", "campo__select"); env.appendChild(sel); env.appendChild(icone("chevron-down"));
      caixa.appendChild(env);
      ajuda(caixa, nomes.length ? "O valor secreto nunca aparece no fluxo, no histórico nem na exportação." : (ctx.urlCredenciais ? "Nenhuma credencial cadastrada. Crie uma na tela Credenciais." : "Nenhuma credencial disponível."));
      if (ctx.urlCredenciais) { var a = criar("a", "campo__link", "Gerenciar credenciais"); a.href = ctx.urlCredenciais; a.target = "_blank"; a.rel = "noopener"; caixa.appendChild(a); }
      return comErros(caixa, "credencial");
    }
    function paginacao(f) {
      var p = atual().paginacao, caixa = criar("div", "campo grupo-campos");
      caixa.appendChild(alternar("Paginação", !!p, function (on) {
        mudar(function (x) {
          x.config.paginacao = on ? { modo: "atualizar_parametro", onde: "query", nome: "page", valor: "{{ $pageCount + 1 }}", parar_quando: "resposta_vazia", limite_paginas: 10, intervalo_ms: 0 } : null;
        }, true);
      }, "Busca página após página e junta os itens."));
      if (p) {
        var sub = function (c, rot, extra) { return Object.assign({ c: "paginacao." + c, rotulo: rot }, extra || {}); };
        caixa.appendChild(selecao(sub("modo", "Modo", { recarrega: true }), "", [["atualizar_parametro", "Atualizar um parâmetro a cada página"], ["proxima_url", "Usar a URL da próxima página"]]));
        if (p.modo === "proxima_url") caixa.appendChild(expressao(sub("url", "URL da próxima página", { placeholder: "{{ $response.corpo.next }}" }), ""));
        else {
          caixa.appendChild(selecao(sub("onde", "Onde"), "", [["query", "Parâmetro de consulta"], ["corpo", "Corpo"], ["header", "Cabeçalho"]]));
          caixa.appendChild(texto(sub("nome", "Nome do parâmetro"), ""));
          caixa.appendChild(expressao(sub("valor", "Valor"), ""));
        }
        caixa.appendChild(selecao(sub("parar_quando", "Parar quando", { recarrega: true }), "", [["resposta_vazia", "A resposta vier vazia"], ["status", "O status for um destes"], ["expressao", "Uma expressão for verdadeira"]]));
        if (p.parar_quando === "status") {
          var cc = criar("div", "campo"), ci = id("paginacao.codigos"); rotulo(cc, "Códigos de status (separados por vírgula)", ci);
          var inpC = criar("input"); inpC.type = "text"; inpC.id = ci; inpC.placeholder = "404, 204"; inpC.value = (p.codigos || []).join(", ");
          inpC.addEventListener("input", function () {
            var nums = inpC.value.split(",").map(function (t) { return parseInt(t.trim(), 10); }).filter(function (n) { return !isNaN(n); });
            mudar(function (x) { x.config.paginacao.codigos = nums; });
          });
          cc.appendChild(inpC); caixa.appendChild(comErros(cc, "paginacao.codigos"));
        }
        if (p.parar_quando === "expressao") caixa.appendChild(expressao(sub("expressao", "Expressão (verdadeiro = para)", { placeholder: "{{ $response.corpo.length < 100 }}" }), ""));
        caixa.appendChild(numero(sub("limite_paginas", "Limite de páginas (1 a 100)", { min: 1, max: 100 }), ""));
        caixa.appendChild(numero(sub("intervalo_ms", "Intervalo entre páginas (ms)", { min: 0, max: 5000 }), ""));
      }
      return comErros(caixa, "paginacao");
    }

    function caminho(f, base) { return base ? base + "." + f.c : f.c; }
    function valor(f, base) { return E.valorEm(atual(), caminho(f, base)); }

    function campo(f) {
      switch (f.k) {
        case "texto": return texto(f);
        case "expr": return expressao(f);
        case "numero": return numero(f);
        case "select": return selecao(f);
        case "toggle": return comErros(alternar(f.rotulo, valor(f), function (v) { mudar(function (x) { E.definirEm(x.config, f.c, v); }, f.recarrega); }, f.ajuda), f.c);
        case "lista": return lista(f);
        case "pares": return pares(f);
        case "tabela": return tabela(f);
        case "condicoes": return condicoes(f, "");
        case "regras": return regras(f);
        case "codigo": return codigo(f);
        case "credencial": return credencial(f);
        case "paginacao": return paginacao(f);
        case "aviso": return criar("p", "campo__ajuda", f.texto);
        default: return criar("span");
      }
    }

    /* ----- cabeçalho, pendências, título ----- */
    var cab = criar("div", "inspector__cab");
    var ic = criar("span", "no__icone no__icone--" + tipoInfo.grupo); ic.appendChild(icone(tipoInfo.icone, 20));
    cab.appendChild(ic); cab.appendChild(criar("h2", "card__titulo", tipoInfo.rotulo));
    form.appendChild(cab);
    var geral = (ctx.pendencias || []).filter(function (p) { return !p.campo; });
    if (geral.length) {
      var alerta = criar("div", "alerta alerta--erro"); alerta.setAttribute("role", "alert");
      alerta.appendChild(icone("circle-alert")); alerta.appendChild(criar("span", "", geral.map(function (p) { return p.mensagem; }).join(" ")));
      form.appendChild(alerta);
    }
    var tc = criar("div", "campo"), ti = id("titulo"); rotulo(tc, "Título", ti);
    var inpT = criar("input"); inpT.type = "text"; inpT.id = ti; inpT.maxLength = 80; inpT.value = d.titulo;
    inpT.addEventListener("input", function () { mudar(function (x) { x.titulo = inpT.value; }); });
    tc.appendChild(inpT); form.appendChild(comErros(tc, "titulo"));

    /* ----- parâmetros por tipo ----- */
    var campos = E.esquema(d.tipo), temExpr = false;
    var cfg = atual();
    campos.forEach(function (f) {
      if (f.quando && !f.quando(cfg)) return;
      if (/expr|condicoes|regras|tabela|paginacao/.test(f.k)) temExpr = true;
      form.appendChild(campo(f));
    });
    if (temExpr && X) form.appendChild(X.listaVariaveis(ctx.anteriores));

    /* ----- configurações do nó (MV2-02) ----- */
    var cfgNo = criar("details", "inspector__secao");
    cfgNo.appendChild(criar("summary", "inspector__secao-titulo", "Configurações do nó"));
    var corpoCfg = criar("div", "inspector__secao-corpo");
    corpoCfg.appendChild(alternar("Desativado", d.desativado, function (v) { mudar(function (x) { x.desativado = v; }); }, "Desativado, o nó só repassa os itens da entrada 1."));
    if (["gatilho", "saida", "sem_operacao", "parar_com_erro", "juntar", "repetir_em_lotes"].indexOf(d.tipo) < 0) {
      corpoCfg.appendChild(alternar("Executar uma vez", d.executar_uma_vez, function (v) { mudar(function (x) { x.executar_uma_vez = v; }); }, "Roda só com o primeiro item de entrada."));
      corpoCfg.appendChild((function () {
        var caixa = criar("div", "campo"), i = id("em_erro"); rotulo(caixa, "Em caso de erro", i);
        var sel = criar("select"); sel.id = i;
        [["parar", "Parar a execução"], ["continuar", "Continuar com o erro no item"], ["saida_de_erro", "Enviar para uma saída de erro"]].forEach(function (o) {
          var op = criar("option", "", o[1]); op.value = o[0]; if (o[0] === d.em_erro) op.selected = true; sel.appendChild(op);
        });
        sel.addEventListener("change", function () { mudar(function (x) { x.em_erro = sel.value; }, false); if (ctx.aoMudarPortas) ctx.aoMudarPortas(); });
        var env = criar("div", "campo__select"); env.appendChild(sel); env.appendChild(icone("chevron-down")); caixa.appendChild(env);
        return caixa;
      })());
    }
    form.appendChild(cfgNo);
    cfgNo.appendChild(corpoCfg);

    /* ----- dados do último teste e dados fixos (MV2-06) ----- */
    var dados = criar("details", "inspector__secao");
    dados.open = !!(ctx.resultado || (d.fixos && d.fixos.length));
    dados.appendChild(criar("summary", "inspector__secao-titulo", "Dados do nó"));
    var corpoDados = criar("div", "inspector__secao-corpo");
    var r = ctx.resultado;
    if (r) {
      var linhaR = criar("p", "campo__ajuda");
      linhaR.textContent = "Último teste: " + (r.status || "—") + " · " + (r.itens_entrada || 0) + " item(ns) de entrada, " + (r.itens_saida || 0) + " de saída";
      corpoDados.appendChild(linhaR);
      if (r.erro) { var er = criar("div", "alerta alerta--erro"); er.appendChild(icone("circle-alert")); er.appendChild(criar("span", "", typeof r.erro === "string" ? r.erro : (r.erro.mensagem || "Erro"))); corpoDados.appendChild(er); }
      var pre = criar("pre", "bloco-codigo__pre"); pre.textContent = JSON.stringify(r.saida || [], null, 2).slice(0, 4000);
      pre.tabIndex = 0; corpoDados.appendChild(criar("span", "campo__rotulo", "Saída (primeiros itens)")); corpoDados.appendChild(pre);
      if (r.logs && r.logs.length) { var lg = criar("pre", "bloco-codigo__pre"); lg.textContent = r.logs.join("\n"); corpoDados.appendChild(criar("span", "campo__rotulo", "console.log")); corpoDados.appendChild(lg); }
    } else corpoDados.appendChild(criar("p", "campo__ajuda", "Sem dados ainda. Use “Executar este nó” para testar."));
    if (d.fixos && d.fixos.length) corpoDados.appendChild(criar("p", "campo__ajuda", "Dados fixos ativos: " + d.fixos.length + " item(ns). O nó não executa; entrega estes itens."));
    var acoesDados = criar("div", "inspector__acoes");
    if (r && (r.saida || []).length && ctx.acoes.fixar) acoesDados.appendChild(botaoAdicionar("Fixar estes dados", function () { ctx.acoes.fixar(r.saida); }));
    if (d.fixos && d.fixos.length && ctx.acoes.limpar) acoesDados.appendChild(botaoAdicionar("Limpar dados fixos", function () { ctx.acoes.limpar(); }));
    corpoDados.appendChild(acoesDados);
    dados.appendChild(corpoDados); form.appendChild(dados);

    /* ----- ações ----- */
    var acoes = criar("div", "inspector__acoes");
    function acao(rot, nome, classe, fn) {
      var b = criar("button", "botao " + classe); b.type = "button"; b.appendChild(icone(nome)); b.appendChild(criar("span", "", rot));
      b.addEventListener("click", fn); acoes.appendChild(b); return b;
    }
    if (ctx.acoes.executarNo && d.tipo !== "nota") acao("Executar este nó", "play", "botao--secundario", ctx.acoes.executarNo).dataset.acaoNo = "executar-no";
    if (d.tipo !== "gatilho") acao("Duplicar", "copy", "botao--secundario", ctx.acoes.duplicar).dataset.acaoNo = "duplicar";
    acao("Remover nó", "trash", "botao--destrutivo", ctx.acoes.remover).dataset.acaoNo = "remover";
    form.appendChild(acoes);
    alvo.appendChild(form);
  }

  /* Inspector da nota (sticky). */
  function montarNota(alvo, ctx) {
    alvo.replaceChildren();
    var d = ctx.dados, form = criar("div", "inspector__form");
    form.appendChild(criar("h2", "card__titulo", "Nota"));
    var c = criar("div", "campo"), i = "insp-nota-texto";
    c.appendChild(Object.assign(criar("label", "campo__rotulo", "Texto"), { htmlFor: i }));
    var ta = criar("textarea"); ta.id = i; ta.rows = 6; ta.maxLength = 5000; ta.value = d.texto || "";
    ta.addEventListener("input", function () { ctx.aoMudar(function (x) { x.texto = ta.value; }); });
    c.appendChild(ta); c.appendChild(criar("p", "campo__ajuda", "Texto simples. Use **negrito** e linhas começando com - para listas."));
    form.appendChild(c);
    var cor = criar("div", "campo"); cor.appendChild(criar("span", "campo__rotulo", "Cor"));
    var seg = criar("div", "notas__cores"); seg.setAttribute("role", "radiogroup"); seg.setAttribute("aria-label", "Cor da nota");
    C.CORES_NOTA.forEach(function (nome) {
      var b = criar("button", "notas__cor notas__cor--" + nome); b.type = "button"; b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", String(d.cor === nome)); b.setAttribute("aria-label", nome);
      b.addEventListener("click", function () { ctx.aoMudar(function (x) { x.cor = nome; }); montarNota(alvo, Object.assign({}, ctx, { dados: ctx.atual() })); });
      seg.appendChild(b);
    });
    cor.appendChild(seg); form.appendChild(cor);
    var rm = criar("button", "botao botao--destrutivo", "Remover nota"); rm.type = "button"; rm.addEventListener("click", ctx.acoes.remover);
    form.appendChild(rm);
    alvo.appendChild(form);
  }

  raiz.InspectorNos = { montar: montar, montarNota: montarNota };
})(window);
