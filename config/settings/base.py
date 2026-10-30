"""Configuração comum. Os padrões aqui são os seguros (produção); dev e teste relaxam."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "")
# Chave Fernet do cofre de credenciais (SEG-18): só do ambiente; vazia = ausente (MV2-18 C2).
CREDENCIAIS_CHAVE = os.environ.get("CREDENCIAIS_CHAVE", "")
DEBUG = False
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.nucleo",
    "apps.contas",
    "apps.fluxos",
    "apps.execucoes",
    "apps.motor",
    "apps.credenciais",
    "apps.funcoes",
    "apps.juridico",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.nucleo.middleware.EncerraSessaoInvalidaMiddleware",
    "apps.contas.presenca.PresencaMiddleware",  # bolinha "online" do perfil (D-041)
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.contas.simulacao.SimulacaoMiddleware",  # Adm vê como outro usuário (D-047)
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.nucleo.contexto.shell",
            ],
        },
    },
]

AUTH_USER_MODEL = "contas.Usuario"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.contas.validators.SenhaRepetitivaValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "login"


def _sim(valor):
    return str(valor).strip().lower() not in ("0", "false", "nao", "não", "no", "")


# Login pelo Active Directory (D-039): só AD; quem entra pela 1ª vez vira Base no AD_SETOR_PADRAO.
# LOGIN_AD=0 volta ao login local por e-mail (testes e ambientes fora da rede da empresa).
LOGIN_AD = _sim(os.environ.get("LOGIN_AD", "1"))
AUTHENTICATION_BACKENDS = [
    "apps.contas.ad.BackendAD" if LOGIN_AD else "django.contrib.auth.backends.ModelBackend"
]
AD_SERVIDOR = os.environ.get("AD_SERVIDOR", "EEM-CWB-DC02.EEM.local")
AD_PORTA = int(os.environ.get("AD_PORTA") or 636)
AD_BASE_DN = os.environ.get("AD_BASE_DN", "DC=EEM,DC=local")
# Certificado do LDAPS validado pelo repositório do SO (sem isso, um falso DC receberia as senhas).
AD_TLS_VERIFICAR = _sim(os.environ.get("AD_TLS_VERIFICAR", "1"))
AD_CA_CERT = os.environ.get("AD_CA_CERT", "")
AD_CREDENCIAL_SERVICO = "binduser_hubia"
AD_BIBLIOTECA = r"\\EEM-CWB-DC02.EEM.local\Corporativo\Tecnologia\Biblioteca"
AD_DOMINIO_EMAIL = os.environ.get("AD_DOMINIO_EMAIL", "eem.adv.br")  # se o AD não tiver `mail`
# Grupos do AD que podem entrar (separados por vírgula). Vazio = qualquer usuário do AD.
AD_GRUPOS_PERMITIDOS = [
    g.strip().lower() for g in os.environ.get("AD_GRUPOS_PERMITIDOS", "").split(",") if g.strip()
]
AD_SETOR_PADRAO = "Geral"
# Logins de rede sempre Adm (garantido a cada login): sem senha local, é assim que nasce o 1º Adm.
AD_LOGINS_ADM = [
    g.strip().lower()
    for g in os.environ.get("AD_LOGINS_ADM", "joao.vieira").split(",")
    if g.strip()
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Segurança (SEG-11, SEG-12)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Spec e motor
SPEC_DIR = BASE_DIR / "docs" / "spec"
# Liberação de loopback para testes do executor (SEG-08): vazia em TODOS os ambientes.
MOTOR_SSRF_LIBERAR = []
# Limites do motor (SEG-07, SEG-16, EXE-13); os testes reduzem via fixture `settings`.
MOTOR_TIMEOUT_CONEXAO = 5  # segundos
MOTOR_TIMEOUT_LEITURA = 10
MOTOR_TIMEOUT_NO = 15
MOTOR_TIMEOUT_EXECUCAO = 60
MOTOR_LIMITE_RESPOSTA = 1048576  # bytes, já descompactado
MOTOR_MAX_REDIRECTS = 5

# Logs (SEG-11): httpx/httpcore imprimem a URL com a query; só WARNING+ e com query mascarada.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"mascarar_query": {"()": "apps.motor.mascarar.FiltroMascararQuery"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "filters": ["mascarar_query"]}},
    "loggers": {
        nome: {"handlers": ["console"], "level": "WARNING", "propagate": False}
        for nome in ("httpx", "httpcore")
    },
}

# Pasta PRIVADA dos PDFs do cadastro (CAD-04): nunca servida por URL (sem MEDIA_URL).
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT") or BASE_DIR / "arquivos_privados")
# Cadastro de processos (M8, CAD-23 item 8). Os testes sobrescrevem com o fixture `settings`.
JURIDICO_DIFY_TIMEOUT_S = 300
JURIDICO_DATAJUD_TIMEOUT_S = 30
JURIDICO_DATAJUD_INTERVALO_S = 1.5
JURIDICO_DATAJUD_ESPERAS_429_S = (5, 15)  # novas tentativas após o erro 429 (D-058)
JURIDICO_TRAVADO_MIN = 15
JURIDICO_TEXTO_MAX = 40_000
JURIDICO_TEXTO_INICIO = 25_000
JURIDICO_TEXTO_FIM = 15_000
JURIDICO_PDF_MAX_MB = 30
JURIDICO_PDF_MAX_ARQUIVOS = 10
JURIDICO_RESPOSTA_MAX_BYTES = 2_097_152
