/* Formulários do inspector por tipo de nó (NOV-02..06). Dados puros, sem DOM: o inspector.js os renderiza.
   Campo: {k: tipo de controle, c: caminho na config ("corpo.tipo"), rotulo, ...}. `quando(config)` esconde o campo.
   `recarrega: true` remonta o formulário quando o valor muda (campos que mostram/escondem outros). */
(function (raiz) {
  "use strict";

  var OPERADORES = [
    ["igual", "é igual a"], ["diferente", "é diferente de"], ["maior", "é maior que"], ["maior_igual", "é maior ou igual a"],
    ["menor", "é menor que"], ["menor_igual", "é menor ou igual a"], ["contem", "contém"], ["nao_contem", "não contém"],
    ["comeca_com", "começa com"], ["termina_com", "termina com"], ["vazio", "está vazio"], ["nao_vazio", "não está vazio"],
    ["regex", "casa com regex"], ["existe", "existe"], ["nao_existe", "não existe"]
  ];
  var OPERADORES_UNARIOS = ["vazio", "nao_vazio", "existe", "nao_existe"];
  var TIPOS_VALOR = [["texto", "Texto"], ["numero", "Número"], ["data", "Data"], ["booleano", "Booleano"], ["lista", "Lista"], ["objeto", "Objeto"]];
  var TIPOS_CAMPO = [["texto", "Texto"], ["numero", "Número"], ["booleano", "Booleano"], ["lista", "Lista"], ["objeto", "Objeto"]];

  function sempre() { return true; }
  function eq(c, v) { return function (cfg) { return valorEm(cfg, c) === v; }; }

  function valorEm(obj, caminho) {
    return String(caminho).split(".").reduce(function (o, k) { return o == null ? undefined : o[k]; }, obj);
  }
  function definirEm(obj, caminho, valor) {
    var partes = String(caminho).split("."), alvo = obj;
    partes.slice(0, -1).forEach(function (k) {
      if (alvo[k] == null || typeof alvo[k] !== "object") alvo[k] = {};
      alvo = alvo[k];
    });
    alvo[partes[partes.length - 1]] = valor;
    return obj;
  }

  /* Corpo do HTTP: "formulario" guarda lista [{nome, valor}]; os outros tipos guardam texto (MV2-18). */
  function ajustarCorpo(config, tipo) {
    var c = config.corpo || (config.corpo = { tipo: tipo, conteudo: "" });
    if (tipo === "formulario" && !Array.isArray(c.conteudo)) c.conteudo = [];
    else if (tipo !== "formulario" && typeof c.conteudo !== "string") c.conteudo = "";
  }

  var ESQUEMAS = {
    gatilho: [{ k: "aviso", texto: "O gatilho manual inicia o fluxo com um item: quando foi disparado e por quem." }],
    saida: [{ k: "aviso", texto: "Mostra na tela o resultado dos itens que chegam aqui." }],
    sem_operacao: [{ k: "aviso", texto: "Repassa os itens sem alterar. Útil para organizar o desenho." }],
    http: [
      { k: "select", c: "metodo", rotulo: "Método", opcoes: [["GET", "GET"], ["POST", "POST"], ["PUT", "PUT"], ["PATCH", "PATCH"], ["DELETE", "DELETE"]] },
      { k: "expr", c: "url", rotulo: "URL", placeholder: "https://api.exemplo.com/recurso", max: 2048 },
      { k: "credencial", c: "credencial", rotulo: "Credencial" },
      { k: "pares", c: "query", rotulo: "Parâmetros de consulta" },
      { k: "pares", c: "headers", rotulo: "Cabeçalhos" },
      { k: "select", c: "corpo.tipo", rotulo: "Corpo", recarrega: true, aoMudar: ajustarCorpo, opcoes: [["nenhum", "Nenhum"], ["json", "JSON"], ["formulario", "Formulário"], ["texto", "Texto"]] },
      { k: "expr", c: "corpo.conteudo", rotulo: "Conteúdo do corpo", multilinha: true, mono: true, quando: function (c) { var t = valorEm(c, "corpo.tipo"); return t && t !== "nenhum" && t !== "formulario"; } },
      { k: "pares", c: "corpo.conteudo", rotulo: "Campos do formulário", quando: eq("corpo.tipo", "formulario") },
      { k: "select", c: "resposta", rotulo: "Formato da resposta", opcoes: [["automatica", "Automático"], ["json", "JSON"], ["texto", "Texto"]] },
      { k: "toggle", c: "resposta_completa", rotulo: "Resposta completa (status, cabeçalhos e corpo)", ajuda: "Desligado: o item é o corpo da resposta." },
      { k: "paginacao", c: "paginacao", rotulo: "Paginação" }
    ],
    chamar_n8n: [
      { k: "expr", c: "url", rotulo: "URL do webhook do n8n", placeholder: "https://n8n.exemplo.com/webhook/meu-fluxo", max: 2048 },
      { k: "alerta", texto: "URL de TESTE do n8n: só funciona enquanto o n8n estiver em “Listen for test event”. Para uso real, ative o fluxo no n8n e use /webhook/.",
        quando: function (c) { return String(c.url || "").indexOf("/webhook-test/") >= 0; } },
      { k: "select", c: "metodo", rotulo: "Método", opcoes: [["POST", "POST"], ["GET", "GET"]] },
      { k: "credencial", c: "credencial", rotulo: "Credencial" },
      { k: "select", c: "enviar", rotulo: "Enviar", recarrega: true, opcoes: [["item", "Um item por chamada"], ["todos", "Todos os itens numa chamada"], ["personalizado", "Corpo personalizado"]] },
      { k: "expr", c: "corpo", rotulo: "Corpo a enviar (objeto ou lista JSON)", multilinha: true, mono: true, placeholder: "{ \"id\": \"{{ $json.id }}\" }", quando: eq("enviar", "personalizado") },
      { k: "toggle", c: "aguardar_resposta", rotulo: "Aguardar a resposta do n8n", ajuda: "Desligado: o fluxo segue sem ler a resposta e cada item ganha o campo n8n_status." },
      { k: "numero", c: "tempo_limite_s", rotulo: "Tempo limite (1 a 55 segundos)", min: 1, max: 55 }
    ],
    codigo: [
      { k: "select", c: "modo", rotulo: "Modo", opcoes: [["uma_vez_para_todos", "Uma vez para todos os itens"], ["uma_vez_por_item", "Uma vez para cada item"]] },
      { k: "codigo", c: "codigo", rotulo: "JavaScript", max: 50000, ajuda: "Retorne uma lista de {json}. Use $input.all(), $json, $('Nó').all(). Roda isolado, sem rede e sem disco." }
    ],
    editar_campos: [
      { k: "select", c: "modo", rotulo: "Modo", recarrega: true, opcoes: [["manual", "Campo a campo"], ["json", "JSON"]] },
      { k: "tabela", c: "campos", rotulo: "Campos", quando: eq("modo", "manual"), max: 50, novo: { nome: "", valor: "", tipo: "texto" }, colunas: [
        { c: "nome", rotulo: "Nome (aceita a.b)", k: "texto" }, { c: "valor", rotulo: "Valor", k: "expr" }, { c: "tipo", rotulo: "Tipo", k: "select", opcoes: TIPOS_CAMPO }] },
      { k: "expr", c: "json", rotulo: "Objeto JSON", multilinha: true, mono: true, quando: eq("modo", "json") },
      { k: "toggle", c: "incluir_outros", rotulo: "Manter os outros campos do item" }
    ],
    filtrar: [
      { k: "condicoes", c: "", rotulo: "Condições" },
      { k: "toggle", c: "manter_descartados", rotulo: "Mostrar os descartados numa segunda saída", recarrega: true }
    ],
    se: [{ k: "condicoes", c: "", rotulo: "Condições" }, { k: "aviso", texto: "Saída 1: verdadeiro. Saída 2: falso." }],
    escolher: [
      { k: "regras", c: "regras", rotulo: "Regras", max: 10 },
      { k: "toggle", c: "saida_outros", rotulo: "Saída “outros” para o que não casou", recarrega: true }
    ],
    ordenar: [{ k: "tabela", c: "campos", rotulo: "Ordenar por", max: 10, novo: { campo: "", ordem: "asc" }, colunas: [
      { c: "campo", rotulo: "Campo", k: "texto" }, { c: "ordem", rotulo: "Ordem", k: "select", opcoes: [["asc", "Crescente"], ["desc", "Decrescente"]] }] }],
    limitar: [
      { k: "numero", c: "quantidade", rotulo: "Quantidade", min: 0 },
      { k: "select", c: "de", rotulo: "Manter os", opcoes: [["inicio", "Primeiros"], ["fim", "Últimos"]] }
    ],
    remover_duplicados: [
      { k: "select", c: "comparar", rotulo: "Comparar", recarrega: true, opcoes: [["todos", "Itens inteiros"], ["campos", "Só alguns campos"]] },
      { k: "lista", c: "campos", rotulo: "Campos", quando: eq("comparar", "campos"), placeholder: "campo ou a.b" }
    ],
    separar_lista: [
      { k: "texto", c: "campo", rotulo: "Campo com a lista", placeholder: "dados.itens" },
      { k: "select", c: "incluir", rotulo: "Incluir em cada item", opcoes: [["nada", "Só o elemento"], ["campos_pai", "Os campos do item original"]] }
    ],
    agregar: [
      { k: "select", c: "modo", rotulo: "Agregar", recarrega: true, opcoes: [["todos", "Os itens inteiros"], ["campos", "Só alguns campos"]] },
      { k: "lista", c: "campos", rotulo: "Campos", quando: eq("modo", "campos"), placeholder: "campo ou a.b" },
      { k: "texto", c: "saida", rotulo: "Nome do campo de saída", max: 80 }
    ],
    resumir: [
      { k: "lista", c: "agrupar_por", rotulo: "Agrupar por (opcional)", placeholder: "campo ou a.b" },
      { k: "tabela", c: "operacoes", rotulo: "Operações", max: 20, novo: { campo: "", op: "contar" }, colunas: [
        { c: "campo", rotulo: "Campo", k: "texto" },
        { c: "op", rotulo: "Operação", k: "select", opcoes: [["contar", "Contar"], ["contar_unicos", "Contar únicos"], ["somar", "Somar"], ["media", "Média"], ["min", "Mínimo"], ["max", "Máximo"], ["concatenar", "Concatenar"]] }] }
    ],
    data_hora: [
      { k: "select", c: "operacao", rotulo: "Operação", recarrega: true, opcoes: [["agora", "Data e hora de agora"], ["formatar", "Formatar"], ["somar", "Somar"], ["subtrair", "Subtrair"], ["diferenca", "Diferença"], ["inicio_de", "Início de"]] },
      { k: "expr", c: "campo", rotulo: "Data (expressão)", placeholder: "{{ $json.criado_em }}", quando: function (c) { return c.operacao !== "agora"; } },
      { k: "texto", c: "formato", rotulo: "Formato (yyyy MM dd HH mm ss)", quando: function (c) { return c.operacao === "formatar" || c.operacao === "agora"; } },
      { k: "numero", c: "quantidade", rotulo: "Quantidade", quando: function (c) { return c.operacao === "somar" || c.operacao === "subtrair"; } },
      { k: "select", c: "unidade", rotulo: "Unidade", opcoes: [["minutos", "Minutos"], ["horas", "Horas"], ["dias", "Dias"], ["semanas", "Semanas"], ["meses", "Meses"], ["anos", "Anos"]], quando: function (c) { return ["somar", "subtrair", "diferenca", "inicio_de"].indexOf(c.operacao) >= 0; } },
      { k: "texto", c: "saida", rotulo: "Nome do campo de saída", max: 80 }
    ],
    juntar: [
      { k: "select", c: "modo", rotulo: "Modo", recarrega: true, opcoes: [["anexar", "Anexar (uma entrada depois da outra)"], ["combinar_por_campo", "Combinar por campo"], ["combinar_por_posicao", "Combinar por posição"], ["escolher_entrada", "Escolher uma entrada"]] },
      { k: "numero", c: "entradas", rotulo: "Número de entradas", min: 2, max: 4, recarrega: true },
      { k: "texto", c: "campo1", rotulo: "Campo da entrada 1", quando: eq("modo", "combinar_por_campo") },
      { k: "texto", c: "campo2", rotulo: "Campo da entrada 2", quando: eq("modo", "combinar_por_campo") },
      { k: "select", c: "tipo", rotulo: "Itens mantidos", quando: eq("modo", "combinar_por_campo"), opcoes: [["dentro", "Só os que casam"], ["esquerda", "Todos da entrada 1"], ["direita", "Todos da entrada 2"], ["externa", "Todos"]] },
      { k: "numero", c: "entrada", rotulo: "Entrada escolhida", min: 1, max: 4, quando: eq("modo", "escolher_entrada") }
    ],
    repetir_em_lotes: [
      { k: "numero", c: "tamanho_lote", rotulo: "Itens por lote", min: 1 },
      { k: "aviso", texto: "Saída “loop”: o lote atual; ligue o fim do laço de volta à entrada deste nó. Saída “pronto”: todos os itens ao final." }
    ],
    parar_com_erro: [{ k: "expr", c: "mensagem", rotulo: "Mensagem de erro", multilinha: true, max: 500 }]
  };

  function esquema(tipo) { return ESQUEMAS[tipo] || []; }

  function unario(operador) { return OPERADORES_UNARIOS.indexOf(operador) >= 0; }

  var API = { ESQUEMAS: ESQUEMAS, OPERADORES: OPERADORES, TIPOS_VALOR: TIPOS_VALOR, esquema: esquema, ajustarCorpo: ajustarCorpo, unario: unario, valorEm: valorEm, definirEm: definirEm, sempre: sempre };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  else raiz.EsquemasNos = API;
})(typeof window !== "undefined" ? window : this);
