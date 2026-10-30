// Aprovações (D-048): selecionar todos, contagem da seleção e ações só com algo marcado.
// Só UX: o servidor valida tudo (itens sem número válido nunca são aprovados).
(function () {
  "use strict";
  var form = document.querySelector("[data-aprovacoes]");
  if (!form) return;
  var todos = form.querySelector("[data-aprovacoes-todos]");
  var itens = Array.prototype.slice.call(form.querySelectorAll("[data-aprovacoes-item]"));
  var acoes = form.querySelectorAll("[data-aprovacoes-acao]");
  var contagem = form.querySelector("[data-aprovacoes-contagem]");
  if (!itens.length) return;

  function atualizar() {
    var marcados = itens.filter(function (c) { return c.checked; });
    var invalidos = marcados.filter(function (c) { return c.hasAttribute("data-so-descartar"); });
    Array.prototype.forEach.call(acoes, function (b) { b.disabled = marcados.length === 0; });
    if (todos) {
      todos.checked = marcados.length === itens.length;
      todos.indeterminate = marcados.length > 0 && marcados.length < itens.length;
    }
    if (!contagem) return;
    if (!marcados.length) {
      contagem.textContent = "Selecione os itens para aprovar ou descartar.";
      return;
    }
    var texto = marcados.length + (marcados.length === 1 ? " item selecionado" : " itens selecionados");
    if (invalidos.length) {
      texto += " · " + invalidos.length + " sem número válido (só pode" + (invalidos.length === 1 ? "" : "m") + " ser descartado" + (invalidos.length === 1 ? ")" : "s)");
    }
    contagem.textContent = texto + ".";
  }

  if (todos) {
    todos.addEventListener("change", function () {
      itens.forEach(function (c) { c.checked = todos.checked; });
      atualizar();
    });
  }
  itens.forEach(function (c) { c.addEventListener("change", atualizar); });
  atualizar();
})();
