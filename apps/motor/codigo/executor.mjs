// Runner do nó Código (SEG-17). Lê UM JSON do stdin, escreve UM JSON no stdout.
// Roda com `node --permission` (sem --allow-*), env vazio, --max-old-space-size.
// Defesa em camadas: (1) permission model bloqueia fs/child_process/worker/addon/wasi;
// (2) o código do usuário roda num contexto `vm` NOVO que não recebe nenhum objeto do host
// (API e console são construídos DENTRO do contexto a partir de texto; dados entram como JSON),
// logo não há cadeia `.constructor` que leve ao Function/process do host; (3) o host remove
// fetch/WebSocket etc. antes de executar; (4) vm.timeout limita CPU síncrona.
import vm from "node:vm";
import { readFileSync } from "node:fs";

const entrada = JSON.parse(readFileSync(0, "utf8"));
const { codigo, modo, itens, nos, contexto, timeoutMs } = entrada;

for (const nome of ["fetch", "WebSocket", "EventSource", "XMLHttpRequest", "Request", "Response", "Headers", "FormData", "BroadcastChannel", "MessageChannel", "Worker"]) {
  try { delete globalThis[nome]; } catch { /* ignora */ }
}

const PRELUDIO = `
"use strict";
delete globalThis.WebAssembly;
(function () {
  const __dados = JSON.parse(__JSON__);
  const __linhas = [];
  const __fmt = (a) => { try { return typeof a === "string" ? a : JSON.stringify(a); } catch (e) { return String(a); } };
  const console = {};
  for (const n of ["log", "info", "warn", "error", "debug"]) {
    console[n] = (...a) => { if (__linhas.length < 200) __linhas.push(a.map(__fmt).join(" ").slice(0, 2000)); };
  }
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const lista = (l) => l.map((x) => ({ json: clone(x.json) }));
  const par = (l) => ({
    all: () => lista(l), first: () => (l.length ? lista(l)[0] : undefined), last: () => (l.length ? lista(l)[l.length - 1] : undefined),
  });
  const $input = { ...par(__dados.itens), item: undefined };
  const $ = (titulo) => {
    const l = __dados.nos[titulo];
    if (!l) throw new Error("Nó '" + titulo + "' não encontrado ou ainda não executado.");
    return { ...par(l), item: l[__dados.indice] ? { json: clone(l[__dados.indice].json) } : undefined };
  };
  const $now = new Date(__dados.contexto.agora);
  const $today = new Date(Date.UTC(...(() => { const d = new Date(__dados.contexto.agora); return [d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()]; })()));
  const $execution = Object.freeze({ id: __dados.contexto.execucao_id });
  const $workflow = Object.freeze({ name: __dados.contexto.fluxo_nome });
  const $parametros = Object.freeze(clone(__dados.contexto.parametros || {}));
  const executar = (indice) => {
    __dados.indice = indice;
    const item = __dados.itens[indice];
    const $json = item ? clone(item.json) : undefined;
    const items = lista(__dados.itens);
    $input.item = item ? { json: clone(item.json) } : undefined;
    // eslint-disable-next-line no-new-func
    return (function ($input, $, $json, items, $now, $today, $execution, $workflow, $parametros, console) {
      return (function () {
        __CODIGO__
      }).call(undefined);
    })($input, $, $json, items, $now, $today, $execution, $workflow, $parametros, console);
  };
  const normalizar = (r) => {
    if (r === undefined || r === null) throw new Error("O código deve devolver (return) um array ou um objeto.");
    if (typeof r.then === "function") throw new Error("Código assíncrono (Promise/await/import) não é suportado.");
    const l = Array.isArray(r) ? r : [r];
    return l.map((x) => {
      if (x === null || typeof x !== "object" || Array.isArray(x)) throw new Error("O código deve devolver objetos ou {json: ...}.");
      if (Object.prototype.hasOwnProperty.call(x, "json")) {
        if (x.json === null || typeof x.json !== "object" || Array.isArray(x.json)) throw new Error("O campo json de cada item deve ser um objeto.");
        return clone({ json: x.json });
      }
      return clone({ json: x });
    });
  };
  if (__dados.modo === "uma_vez_por_item") {
    const porItem = [];
    for (let i = 0; i < __dados.itens.length; i++) {
      try {
        porItem.push({ itens: normalizar(executar(i)) });
      } catch (e) {
        porItem.push({ erro: String((e && e.message) || e).slice(0, 500) });
      }
    }
    return JSON.stringify({ por_item: porItem, logs: __linhas });
  }
  return JSON.stringify({ itens: normalizar(executar(0)), logs: __linhas });
})()
`;

function falhar(categoria, mensagem) {
  process.stdout.write(JSON.stringify({ erro: { categoria, mensagem } }));
  process.exit(0);
}

let fonte;
{
  // O código do usuário entra por substituição de texto no contexto isolado; o JSON de dados vai
  // como literal de string para não ser interpretado como código.
  const jsonLiteral = JSON.stringify(JSON.stringify({ itens, nos, contexto, modo, indice: 0 }));
  fonte = PRELUDIO.replace("__JSON__", () => jsonLiteral).replace("__CODIGO__", () => codigo);
}

let resultado;
try {
  const ctx = vm.createContext(Object.create(null), {
    codeGeneration: { strings: false, wasm: false },
  });
  resultado = vm.runInContext(fonte, ctx, { timeout: timeoutMs || 5000, filename: "codigo.js" });
} catch (e) {
  const msg = e && typeof e.message === "string" ? e.message : "erro de execução";
  if (/timed out/i.test(msg)) falhar("codigo_limite", "O código excedeu o tempo limite de CPU.");
  falhar("codigo", String(msg).slice(0, 500));
}
if (typeof resultado !== "string") falhar("codigo", "Retorno inválido.");
process.stdout.write(resultado);
