"""Login pelo Active Directory (LDAPS, D-039), no mesmo fluxo do Monitor de IA (ati-claude-monitor):
bind com a credencial de serviço → busca o usuário por sAMAccountName → bind com a senha dele.
A credencial de serviço vem da biblioteca corporativa; a senha do usuário nunca é gravada."""

import logging
import re
import ssl
import sys
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Group
from django.db import transaction

from .models import Setor, Usuario

logger = logging.getLogger("contas.ad")

LOGIN_VALIDO = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # sAMAccountName


class ADIndisponivel(Exception):
    """Falha de infraestrutura (rede, certificado, credencial de serviço): a tela avisa."""


class SemPermissaoAD(Exception):
    """Senha certa, mas o usuário não está em nenhum grupo de AD_GRUPOS_PERMITIDOS."""


@dataclass
class DadosAD:
    login: str
    email: str
    nome: str
    grupos: list = field(default_factory=list)
    cargo: str = ""  # `title` do AD (D-041)


def normalizar_login(texto):
    """`EEM\\fulano`, `fulano@eem.adv.br` e `fulano` → `fulano` (ou '' se inválido)."""
    login = (texto or "").strip()
    if "\\" in login:
        login = login.split("\\", 1)[1]
    login = login.split("@", 1)[0]
    return login.lower() if LOGIN_VALIDO.match(login) else ""


def _credencial_servico():
    if settings.AD_BIBLIOTECA not in sys.path:
        sys.path.append(settings.AD_BIBLIOTECA)
    from pegar_credenciais import pegar_credenciais  # só existe na rede da empresa

    return pegar_credenciais([settings.AD_CREDENCIAL_SERVICO])[0]


def _tls():
    from ldap3 import Tls

    if not settings.AD_TLS_VERIFICAR:
        logger.warning("AD_TLS_VERIFICAR=0: certificado do AD NÃO é validado.")
        return Tls(validate=ssl.CERT_NONE)
    return Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=settings.AD_CA_CERT or None)


def _valor(entrada, atributo):
    return str(entrada[atributo].value or "").strip() if atributo in entrada else ""


def autenticar_no_ad(login, senha):
    """DadosAD se usuário e senha conferem; None se não. Erro de infraestrutura → ADIndisponivel."""
    if not login or not senha:  # senha vazia faria um bind anônimo, que o AD aceita
        return None
    from ldap3 import SIMPLE, Connection, Server
    from ldap3.utils.conv import escape_filter_chars

    try:
        credencial = _credencial_servico()
        servidor = Server(
            settings.AD_SERVIDOR,
            use_ssl=True,
            port=settings.AD_PORTA,
            tls=_tls(),
            connect_timeout=8,
        )
        conexao = Connection(
            servidor,
            user=credencial["usr"],
            password=credencial["pass"],
            authentication=SIMPLE,
            receive_timeout=15,
        )
        if not conexao.bind():
            raise ConnectionError(f"Falha no bind do usuário de serviço: {conexao.result}")
        try:
            conexao.search(
                search_base=settings.AD_BASE_DN,
                search_filter=f"(sAMAccountName={escape_filter_chars(login)})",
                attributes=["memberOf", "mail", "displayName", "title"],
            )
            if not conexao.entries:
                return None
            entrada = conexao.entries[0]
            dn = entrada.entry_dn
            grupos_dn = entrada.memberOf.values if "memberOf" in entrada else []
            email, nome = _valor(entrada, "mail"), _valor(entrada, "displayName")
            cargo = _valor(entrada, "title")
        finally:
            conexao.unbind()

        do_usuario = Connection(
            servidor, user=dn, password=senha, authentication=SIMPLE, receive_timeout=15
        )
        if not do_usuario.bind():
            return None
        do_usuario.unbind()
    except Exception as erro:
        logger.exception("Erro ao consultar o AD")
        raise ADIndisponivel(str(erro)) from erro

    # "CN=Equipe Tecnologia,OU=...,DC=EEM,DC=local" → "Equipe Tecnologia"
    grupos = [m.group(1) for m in (re.match(r"CN=([^,]+)", g) for g in grupos_dn) if m]
    return DadosAD(
        login=login,
        email=(email or f"{login}@{settings.AD_DOMINIO_EMAIL}").lower(),
        nome=nome or " ".join(p.capitalize() for p in re.split(r"[._-]", login) if p),
        grupos=grupos,
        cargo=cargo,
    )


def grupo_permitido(grupos):
    permitidos = settings.AD_GRUPOS_PERMITIDOS
    return not permitidos or bool({g.lower() for g in grupos} & set(permitidos))


@transaction.atomic
def usuario_do_ad(dados):
    """Usuário do produto com o e-mail do AD; no 1º login é criado como Base (D-039).
    Papel, setor e nome de quem já existe ficam como o Adm deixou, exceto os AD_LOGINS_ADM,
    que viram Adm a cada login. O cargo segue o AD (`title`) quando ele vem preenchido (D-041)."""
    usuario = Usuario.objects.filter(email__iexact=dados.email).first()
    if not usuario:
        usuario = Usuario.objects.create_user(
            email=dados.email,
            nome=dados.nome[:120],
            cargo=dados.cargo[:120],
            setor=Setor.objects.filter(nome__iexact=settings.AD_SETOR_PADRAO, ativo=True).first(),
        )
        usuario.groups.set([Group.objects.get_or_create(name="Base")[0]])
        logger.info("Usuário criado pelo 1º login no AD: %s", dados.login)
    elif dados.cargo and usuario.cargo != dados.cargo[:120]:
        usuario.cargo = dados.cargo[:120]
        usuario.save(update_fields=["cargo"])
    if dados.login in settings.AD_LOGINS_ADM and list(
        usuario.groups.values_list("name", flat=True)
    ) != ["Adm"]:
        usuario.groups.set([Group.objects.get_or_create(name="Adm")[0]])
        logger.info("Login de rede em AD_LOGINS_ADM promovido a Adm: %s", dados.login)
    return usuario


class BackendAD(ModelBackend):
    """Só AD: a senha local não vale. `username` é o login de rede (ou o e-mail)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        dados = autenticar_no_ad(normalizar_login(username), password)
        if dados is None:
            return None
        if not grupo_permitido(dados.grupos):
            raise SemPermissaoAD(dados.login)
        usuario = usuario_do_ad(dados)
        return usuario if self.user_can_authenticate(usuario) else None
