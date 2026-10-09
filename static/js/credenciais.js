/* Formulário de credencial: mostra só os campos do tipo escolhido. A validação é do servidor. */
(function () {
  "use strict";
  var form = document.querySelector("[data-form-credencial]");
  if (!form) return;
  var tipo = form.querySelector("[name=tipo]");
  var blocos = form.querySelectorAll("[data-tipos]");
  function aplicar() {
    var atual = tipo ? tipo.value : "";
    blocos.forEach(function (b) { b.hidden = b.dataset.tipos.split(" ").indexOf(atual) < 0; });
  }
  if (tipo) tipo.addEventListener("change", aplicar);
  aplicar();
})();
