/* JS fino: tema, toasts, modal, menu mobile, copiar. Validação é do servidor. */
(function () {
  "use strict";
  var raiz = document.documentElement;

  function salvarTema(tema) {
    raiz.setAttribute("data-theme", tema);
    try { localStorage.setItem("tema", tema); } catch (e) {}
  }

  /* Prepara o modal a partir de data-* do botão: data-form-action, data-valor-<campo>,
     data-texto-<slot>. Tudo por value/textContent. Erros do servidor somem ao reabrir. */
  function prepararModal(modal, botao) {
    var form = modal.querySelector("form");
    modal.querySelectorAll(".campo__erro").forEach(function (e) { e.remove(); });
    modal.querySelectorAll(".campo--erro").forEach(function (e) { e.classList.remove("campo--erro"); });
    Object.keys(botao.dataset).forEach(function (chave) {
      var valor = botao.dataset[chave], nome;
      if (chave === "formAction" && form) form.setAttribute("action", valor);
      else if (chave.indexOf("valor") === 0) {
        nome = chave.slice(5).toLowerCase();
        var campo = modal.querySelector("[name=" + nome + "]");
        if (campo) campo.value = valor;
      } else if (chave.indexOf("texto") === 0) {
        nome = chave.slice(5).toLowerCase();
        var slot = modal.querySelector("[data-slot=" + nome + "]");
        if (slot) slot.textContent = valor;
      }
    });
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
      alvo.setAttribute("aria-label", aberto ? "Fechar menu" : "Abrir menu");
    } else if (alvo.hasAttribute("data-menu-fechar") && shell) {
      shell.classList.remove("menu-aberto");
    } else if (alvo.hasAttribute("data-modal-abrir")) {
      var modal = document.getElementById(alvo.getAttribute("data-modal-abrir"));
      if (modal && modal.showModal) { prepararModal(modal, alvo); modal.showModal(); }
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

  /* Modal aberto pelo servidor (erro de formulário). */
  document.querySelectorAll("dialog[data-abrir]").forEach(function (m) { if (m.showModal) m.showModal(); });

  /* Toasts somem sozinhos (erros ficam até serem fechados). */
  document.querySelectorAll("[data-toast]:not(.toast--error)").forEach(function (t) {
    setTimeout(function () { t.remove(); }, 5000);
  });

  /* Toast criado por JS (mesmo markup de componentes/toast.html; texto sempre por textContent). */
  var ICONES = { success: "circle-check", error: "circle-alert", warning: "triangle-alert", info: "info" };
  function svg(nome, tamanho) {
    var area = document.querySelector("[data-toasts]");
    var s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("class", "icone icone--" + tamanho); s.setAttribute("aria-hidden", "true");
    var u = document.createElementNS("http://www.w3.org/2000/svg", "use");
    u.setAttribute("href", (area ? area.getAttribute("data-sprite") : "") + "#" + nome);
    s.appendChild(u);
    return s;
  }
  window.mostrarToast = function (tag, texto) {
    var area = document.querySelector("[data-toasts]");
    if (!area) return;
    var t = document.createElement("div");
    t.className = "toast toast--" + tag; t.setAttribute("role", tag === "error" ? "alert" : "status");
    t.setAttribute("data-toast", "");
    var msg = document.createElement("span"); msg.className = "toast__texto"; msg.textContent = texto;
    var fechar = document.createElement("button");
    fechar.className = "botao botao--icone"; fechar.type = "button";
    fechar.setAttribute("data-toast-fechar", ""); fechar.setAttribute("aria-label", "Fechar");
    fechar.appendChild(svg("x", 16));
    t.appendChild(svg(ICONES[tag] || "info", 20)); t.appendChild(msg); t.appendChild(fechar);
    area.appendChild(t);
    if (tag !== "error") setTimeout(function () { t.remove(); }, 5000);
  };

  /* Botão de envio ([data-carregando]) mostra "carregando" e bloqueia duplo envio do formulário. */
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (ev.defaultPrevented) return;
    if (form.dataset.enviando === "true") { ev.preventDefault(); return; }
    var btn = form.querySelector("[type=submit][data-carregando]");
    if (!btn) return;
    form.dataset.enviando = "true";
    btn.setAttribute("aria-busy", "true");
    var texto = btn.getAttribute("data-texto-carregando");
    if (texto) {
      btn.replaceChildren(svg("loader-circle", 16), document.createTextNode(texto));
      btn.firstChild.setAttribute("class", "icone icone--16 icone--gira");
    }
  });

  /* Voltar pelo histórico do navegador não deve deixar formulário travado. */
  window.addEventListener("pageshow", function (ev) {
    if (!ev.persisted) return;
    document.querySelectorAll("form[data-enviando]").forEach(function (f) {
      delete f.dataset.enviando;
      f.querySelectorAll("[aria-busy]").forEach(function (b) { b.removeAttribute("aria-busy"); });
    });
  });
  /* Linha de tabela clicável: <tr data-href>. O nome continua sendo um <a> (teclado, Cmd/Ctrl+clique).
     Ignora links/botões/campos internos, clique que não é o principal e seleção de texto. */
  document.addEventListener("click", function (ev) {
    var linha = ev.target.closest && ev.target.closest("tr[data-href]");
    if (!linha || ev.defaultPrevented || ev.button !== 0) return;
    if (ev.target.closest("a, button, input, select, textarea, label, summary, [role=button]")) return;
    var sel = window.getSelection && window.getSelection();
    if (sel && String(sel).length > 0) return;
    var href = linha.getAttribute("data-href");
    if (!href || href.charAt(0) !== "/") return;
    if (ev.metaKey || ev.ctrlKey) window.open(href, "_blank", "noopener");
    else window.location.assign(href);
  });
})();
