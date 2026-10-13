// Teste do conversor v2 com Node (sem dependências): node tests/unit/frontend/conversor.test.js
const assert = require("assert");
const C = require("../../../static/js/canvas/conversor.js");
const E = require("../../../static/js/canvas/esquemas.js");
const X = require("../../../static/js/canvas/expressao.js");

const grafo = {
  versao: 2,
  nos: [
    { id: "n1", tipo: "gatilho", titulo: "Início", posicao: { x: 80, y: 120 }, config: {}, desativado: false, executar_uma_vez: false, em_erro: "parar" },
    { id: "n2", tipo: "se", titulo: "É grande?", posicao: { x: 360, y: 120 },
      config: { condicoes: [{ esquerda: "{{ $json.n }}", operador: "maior", direita: "10", tipo: "numero" }], combinar: "e" },
      desativado: false, executar_uma_vez: false, em_erro: "parar" },
    { id: "n3", tipo: "http", titulo: "Buscar", posicao: { x: 640, y: 40 },
      config: C.configPadrao("http"), desativado: true, executar_uma_vez: true, em_erro: "saida_de_erro" },
    { id: "n4", tipo: "saida", titulo: "Resultado", posicao: { x: 640, y: 220 }, config: {}, desativado: false, executar_uma_vez: false, em_erro: "parar" }
  ],
  arestas: [
    { de: "n1", saida: 0, para: "n2", entrada: 0 },
    { de: "n2", saida: 0, para: "n3", entrada: 0 },
    { de: "n2", saida: 1, para: "n4", entrada: 0 }
  ],
  notas: [{ id: "n5", texto: "Lembrete", posicao: { x: 20, y: 300 }, tamanho: { l: 240, a: 140 }, cor: "azul" }],
  dados_fixos: { n1: [{ json: { n: 12 } }] }
};

// Simula o export do Drawflow a partir do grafo (portas, ramos e nota).
const data = {};
const dfId = {};
function adicionar(spec, i) {
  dfId[spec.data.cid] = String(i);
  const outs = {}, ins = {};
  for (let k = 1; k <= spec.saidas; k += 1) outs["output_" + k] = { connections: [] };
  for (let k = 1; k <= spec.entradas; k += 1) ins["input_" + k] = { connections: [] };
  data[i] = { id: i, pos_x: spec.x, pos_y: spec.y, data: spec.data, inputs: ins, outputs: outs };
}
let i = 1;
grafo.nos.forEach((no) => {
  const n = Object.assign({}, no, { fixos: grafo.dados_fixos[no.id] });
  adicionar(C.especificacao(n), i++);
});
grafo.notas.forEach((n) => adicionar(C.especificacaoNota(n), i++));
grafo.arestas.forEach((a) => data[dfId[a.de]].outputs["output_" + (a.saida + 1)].connections.push({ node: dfId[a.para], output: "input_" + (a.entrada + 1) }));

assert.deepStrictEqual(C.extrair({ drawflow: { Home: { data } } }), grafo);
assert.strictEqual(C.lerFixos(data[1].data).length, 1);

// Portas (EDV-01)
assert.deepStrictEqual(C.portas("se", {}, "parar").saidas, ["verdadeiro", "falso"]);
assert.deepStrictEqual(C.portas("repetir_em_lotes", {}, "parar").saidas, ["loop", "pronto"]);
assert.deepStrictEqual(C.portas("escolher", { regras: [{}, {}, {}], saida_outros: true }, "parar").saidas, ["regra 1", "regra 2", "regra 3", "outros"]);
assert.deepStrictEqual(C.portas("http", {}, "saida_de_erro").saidas, ["", "erro"]);
assert.deepStrictEqual(C.portas("filtrar", { manter_descartados: true }, "parar").saidas, ["passou", "descartados"]);
assert.strictEqual(C.portas("juntar", { entradas: 3 }, "parar").entradas.length, 3);
assert.strictEqual(C.portas("gatilho", {}, "parar").entradas.length, 0);
assert.strictEqual(C.portas("saida", {}, "parar").saidas.length, 0);

// Catálogo: todo tipo tem grupo, ícone, config padrão e esquema de formulário
C.ORDEM_TIPOS.forEach((t) => {
  assert.ok(C.TIPOS[t].grupo && C.TIPOS[t].icone && C.TIPOS[t].rotulo, t);
  assert.ok(typeof C.configPadrao(t) === "object", t);
  assert.ok(E.esquema(t).length > 0, "sem formulário: " + t);
  assert.ok(typeof C.resumo({ tipo: t, config: C.configPadrao(t) }) === "string", t);
});
assert.strictEqual(C.ORDEM_TIPOS.length, 19);

// Paginação (MV2-16): formato plano, só as chaves do modo
assert.deepStrictEqual(C.normalizarPaginacao({ modo: "atualizar_parametro", onde: "query", nome: "page", valor: "{{ $pageCount }}", url: "x", parar_quando: "status", codigos: [404], expressao: "y", limite_paginas: 5, intervalo_ms: 0 }),
  { modo: "atualizar_parametro", parar_quando: "status", limite_paginas: 5, intervalo_ms: 0, onde: "query", nome: "page", valor: "{{ $pageCount }}", codigos: [404] });
assert.strictEqual(C.normalizarPaginacao(null), null);

// Ids e títulos
assert.strictEqual(C.novoId(["n1", "n2"]), "n3");
assert.strictEqual(C.novoId(["n2", "n3"]), "n4");
assert.strictEqual(C.tituloUnico("Se", ["Se", "Se 2"]), "Se 3");
assert.strictEqual(C.tituloUnico("Se", ["Outro"]), "Se");
assert.strictEqual(C.resumo(grafo.nos[2]), "Configure a URL");

// Migração v1 -> v2 (MV2-03, MV2-12 L1)
const v1 = { versao: 1, nos: [
  { id: "n1", tipo: "gatilho", titulo: "Início", posicao: { x: 0, y: 0 }, config: {} },
  { id: "n2", tipo: "http", titulo: "Buscar", posicao: { x: 300, y: 0 }, config: { metodo: "GET", url: "https://x.test/{{ anterior.id }}", headers: [], query: [], corpo: "" } },
  { id: "n3", tipo: "saida", titulo: "Resultado", posicao: { x: 600, y: 0 }, config: {} }],
  arestas: [{ de: "n1", para: "n2" }, { de: "n2", para: "n3" }] };
const m = C.migrar(v1);
assert.strictEqual(m.versao, 2);
assert.deepStrictEqual(m.arestas[0], { de: "n1", saida: 0, para: "n2", entrada: 0 });
assert.strictEqual(m.nos[1].config.url, "https://x.test/{{ $json.id }}");
assert.strictEqual(m.nos[1].config.resposta_completa, true);
assert.strictEqual(m.nos[1].em_erro, "parar");
assert.deepStrictEqual(m.notas, []);

// Variáveis anteriores
assert.deepStrictEqual(C.anteriores(grafo, "n3").map((x) => x.titulo), ["É grande?", "Início"]);

// Esquemas: caminho com ponto
const cfg = { corpo: { tipo: "json" } };
assert.strictEqual(E.valorEm(cfg, "corpo.tipo"), "json");
E.definirEm(cfg, "paginacao.limite", 3);
assert.strictEqual(cfg.paginacao.limite, 3);
assert.ok(E.unario("vazio") && !E.unario("igual"));

// Destaque de expressão
const tipos = X.destacar("Olá {{ $json.nome + 3 + 'x' }}").map((p) => p.tipo);
assert.ok(tipos.includes("chave") && tipos.includes("variavel") && tipos.includes("numero") && tipos.includes("literal"));
assert.strictEqual(X.destacar("a {{ b").map((p) => p.t).join(""), "a {{ b");
assert.strictEqual(X.ehExpressao("x"), false);
assert.strictEqual(X.ehExpressao("={{ 1 }}"), true);
console.log("ok");
