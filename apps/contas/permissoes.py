"""Motor único de permissão. A matriz vem de docs/spec/permissoes.yaml (PRM-xx); nada é duplicado.

- `pode(usuario, acao, objeto=None)`: a ação é permitida? Com `objeto`, ele também precisa estar
  no escopo do papel (ativos / proprias).
- `escopo(usuario, qs, acao=None)`: queryset já filtrado pelo escopo, aplicado no banco (PRM-04).
- `PermissaoMixin`: view que exige login (anônimo → login, PRM-01) e a ação (sem → 403, PRM-02).

O papel efetivo vem só do Group (PAP-02/03): superuser não ganha bypass.
"""

from functools import lru_cache

import yaml
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

NENHUM = "nenhum"
TODOS = "todos"
ATIVOS = "ativos"
PROPRIAS = "proprias"

# Modelo (app_label.model) -> ação de leitura usada por escopo() quando `acao` não é informada.
ACAO_DE_LEITURA = {
    "fluxos.fluxo": "fluxos.ver",
    "execucoes.execucao": "execucoes.ver",
}


@lru_cache(maxsize=1)
def _carregar_spec():
    papeis = yaml.safe_load((settings.SPEC_DIR / "papeis.yaml").read_text(encoding="utf-8"))
    matriz = yaml.safe_load((settings.SPEC_DIR / "permissoes.yaml").read_text(encoding="utf-8"))
    por_grupo = {p["grupo"]: p for p in papeis["papeis"]}
    return por_grupo, matriz["acoes"]


def papeis():
    """Lista de papéis da spec: [{id, grupo, nome}]."""
    return list(_carregar_spec()[0].values())


def papel_de(usuario):
    """Id do papel ('adm', 'coordenador', 'base') ou None. Vale por instância (por requisição)."""
    if usuario is None or not getattr(usuario, "is_authenticated", False) or not usuario.is_active:
        return None
    if not hasattr(usuario, "_papel_cache"):
        por_grupo, _ = _carregar_spec()
        grupos = [g for g in usuario.groups.values_list("name", flat=True) if g in por_grupo]
        usuario._papel_cache = por_grupo[grupos[0]]["id"] if len(grupos) == 1 else None
    return usuario._papel_cache


def nome_do_papel(usuario):
    papel = papel_de(usuario)
    return next((p["nome"] for p in papeis() if p["id"] == papel), "") if papel else ""


def _escopo_da_acao(usuario, acao):
    _, acoes = _carregar_spec()
    if acao not in acoes:
        raise KeyError(f"Ação de permissão desconhecida: {acao}")
    papel = papel_de(usuario)
    return acoes[acao].get(papel, NENHUM) if papel else NENHUM


def pode(usuario, acao, objeto=None):
    escopo_da_acao = _escopo_da_acao(usuario, acao)
    if escopo_da_acao == NENHUM:
        return False
    if objeto is None or escopo_da_acao == TODOS:
        return True
    if escopo_da_acao == ATIVOS:
        return getattr(objeto, "status", None) == "ativo"
    if escopo_da_acao == PROPRIAS:
        return getattr(objeto, "executado_por_id", None) == usuario.pk
    return False


def escopo(usuario, qs, acao=None):
    qs = qs.all() if hasattr(qs, "all") else qs
    acao = acao or ACAO_DE_LEITURA[qs.model._meta.label_lower]
    escopo_da_acao = _escopo_da_acao(usuario, acao)
    if escopo_da_acao == TODOS:
        return qs
    if escopo_da_acao == ATIVOS:
        return qs.filter(status="ativo")
    if escopo_da_acao == PROPRIAS:
        return qs.filter(executado_por=usuario)
    return qs.none()


class PermissaoMixin(LoginRequiredMixin):
    """Defina `acao_requerida` (id da spec). Anônimo → login; sem a ação → 403.

    Objeto fora do escopo → 404: busque-o com `self.escopo_queryset(Model.objects)` e
    `get_object_or_404`, nunca direto no model.
    """

    acao_requerida = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.acao_requerida and not pode(request.user, self.acao_requerida):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def escopo_queryset(self, qs):
        return escopo(self.request.user, qs, self.acao_requerida)
