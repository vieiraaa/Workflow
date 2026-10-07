// Teste do conversor com Node (sem dependências): node tests/unit/frontend/conversor.test.js
const assert = require("assert");
const C = require("../../../static/js/canvas/conversor.js");

const grafo = {
  versao: 1,
  nos: [
    { id: "n1", tipo: "gatilho", titulo: "Início", posicao: { x: 80, y: 120 }, config: {} },
    { id: "n2", tipo: "http", titulo: "Buscar", posicao: { x: 360, y: 120 },
      config: { metodo: "GET", url: "https://api.exemplo.test/x", headers: [{ nome: "A", valor: "b" }], query: [], corpo: "" } },
    { id: "n3", tipo: "saida", titulo: "Resultado", posicao: { x: 640, y: 120 }, config: {} }
  ],
  arestas: [{ de: "n1", para: "n2" }, { de: "n2", para: "n3" }]
};

// Simula o export do Drawflow a partir do grafo.
const data = {};
grafo.nos.forEach((no, i) => {
  const e = C.especificacao(no);
  data[i + 1] = { id: i + 1, pos_x: e.x, pos_y: e.y, data: e.data, inputs: {}, outputs: e.saidas ? { output_1: { connections: [] } } : {} };
});
data[1].outputs.output_1.connections.push({ node: "2", output: "input_1" });
data[2].outputs.output_1.connections.push({ node: "3", output: "input_1" });

assert.deepStrictEqual(C.extrair({ drawflow: { Home: { data } } }), grafo);
assert.strictEqual(C.novoId(["n1", "n2"]), "n3");
assert.strictEqual(C.novoId(["n2", "n3"]), "n4");
assert.strictEqual(C.resumo(grafo.nos[1]), "GET https://api.exemplo.test/x");
console.log("ok");
