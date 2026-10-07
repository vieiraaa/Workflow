"""Formatação para as telas de execução (texto puro: o template escapa)."""

import json

ROTULOS_ERRO = {
    "bloqueado_ssrf": "Destino bloqueado por segurança",
    "timeout": "Tempo esgotado",
    "dns": "Falha de DNS",
    "conexao": "Falha de conexão",
    "tls": "Falha de TLS",
    "resposta_grande": "Resposta grande demais",
    "redirect_excessivo": "Redirecionamentos demais",
    "http_4xx": "Erro HTTP 4xx",
    "http_5xx": "Erro HTTP 5xx",
    "placeholder": "Erro de placeholder",
    "json_invalido": "JSON inválido",
}
ROTULOS_NO = {"sucesso": "Sucesso", "erro": "Erro", "nao_executado": "Não executado"}


def duracao_texto(ms):
    """'1,2 s', '0,3 s' ou '1 min 05 s'; vazio quando ainda não há duração."""
    if ms is None:
        return ""
    if ms >= 60_000:
        minutos, segundos = divmod(round(ms / 1000), 60)
        return f"{minutos} min {segundos:02d} s"
    return f"{ms / 1000:.1f}".replace(".", ",") + " s"


def json_formatado(valor):
    """JSON legível (indentado, UTF-8); vazio para None/dict/list vazios."""
    if valor in (None, "", {}, []):
        return ""
    return json.dumps(valor, ensure_ascii=False, indent=2, sort_keys=False)


def corpo_texto(corpo):
    """Corpo da resposta como texto: texto como veio, JSON indentado."""
    if corpo is None:
        return ""
    return corpo if isinstance(corpo, str) else json.dumps(corpo, ensure_ascii=False, indent=2)
