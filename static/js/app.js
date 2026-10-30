/* JS fino: tema, toasts, modal, menu mobile, copiar. Validação é do servidor. */
(function () {
  "use strict";
  var raiz = document.documentElement;

  function salvarTema(tema) {
    raiz.setAttribute("data-theme", tema);
    try { localStorage.setItem("tema", tema); } catch (e) {}
  }

  /* Troca de tema (D-040): um disco na cor de fundo do tema novo cresce a partir do botão (só
     transform), o tema troca por baixo dele e o disco se desfaz (só opacity). As duas animações
     rodam no compositor; o recálculo pesado da troca fica escondido. Movimento reduzido: na hora. */
  var trocandoTema = false;
  function alternarTema(botao) {
    var novo = raiz.getAttribute("data-theme") === "dark" ? "light" : "dark";
    var reduzido = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (trocandoTema) return;
    if (reduzido || !document.body.animate) { salvarTema(novo); return; }
    trocandoTema = true;
    var caixa = botao.getBoundingClientRect();
    var x = caixa.left + caixa.width / 2, y = caixa.top + caixa.height / 2;
    var raio = Math.ceil(Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y)));
    var disco = document.createElement("div");
    disco.className = "tema-disco";
    disco.style.left = x - raio + "px"; disco.style.top = y - raio + "px";
    disco.style.width = disco.style.height = 2 * raio + "px";
    disco.style.background = getComputedStyle(raiz).getPropertyValue("--tema-disco").trim();
    document.body.appendChild(disco);
    function fim() { disco.remove(); trocandoTema = false; }
    disco.animate([{ transform: "scale(0)" }, { transform: "scale(1)" }],
      { duration: 380, easing: "cubic-bezier(.4,0,.2,1)" }).finished
      .then(function () {
        salvarTema(novo);
        return disco.animate([{ opacity: 1 }, { opacity: 0 }],
          { duration: 260, easing: "ease-out", fill: "forwards" }).finished;
      })
      .then(fim, fim);
  }

  /* Easter egg (D-045): 5 cliques seguidos (menos de 1 s entre eles) no botão de tema abrem o vídeo
     em tela cheia; ao acabar, volta para a Home. Só existe data-easteregg para quem está na lista. */
  var cliquesDoTema = [];
  function contarCliqueDoEasteregg() {
    var video = document.body.getAttribute("data-easteregg");
    if (!video) return;
    var agora = Date.now();
    var ultimo = cliquesDoTema[cliquesDoTema.length - 1];
    if (ultimo === undefined || agora - ultimo > 1000) cliquesDoTema = [];  /* pausa: recomeça */
    cliquesDoTema.push(agora);
    if (cliquesDoTema.length >= 5) { cliquesDoTema = []; abrirEasteregg(video); }
  }

  function abrirEasteregg(src) {
    if (document.querySelector(".easteregg")) return;
    var tela = document.createElement("div");
    tela.className = "easteregg";
    tela.setAttribute("role", "dialog");
    tela.setAttribute("aria-label", "Surpresa");
    var video = document.createElement("video");
    video.src = src;
    video.playsInline = true;
    video.autoplay = true;
    tela.appendChild(video);
    document.body.appendChild(tela);
    function voltar() { location.href = document.body.getAttribute("data-inicio") || "/"; }
    function fechar(ev) { if (ev.key === "Escape") { document.removeEventListener("keydown", fechar); tela.remove(); } }
    video.addEventListener("ended", voltar);
    video.addEventListener("error", function () { tela.remove(); });
    document.addEventListener("keydown", fechar);
    var tocando = video.play();
    if (tocando && tocando.catch) tocando.catch(function () { video.muted = true; video.play().catch(function () { tela.remove(); }); });
  }

  /* Prepara o modal a partir de data-* do botão: data-form-action, data-valor-<campo>,
     data-texto-<slot>. Tudo por value/textContent. Erros do servidor somem ao reabrir. */
  function prepararModal(modal, botao) {
    var form = modal.querySelector("form");
    modal.querySelectorAll(".campo__erro").forEach(function (e) { e.remove(); });
    modal.querySelectorAll(".campo--erro").forEach(function (e) { e.classList.remove("campo--erro"); });
    modal.querySelectorAll("[data-somente-editar]").forEach(function (e) { e.hidden = botao.dataset.modo !== "editar"; });
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
      contarCliqueDoEasteregg();
      alternarTema(alvo);
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
      if (codigo) copiar(codigo.textContent.trim());
    }
  });

  /* navigator.clipboard só existe em HTTPS ou localhost; pelo IP da rede (http) cai no execCommand. */
  function copiar(texto) {
    function avisar(ok) {
      if (window.mostrarToast) window.mostrarToast(ok ? "success" : "error", ok ? "Copiado: " + texto : "Não foi possível copiar. Selecione o texto e use Ctrl+C.");
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(texto).then(function () { avisar(true); }, function () { avisar(copiarAntigo(texto)); });
    } else {
      avisar(copiarAntigo(texto));
    }
  }

  function copiarAntigo(texto) {
    var area = document.createElement("textarea");
    area.value = texto;
    area.setAttribute("readonly", "");
    area.style.position = "fixed"; area.style.top = "0"; area.style.left = "0"; area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    area.remove();
    return ok;
  }

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

  /* Menu "Arquivo": fecha ao clicar fora ou com Esc. */
  document.addEventListener("click", function (ev) {
    document.querySelectorAll("details[data-menu][open]").forEach(function (m) { if (!m.contains(ev.target) || ev.target.closest(".menu__item")) m.removeAttribute("open"); });
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") document.querySelectorAll("details[data-menu][open]").forEach(function (m) { m.removeAttribute("open"); });
  });

  /* Importar: valida tipo e tamanho antes de enviar (o servidor valida de novo). */
  document.addEventListener("submit", function (ev) {
    var form = ev.target.closest && ev.target.closest("form[data-importar]");
    if (!form) return;
    var campo = form.querySelector("[data-arquivo-importar]"), erro = form.querySelector("[data-erro-arquivo]");
    var arq = campo && campo.files && campo.files[0], msg = "";
    if (!arq) msg = "Escolha um arquivo .json.";
    else if (!/\.json$/i.test(arq.name)) msg = "O arquivo precisa ser .json.";
    else if (arq.size > 2 * 1024 * 1024) msg = "O arquivo passa de 2 MB.";
    if (msg) {
      ev.preventDefault(); ev.stopImmediatePropagation();
      erro.textContent = msg; erro.hidden = false; campo.closest(".campo").classList.add("campo--erro");
      form.querySelectorAll("[aria-busy]").forEach(function (b) { b.removeAttribute("aria-busy"); });
    }
  }, true);
})();
