/* JS fino: tema, toasts, modal, menu mobile, copiar. Validação é do servidor. */
(function () {
  "use strict";
  var raiz = document.documentElement;

  function salvarTema(tema) {
    raiz.setAttribute("data-theme", tema);
    try { localStorage.setItem("tema", tema); } catch (e) {}
  }

  document.addEventListener("click", function (ev) {
    var alvo = ev.target.closest("[data-tema-alternar],[data-menu-alternar],[data-menu-fechar],[data-modal-abrir],[data-modal-fechar],[data-toast-fechar],[data-copiar]");
    if (!alvo) return;
    var shell = document.querySelector("[data-shell]");

    if (alvo.hasAttribute("data-tema-alternar")) {
      salvarTema(raiz.getAttribute("data-theme") === "dark" ? "light" : "dark");
    } else if (alvo.hasAttribute("data-menu-alternar") && shell) {
      var aberto = shell.classList.toggle("menu-aberto");
      alvo.setAttribute("aria-expanded", aberto ? "true" : "false");
    } else if (alvo.hasAttribute("data-menu-fechar") && shell) {
      shell.classList.remove("menu-aberto");
    } else if (alvo.hasAttribute("data-modal-abrir")) {
      var modal = document.getElementById(alvo.getAttribute("data-modal-abrir"));
      if (modal && modal.showModal) modal.showModal();
    } else if (alvo.hasAttribute("data-modal-fechar")) {
      var dlg = alvo.closest("dialog");
      if (dlg) dlg.close();
    } else if (alvo.hasAttribute("data-toast-fechar")) {
      var t = alvo.closest("[data-toast]");
      if (t) t.remove();
    } else if (alvo.hasAttribute("data-copiar")) {
      var codigo = alvo.parentElement.querySelector("code");
      if (codigo && navigator.clipboard) navigator.clipboard.writeText(codigo.textContent);
    }
  });

  /* Clique no fundo fecha o modal. */
  document.addEventListener("click", function (ev) {
    if (ev.target.tagName === "DIALOG" && ev.target.open) ev.target.close();
  });

  /* Toasts somem sozinhos (erros ficam até serem fechados). */
  document.querySelectorAll("[data-toast]:not(.toast--error)").forEach(function (t) {
    setTimeout(function () { t.remove(); }, 5000);
  });

  /* Botão de envio mostra estado "carregando" e evita duplo envio. */
  document.addEventListener("submit", function (ev) {
    var btn = ev.target.querySelector("[type=submit][data-carregando]");
    if (btn) btn.setAttribute("aria-busy", "true");
  });
})();
