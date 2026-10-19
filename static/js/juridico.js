/* JS fino do Jurídico: seleção no painel, auto-atualização, soltar arquivos. Validação final é do servidor. */
(function () {
  "use strict";
  var INTERVALO_MS = 10000;
  var MAPA_BADGE = { concluido: "sucesso", processando: "executando", erro: "erro", na_fila: "rascunho", ignorado: "rascunho" };
  var ROTULOS = { na_fila: "Na fila", processando: "Processando", concluido: "Concluído", erro: "Erro", ignorado: "Ignorado" };

  function buscarJson(url) {
    return fetch(url, { headers: { "Accept": "application/json" }, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("status " + r.status); return r.json(); });
  }
  /* Repete enquanto `passo` devolver true; pausa com a aba escondida; para em erro de rede/servidor. */
  function repetir(passo) {
    var tempo = null;
    function agendar() { tempo = setTimeout(rodar, INTERVALO_MS); }
    function rodar() {
      if (document.hidden) { agendar(); return; }
      passo().then(function (continuar) { if (continuar) agendar(); }, function () { /* falha: para sem derrubar a tela */ });
    }
    agendar();
    document.addEventListener("visibilitychange", function () { if (!document.hidden && tempo) { clearTimeout(tempo); rodar(); } });
  }

  /* Painel: no desktop o clique no cartão seleciona (?p=); no celular abre o detalhe. */
  document.addEventListener("click", function (ev) {
    var link = ev.target.closest && ev.target.closest("a[data-href-desktop]");
    if (!link || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
    if (window.matchMedia && window.matchMedia("(min-width: 1001px)").matches) {
      ev.preventDefault();
      window.location.assign(link.getAttribute("data-href-desktop"));
    }
  });
  document.addEventListener("change", function (ev) {
    var campo = ev.target;
    if (campo.matches && campo.matches("select[data-auto-enviar]") && campo.form) campo.form.submit();
  });

  /* Painel: contagens a cada 10 s enquanto houver itens do usuário em andamento. */
  var painel = document.querySelector("[data-painel][data-status-url]");
  if (painel) {
    var aviso = painel.querySelector("[data-painel-aviso]"), texto = painel.querySelector("[data-painel-aviso-texto]");
    var recarregar = painel.querySelector("[data-painel-recarregar]"), totalInicial = null;
    aviso.hidden = false;
    recarregar.setAttribute("href", window.location.href);
    repetir(function () {
      return buscarJson(painel.getAttribute("data-status-url")).then(function (d) {
        ["total", "com_pendencias", "conferir", "cadastrados", "na_fila", "erros"].forEach(function (k) {
          var el = painel.querySelector('[data-resumo="' + k + '"]');
          if (el && d[k] != null) el.textContent = String(d[k]);
          var frase = painel.querySelector('[data-contagem="' + k + '"]');
          if (frase && d[k] != null) frase.textContent = String(d[k]);
        });
        if (totalInicial === null) totalInicial = d.total;
        if (d.total !== totalInicial) recarregar.hidden = false;
        if (d.em_andamento) { texto.textContent = d.na_fila + (d.na_fila === 1 ? " item na fila…" : " itens na fila…"); return true; }
        texto.textContent = "Processamento concluído.";
        painel.querySelector(".painel__aviso .icone").style.display = "none";
        recarregar.hidden = false;
        return false;
      });
    });
  }

  /* Envio: status de cada item por textContent; para quando nada mais está em andamento. */
  var envio = document.querySelector("[data-envio][data-status-url]");
  if (envio) {
    var andamento = envio.querySelector("[data-envio-andamento]");
    function emAndamento() { return !!envio.querySelector('[data-item-status="na_fila"], [data-item-status="processando"]'); }
    if (emAndamento()) {
      if (andamento) andamento.hidden = false;
      repetir(function () {
        return buscarJson(envio.getAttribute("data-status-url")).then(function (d) {
          (d.itens || []).forEach(function (i) {
            var li = envio.querySelector('[data-item="' + String(i.pk).replace(/\D/g, "") + '"]');
            if (!li) return;
            li.setAttribute("data-item-status", i.status);
            var badge = li.querySelector("[data-item-badge]");
            badge.className = "badge badge--" + (MAPA_BADGE[i.status] || "rascunho");
            badge.textContent = i.status_rotulo || ROTULOS[i.status] || i.status;
            var motivo = li.querySelector("[data-item-motivo]");
            motivo.textContent = i.motivo || i.aviso || ""; motivo.hidden = !(i.motivo || i.aviso);
            var proc = li.querySelector("[data-item-processo]");
            if (i.processo_url && /^\//.test(i.processo_url)) { proc.setAttribute("href", i.processo_url); proc.textContent = "Abrir processo"; proc.hidden = false; }
          });
          if (d.em_andamento) return true;
          if (andamento) andamento.hidden = true;
          return false;
        });
      });
    }
  }

  /* Enviar PDFs: arrastar e soltar + escolher; contagem e validação de tamanho no cliente. */
  var form = document.querySelector("[data-form-pdfs]");
  if (form) {
    var zona = form.querySelector("[data-dropzone]"), entrada = form.querySelector("[data-dropzone-input]");
    var lista = form.querySelector("[data-dropzone-lista]"), contagem = form.querySelector("[data-dropzone-contagem]");
    var erro = form.querySelector("[data-dropzone-erro]"), enviar = form.querySelector("[type=submit]");
    var maxArquivos = Number(form.getAttribute("data-max-arquivos")) || 10, maxBytes = (Number(form.getAttribute("data-max-mb")) || 30) * 1024 * 1024;
    var escolhidos = [];

    function tamanho(b) { return b >= 1048576 ? (b / 1048576).toFixed(1).replace(".", ",") + " MB" : Math.max(1, Math.round(b / 1024)) + " KB"; }
    function ehPdf(f) { return f.type === "application/pdf" || /\.pdf$/i.test(f.name); }
    function sincronizar() {
      if (window.DataTransfer) {
        var dt = new DataTransfer(); escolhidos.forEach(function (f) { dt.items.add(f); }); entrada.files = dt.files;
      }
    }
    function desenhar() {
      lista.textContent = "";
      var problemas = [];
      if (escolhidos.length > maxArquivos) problemas.push("Envie no máximo " + maxArquivos + " PDFs por vez.");
      escolhidos.forEach(function (f, i) {
        var li = document.createElement("li"), nome = document.createElement("span"), meta = document.createElement("span"), rm = document.createElement("button");
        var ruim = null;
        if (!ehPdf(f)) ruim = f.name + ": não é um PDF."; else if (f.size > maxBytes) ruim = f.name + ": maior que 30 MB.";
        if (ruim) { problemas.push(ruim); li.className = "arquivos__item--erro"; }
        nome.className = "arquivos__nome"; nome.textContent = f.name;
        meta.className = "texto-2"; meta.textContent = tamanho(f.size);
        rm.type = "button"; rm.className = "botao botao--icone"; rm.setAttribute("aria-label", "Remover " + f.name); rm.textContent = "×";
        rm.addEventListener("click", function () { escolhidos.splice(i, 1); sincronizar(); desenhar(); });
        li.appendChild(nome); li.appendChild(meta); li.appendChild(rm); lista.appendChild(li);
      });
      var n = escolhidos.length;
      contagem.textContent = n ? n + (n === 1 ? " arquivo escolhido" : " arquivos escolhidos") + " (máximo " + maxArquivos + ")." : "Nenhum arquivo escolhido.";
      erro.hidden = !problemas.length; erro.textContent = problemas.join(" ");
      enviar.disabled = !n || problemas.length > 0;
    }
    function adicionar(arquivos) {
      [].forEach.call(arquivos, function (f) {
        var igual = escolhidos.some(function (e) { return e.name === f.name && e.size === f.size && e.lastModified === f.lastModified; });
        if (!igual) escolhidos.push(f);
      });
      sincronizar(); desenhar();
    }
    entrada.addEventListener("change", function () { escolhidos = []; adicionar(entrada.files); });
    ["dragenter", "dragover"].forEach(function (nome) {
      zona.addEventListener(nome, function (ev) { ev.preventDefault(); zona.classList.add("dropzone--sobre"); });
    });
    ["dragleave", "drop"].forEach(function (nome) {
      zona.addEventListener(nome, function (ev) { ev.preventDefault(); zona.classList.remove("dropzone--sobre"); });
    });
    zona.addEventListener("drop", function (ev) { if (ev.dataTransfer && ev.dataTransfer.files) adicionar(ev.dataTransfer.files); });
    desenhar();
  }
})();
