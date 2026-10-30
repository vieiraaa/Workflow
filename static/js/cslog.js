// CSLOG (D-064): selecionar todos, contagem da seleção, botão só com algo marcado e download
// automático do arquivo recém-gerado. Só UX: o servidor valida tudo.
(function () {
  "use strict";
  var baixar = document.querySelector("[data-cslog-baixar]");
  if (baixar) window.location.assign(baixar.getAttribute("href"));

  var form = document.querySelector("[data-cslog]");
  if (!form) return;
  var todos = form.querySelector("[data-cslog-todos]");
  var itens = Array.prototype.slice.call(form.querySelectorAll("[data-cslog-item]"));
  var acao = form.querySelector("[data-cslog-acao]");
  var contagem = form.querySelector("[data-cslog-contagem]");

  function atualizar() {
    var n = itens.filter(function (c) { return c.checked; }).length;
    if (acao) acao.disabled = n === 0;
    if (todos) {
      todos.checked = itens.length > 0 && n === itens.length;
      todos.indeterminate = n > 0 && n < itens.length;
      todos.disabled = itens.length === 0;
    }
    if (contagem) {
      contagem.textContent = n
        ? n + (n === 1 ? " processo selecionado." : " processos selecionados.")
        : "Marque os processos que vão para o CSLOG.";
    }
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
