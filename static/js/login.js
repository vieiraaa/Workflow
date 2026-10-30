/* Login (TEL-01, D-039): envia por fetch e, aceito pelo AD, mostra a tela de carregamento (orb + logo)
   por no mínimo 3 s antes de abrir o destino. Sem JS o formulário posta normal e redireciona. */
(function () {
  "use strict";
  var form = document.getElementById("form-login");
  if (!form) return;
  var alerta = form.querySelector("[data-login-erro]");
  var textoAlerta = form.querySelector("[data-login-erro-texto]");
  var botao = form.querySelector("[type=submit]");
  var rotuloBotao = botao.textContent;

  function espera(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function mostrarErro(texto) {
    textoAlerta.textContent = texto;
    alerta.hidden = !texto;
  }

  function liberar() {
    botao.removeAttribute("aria-busy");
    botao.textContent = rotuloBotao;
    form.password.value = "";
    form.password.focus();
  }

  function carregar(nome, destino) {
    var tela = document.getElementById("carregamento");
    if (nome) {
      tela.querySelector("[data-carregamento-msg]").textContent = "Olá, " + nome + "! Preparando seu painel…";
    }
    tela.hidden = false;
    Promise.all([espera(3000), fetch(destino, { credentials: "same-origin" }).catch(function () { return null; })])
      .then(function () { location.replace(destino); });
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();  /* o app.js ignora envio com defaultPrevented */
    if (!form.username.value.trim() || !form.password.value) {
      mostrarErro("Preencha usuário e senha.");
      return;
    }
    if (botao.getAttribute("aria-busy") === "true") return;
    mostrarErro("");
    botao.setAttribute("aria-busy", "true");
    botao.textContent = botao.getAttribute("data-texto-carregando");
    fetch(location.href, {
      method: "POST",
      body: new FormData(form),
      headers: { "X-Requested-With": "fetch" },
      credentials: "same-origin",
    })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (d) {
        if (d.ok) { carregar(d.nome, d.destino); return; }
        var erros = (d.erros || []).map(function (e) { return e.mensagem; });
        mostrarErro(erros.join(" ") || "Não foi possível entrar.");
        liberar();
      })
      .catch(function () { mostrarErro("Sem conexão com o servidor."); liberar(); });
  });
})();
