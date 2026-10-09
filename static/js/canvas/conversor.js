/* Conversor Drawflow <-> grafo canônico v2 (docs/spec/motor-v2.yaml MV2-02, NOV-01). Funções puras, sem DOM.
   Cada nó do Drawflow guarda em `data`: {cid, tipo, titulo, config, desativado, executar_uma_vez, em_erro, fixos}.
   Nota (sticky) é um nó do Drawflow sem portas, com data {cid, tipo: "nota", texto, cor, tamanho}. */
(function (raiz) {
  "use strict";

  var GRUPOS = [
    { id: "gatilhos", rotulo: "Gatilhos" },
    { id: "acoes", rotulo: "Ações" },
    { id: "dados", rotulo: "Dados" },
    { id: "fluxo", rotulo: "Fluxo" },
    { id: "saida", rotulo: "Saída" }
  ];

  /* tipo · nome na tela · grupo · ícone (Lucide) · palavras para a busca */
  var TIPOS = {
    gatilho: { rotulo: "Manual", grupo: "gatilhos", icone: "zap", titulo: "Início", busca: "gatilho manual iniciar" },
    http: { rotulo: "Requisição HTTP", grupo: "acoes", icone: "globe", titulo: "Requisição HTTP", busca: "http api get post rest chamada" },
    codigo: { rotulo: "Código", grupo: "dados", icone: "code", titulo: "Código", busca: "codigo code javascript js script" },
    editar_campos: { rotulo: "Editar campos", grupo: "dados", icone: "pen-line", titulo: "Editar campos", busca: "set campos editar atribuir" },
    filtrar: { rotulo: "Filtrar", grupo: "dados", icone: "funnel", titulo: "Filtrar", busca: "filter filtrar condicao" },
    ordenar: { rotulo: "Ordenar", grupo: "dados", icone: "arrow-up-down", titulo: "Ordenar", busca: "sort ordenar classificar" },
    limitar: { rotulo: "Limitar", grupo: "dados", icone: "list-end", titulo: "Limitar", busca: "limit limitar primeiros ultimos" },
    remover_duplicados: { rotulo: "Remover duplicados", grupo: "dados", icone: "copy-x", titulo: "Remover duplicados", busca: "duplicados unicos distinct" },
    separar_lista: { rotulo: "Separar lista em itens", grupo: "dados", icone: "list-tree", titulo: "Separar lista", busca: "split out separar lista itens" },
    agregar: { rotulo: "Agregar", grupo: "dados", icone: "layers", titulo: "Agregar", busca: "aggregate agregar juntar lista" },
    resumir: { rotulo: "Resumir", grupo: "dados", icone: "sigma", titulo: "Resumir", busca: "summarize resumir contar somar media" },
    data_hora: { rotulo: "Data e hora", grupo: "dados", icone: "calendar-clock", titulo: "Data e hora", busca: "date time data hora formatar" },
    se: { rotulo: "Se", grupo: "fluxo", icone: "split", titulo: "Se", busca: "if se condicao verdadeiro falso" },
    escolher: { rotulo: "Escolher", grupo: "fluxo", icone: "git-branch", titulo: "Escolher", busca: "switch escolher regras" },
    juntar: { rotulo: "Juntar", grupo: "fluxo", icone: "merge", titulo: "Juntar", busca: "merge juntar combinar" },
    repetir_em_lotes: { rotulo: "Repetir em lotes", grupo: "fluxo", icone: "repeat", titulo: "Repetir em lotes", busca: "loop lote repetir batches" },
    parar_com_erro: { rotulo: "Parar com erro", grupo: "fluxo", icone: "octagon-x", titulo: "Parar com erro", busca: "stop error parar erro" },
    sem_operacao: { rotulo: "Sem operação", grupo: "fluxo", icone: "circle-dashed", titulo: "Sem operação", busca: "noop nada sem operacao" },
    saida: { rotulo: "Saída", grupo: "saida", icone: "flag", titulo: "Resultado", busca: "saida resultado fim" }
  };
  var ORDEM_TIPOS = Object.keys(TIPOS);
  var METODOS = ["GET", "POST", "PUT", "PATCH", "DELETE"];
  var CORES_NOTA = ["amarela", "azul", "verde", "cinza"];
  var LIMITE_REGRAS = 10;
  var EM_ERRO = ["parar", "continuar", "saida_de_erro"];

  function clonar(valor) { return valor === undefined ? undefined : JSON.parse(JSON.stringify(valor)); }

  function condicaoPadrao() { return { esquerda: "", operador: "igual", direita: "", tipo: "texto" }; }

  function configPadrao(tipo) {
    switch (tipo) {
      case "http":
        return { metodo: "GET", url: "", query: [], headers: [], corpo: { tipo: "nenhum", conteudo: "" }, credencial: null, resposta: "automatica", resposta_completa: false, paginacao: null };
      case "codigo": return { modo: "uma_vez_para_todos", codigo: "return $input.all();" };
      case "editar_campos": return { modo: "manual", campos: [], incluir_outros: true };
      case "filtrar": return { condicoes: [condicaoPadrao()], combinar: "e", manter_descartados: false };
      case "se": return { condicoes: [condicaoPadrao()], combinar: "e" };
      case "escolher": return { regras: [{ condicoes: [condicaoPadrao()], combinar: "e", rotulo: "" }, { condicoes: [condicaoPadrao()], combinar: "e", rotulo: "" }], saida_outros: true };
      case "ordenar": return { campos: [{ campo: "", ordem: "asc" }] };
      case "limitar": return { quantidade: 10, de: "inicio" };
      case "remover_duplicados": return { comparar: "todos", campos: [] };
      case "separar_lista": return { campo: "", incluir: "nada" };
      case "agregar": return { modo: "todos", campos: [], saida: "dados" };
      case "resumir": return { agrupar_por: [], operacoes: [{ campo: "", op: "contar" }] };
      case "data_hora": return { operacao: "agora", campo: "", formato: "yyyy-MM-dd", quantidade: 1, unidade: "dias", saida: "data" };
      case "juntar": return { modo: "anexar", campo1: "", campo2: "", tipo: "dentro", entrada: 1, entradas: 2 };
      case "repetir_em_lotes": return { tamanho_lote: 100 };
      case "parar_com_erro": return { mensagem: "" };
      default: return {};
    }
  }

  function tipoDe(nome) { return TIPOS[nome] || { rotulo: String(nome), grupo: "fluxo", icone: "circle-dashed", titulo: String(nome), busca: "" }; }

  /* Portas (EDV-01): rótulos de entrada e de saída; "" = porta sem rótulo. */
  function portas(tipo, config, emErro) {
    var c = config || {}, entradas = [""], saidas = [""], i;
    if (tipo === "gatilho") entradas = [];
    else if (tipo === "juntar") {
      var n = Math.max(2, Math.min(4, Number(c.entradas) || 2));
      entradas = [];
      for (i = 1; i <= n; i += 1) entradas.push("Entrada " + i);
    }
    if (tipo === "saida" || tipo === "parar_com_erro") saidas = [];
    else if (tipo === "se") saidas = ["verdadeiro", "falso"];
    else if (tipo === "filtrar") saidas = c.manter_descartados ? ["passou", "descartados"] : [""];
    else if (tipo === "repetir_em_lotes") saidas = ["loop", "pronto"];
    else if (tipo === "escolher") {
      var regras = Math.max(1, Math.min(LIMITE_REGRAS, (c.regras || []).length || 1));
      saidas = [];
      for (i = 1; i <= regras; i += 1) saidas.push(String(((c.regras || [])[i - 1] || {}).rotulo || "").trim() || "regra " + i);
      if (c.saida_outros) saidas.push("outros");
    }
    if (emErro === "saida_de_erro" && tipo !== "saida" && tipo !== "parar_com_erro") saidas = saidas.concat(["erro"]);
    return { entradas: entradas, saidas: saidas };
  }

  function novoId(ids) {
    var usados = {};
    ids.forEach(function (id) { usados[id] = true; });
    var n = ids.length + 1;
    while (usados["n" + n]) n += 1;
    return "n" + n;
  }

  /* Título único no fluxo (MV2-02): "Se", "Se 2", "Se 3"... */
  function tituloUnico(base, titulos, ignorar) {
    var usados = {};
    titulos.forEach(function (t) { if (t !== ignorar) usados[String(t).toLowerCase()] = true; });
    if (!usados[base.toLowerCase()]) return base;
    var n = 2;
    while (usados[(base + " " + n).toLowerCase()]) n += 1;
    return base + " " + n;
  }

  function curto(texto, max) {
    texto = String(texto == null ? "" : texto).replace(/\s+/g, " ").trim();
    return texto.length > (max || 40) ? texto.slice(0, (max || 40) - 1) + "…" : texto;
  }

  function resumoCondicoes(c) {
    var lista = c.condicoes || [];
    if (!lista.length || !lista[0].esquerda) return "Defina a condição";
    var p = lista[0];
    return curto(p.esquerda + " " + String(p.operador || "").replace(/_/g, " ") + (p.direita ? " " + p.direita : ""), 36) + (lista.length > 1 ? " +" + (lista.length - 1) : "");
  }

  function resumo(no) {
    var c = no.config || {};
    switch (no.tipo) {
      case "gatilho": return "Início manual";
      case "saida": return "Mostra o resultado";
      case "http": return c.url ? (c.metodo || "GET") + " " + c.url : "Configure a URL";
      case "codigo": return c.modo === "uma_vez_por_item" ? "JavaScript · por item" : "JavaScript · todos os itens";
      case "editar_campos": return (c.campos || []).length ? (c.campos.length + (c.campos.length === 1 ? " campo" : " campos")) : (c.modo === "json" ? "Modo JSON" : "Sem campos");
      case "filtrar": case "se": return resumoCondicoes(c);
      case "escolher": return (c.regras || []).length + " regras" + (c.saida_outros ? " + outros" : "");
      case "ordenar": return (c.campos || []).filter(function (x) { return x.campo; }).map(function (x) { return x.campo; }).join(", ") || "Escolha o campo";
      case "limitar": return (c.de === "fim" ? "Últimos " : "Primeiros ") + (c.quantidade || 0);
      case "remover_duplicados": return c.comparar === "campos" ? "Por " + ((c.campos || []).join(", ") || "campos") : "Itens inteiros";
      case "separar_lista": return c.campo ? "Lista em " + c.campo : "Escolha o campo da lista";
      case "agregar": return c.modo === "campos" ? "Campos: " + ((c.campos || []).join(", ") || "—") : "Todos os itens";
      case "resumir": return (c.operacoes || []).length + " operações" + ((c.agrupar_por || []).length ? " por " + c.agrupar_por.join(", ") : "");
      case "data_hora": return String(c.operacao || "agora").replace(/_/g, " ");
      case "juntar": return String(c.modo || "anexar").replace(/_/g, " ");
      case "repetir_em_lotes": return "Lotes de " + (c.tamanho_lote || 0);
      case "parar_com_erro": return c.mensagem ? curto(c.mensagem, 36) : "Interrompe com erro";
      case "sem_operacao": return "Repassa os itens";
      default: return "";
    }
  }

  function dadosDoNo(no) {
    return {
      cid: no.id, tipo: no.tipo, titulo: no.titulo, config: clonar(no.config || {}),
      desativado: !!no.desativado, executar_uma_vez: !!no.executar_uma_vez,
      em_erro: EM_ERRO.indexOf(no.em_erro) >= 0 ? no.em_erro : "parar",
      fixos: no.fixos === undefined ? null : clonar(no.fixos)
    };
  }

  /* Nó canônico -> especificação para Drawflow.addNode. */
  function especificacao(no) {
    var p = portas(no.tipo, no.config, no.em_erro);
    return {
      nome: no.tipo, entradas: p.entradas.length, saidas: p.saidas.length,
      rotulosEntrada: p.entradas, rotulosSaida: p.saidas,
      x: (no.posicao && no.posicao.x) || 0, y: (no.posicao && no.posicao.y) || 0,
      data: dadosDoNo(no)
    };
  }

  function tamanhoNota(t) {
    t = t || {};
    return { l: Math.max(160, Math.min(1200, Math.round(Number(t.l) || 240))), a: Math.max(80, Math.min(1200, Math.round(Number(t.a) || 140))) };
  }
  function especificacaoNota(nota) {
    return {
      nome: "nota", entradas: 0, saidas: 0,
      x: (nota.posicao && nota.posicao.x) || 0, y: (nota.posicao && nota.posicao.y) || 0,
      data: {
        cid: nota.id, tipo: "nota", texto: String(nota.texto || ""),
        cor: CORES_NOTA.indexOf(nota.cor) >= 0 ? nota.cor : "amarela", tamanho: tamanhoNota(nota.tamanho)
      }
    };
  }

  /* Paginação do HTTP (MV2-16): só as chaves do modo e do critério de parada (schema fechado). */
  function normalizarPaginacao(p) {
    if (!p || typeof p !== "object") return null;
    var o = { modo: p.modo, parar_quando: p.parar_quando, limite_paginas: p.limite_paginas, intervalo_ms: p.intervalo_ms };
    if (p.modo === "proxima_url") o.url = p.url || "";
    else { o.onde = p.onde; o.nome = p.nome || ""; o.valor = p.valor || ""; }
    if (p.parar_quando === "status") o.codigos = p.codigos || [];
    if (p.parar_quando === "expressao") o.expressao = p.expressao || "";
    return o;
  }
  function normalizarConfig(tipo, config) {
    var c = clonar(config || {});
    if (tipo === "http" && c.paginacao) c.paginacao = normalizarPaginacao(c.paginacao);
    return c;
  }

  /* Drawflow.export() -> grafo canônico v2 (arestas e itens em ordem estável). */
  function extrair(exportado) {
    var dados = exportado.drawflow.Home.data;
    var ids = Object.keys(dados).sort(function (a, b) { return Number(a) - Number(b); });
    var cid = {};
    ids.forEach(function (id) { cid[id] = dados[id].data.cid; });
    var nos = [], arestas = [], notas = [], fixos = {};
    ids.forEach(function (id) {
      var d = dados[id], nd = d.data;
      var posicao = { x: Math.round(d.pos_x), y: Math.round(d.pos_y) };
      if (nd.tipo === "nota") {
        notas.push({ id: nd.cid, texto: nd.texto || "", posicao: posicao, tamanho: tamanhoNota(nd.tamanho), cor: nd.cor || "amarela" });
        return;
      }
      nos.push({
        id: nd.cid, tipo: nd.tipo, titulo: nd.titulo, posicao: posicao,
        config: normalizarConfig(nd.tipo, nd.config), desativado: !!nd.desativado, executar_uma_vez: !!nd.executar_uma_vez,
        em_erro: nd.em_erro || "parar"
      });
      if (Array.isArray(nd.fixos) && nd.fixos.length) fixos[nd.cid] = clonar(nd.fixos);
      Object.keys(d.outputs || {}).forEach(function (saida) {
        d.outputs[saida].connections.forEach(function (conexao) {
          arestas.push({
            de: nd.cid, saida: Number(saida.replace("output_", "")) - 1,
            para: cid[conexao.node], entrada: Number(String(conexao.output).replace("input_", "")) - 1
          });
        });
      });
    });
    arestas.sort(function (a, b) {
      return a.de < b.de ? -1 : a.de > b.de ? 1 : a.saida - b.saida || (a.para < b.para ? -1 : a.para > b.para ? 1 : a.entrada - b.entrada);
    });
    return { versao: 2, nos: nos, arestas: arestas, notas: notas, dados_fixos: fixos };
  }

  /* v1 -> v2 (MV2-03). Grafo já v2 passa por um preenchimento de padrões. */
  function trocarAnterior(valor) {
    if (typeof valor === "string") return valor.replace(/\{\{\s*anterior\.([^}]*?)\s*\}\}/g, "{{ $json.$1 }}");
    if (Array.isArray(valor)) return valor.map(trocarAnterior);
    if (valor && typeof valor === "object") {
      var saida = {};
      Object.keys(valor).forEach(function (k) { saida[k] = trocarAnterior(valor[k]); });
      return saida;
    }
    return valor;
  }
  function migrar(grafo) {
    var g = clonar(grafo || {});
    var v1 = !g.versao || g.versao < 2;
    var base = { versao: 2, nos: [], arestas: [], notas: g.notas || [], dados_fixos: g.dados_fixos || {} };
    (g.nos || []).forEach(function (no) {
      var config = clonar(no.config || {});
      if (v1 && no.tipo === "http") {
        var corpo = typeof config.corpo === "string" ? { tipo: config.corpo ? "json" : "nenhum", conteudo: config.corpo } : config.corpo;
        config = Object.assign(configPadrao("http"), config, { corpo: corpo || { tipo: "nenhum", conteudo: "" }, resposta_completa: true });
      }
      if (v1) config = trocarAnterior(config);
      base.nos.push({
        id: no.id, tipo: no.tipo, titulo: no.titulo, posicao: no.posicao || { x: 0, y: 0 }, config: config,
        desativado: !!no.desativado, executar_uma_vez: !!no.executar_uma_vez, em_erro: no.em_erro || "parar",
        fixos: (base.dados_fixos || {})[no.id]
      });
    });
    (g.arestas || []).forEach(function (a) {
      base.arestas.push({ de: a.de, saida: a.saida || 0, para: a.para, entrada: a.entrada || 0 });
    });
    return base;
  }

  /* Nós que alimentam `cid` (para a lista de variáveis do inspector), do mais próximo ao mais distante. */
  function anteriores(grafo, cid) {
    var porPara = {}, ordem = [], visto = {};
    grafo.arestas.forEach(function (a) { (porPara[a.para] = porPara[a.para] || []).push(a.de); });
    var fila = (porPara[cid] || []).slice();
    while (fila.length) {
      var id = fila.shift();
      if (visto[id] || id === cid) continue;
      visto[id] = true; ordem.push(id);
      (porPara[id] || []).forEach(function (p) { fila.push(p); });
    }
    var titulos = {};
    grafo.nos.forEach(function (n) { titulos[n.id] = n.titulo; });
    return ordem.map(function (id) { return { id: id, titulo: titulos[id] }; }).filter(function (x) { return x.titulo; });
  }

  var API = {
    GRUPOS: GRUPOS, TIPOS: TIPOS, ORDEM_TIPOS: ORDEM_TIPOS, METODOS: METODOS, CORES_NOTA: CORES_NOTA, EM_ERRO: EM_ERRO,
    LIMITE_REGRAS: LIMITE_REGRAS, normalizarPaginacao: normalizarPaginacao, clonar: clonar, tipoDe: tipoDe, configPadrao: configPadrao, condicaoPadrao: condicaoPadrao,
    portas: portas, novoId: novoId, tituloUnico: tituloUnico, resumo: resumo, extrair: extrair, especificacao: especificacao,
    especificacaoNota: especificacaoNota, tamanhoNota: tamanhoNota, migrar: migrar, anteriores: anteriores, dadosDoNo: dadosDoNo
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  else raiz.ConversorGrafo = API;
})(typeof window !== "undefined" ? window : this);
