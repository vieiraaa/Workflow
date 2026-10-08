/* Conversor Drawflow <-> grafo canônico (docs/spec/grafo.yaml). Funções puras, sem DOM.
   Cada nó do Drawflow guarda em `data`: {cid, tipo, titulo, config}. */
(function (raiz) {
  "use strict";

  var TIPOS = {
    gatilho: { rotulo: "Gatilho manual", icone: "zap", entradas: 0, saidas: 1, titulo: "Início" },
    http: { rotulo: "Requisição HTTP", icone: "globe", entradas: 1, saidas: 1, titulo: "Requisição HTTP" },
    saida: { rotulo: "Saída", icone: "flag", entradas: 1, saidas: 0, titulo: "Resultado" }
  };
  var METODOS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

  function clonar(valor) { return JSON.parse(JSON.stringify(valor)); }

  function configPadrao(tipo) {
    if (tipo === "http") return { metodo: "GET", url: "", headers: [], query: [], corpo: "" };
    return {};
  }

  function novoId(ids) {
    var usados = {};
    ids.forEach(function (id) { usados[id] = true; });
    var n = ids.length + 1;
    while (usados["n" + n]) n += 1;
    return "n" + n;
  }

  function resumo(no) {
    if (no.tipo === "http") {
      var c = no.config || {};
      var url = c.url || "";
      return url ? (c.metodo || "GET") + " " + url : "Configure a URL";
    }
    return no.tipo === "gatilho" ? "Início manual" : "Mostra o resultado";
  }

  /* Drawflow.export() -> grafo canônico. */
  function extrair(exportado) {
    var dados = exportado.drawflow.Home.data;
    var ids = Object.keys(dados).sort(function (a, b) { return Number(a) - Number(b); });
    var cid = {};
    ids.forEach(function (id) { cid[id] = dados[id].data.cid; });
    var nos = [], arestas = [];
    ids.forEach(function (id) {
      var d = dados[id], nd = d.data;
      nos.push({
        id: nd.cid, tipo: nd.tipo, titulo: nd.titulo,
        posicao: { x: Math.round(d.pos_x), y: Math.round(d.pos_y) },
        config: clonar(nd.config || {})
      });
      Object.keys(d.outputs || {}).forEach(function (saida) {
        d.outputs[saida].connections.forEach(function (conexao) {
          arestas.push({ de: nd.cid, para: cid[conexao.node] });
        });
      });
    });
    return { versao: 1, nos: nos, arestas: arestas };
  }

  /* Nó canônico -> especificação para Drawflow.addNode. */
  function especificacao(no) {
    var tipo = TIPOS[no.tipo];
    return {
      nome: no.tipo, entradas: tipo.entradas, saidas: tipo.saidas,
      x: (no.posicao && no.posicao.x) || 0, y: (no.posicao && no.posicao.y) || 0,
      data: { cid: no.id, tipo: no.tipo, titulo: no.titulo, config: clonar(no.config || {}) }
    };
  }

  var API = { TIPOS: TIPOS, METODOS: METODOS, clonar: clonar, configPadrao: configPadrao, novoId: novoId, resumo: resumo, extrair: extrair, especificacao: especificacao };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  else raiz.ConversorGrafo = API;
})(typeof window !== "undefined" ? window : this);
