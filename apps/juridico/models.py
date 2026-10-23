"""Cadastro de processos (M8, CAD-01..23): carteiras, configuração, processos, envios e itens."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from .armazenamento import ArmazenamentoPrivado

CAMPOS_TEXTO = (
    "empresa", "condicao", "advogado_empresa", "adverso_nome", "adverso_cpf_cnpj",
    "advogado_adverso_nome", "advogado_adverso_oab", "tipo_acao", "rito", "natureza",
    "meio_tramitacao", "instancia", "desdobramento", "tribunal", "comarca", "juizo", "estado",
    "operacoes_vinculadas", "gerencia", "categoria", "escritorio", "peticionamento",
    "na_fase_desde", "responsavel",
)  # fmt: skip
CAMPOS_LONGOS = ("pedidos", "assuntos_cnj", "observacoes")
CAMPOS_MANUAIS = (
    "gerencia",
    "categoria",
    "escritorio",
    "peticionamento",
    "na_fase_desde",
    "responsavel",
)


class Carteira(models.Model):
    nome = models.CharField("nome", max_length=60)
    empresa = models.CharField("empresa", max_length=200, blank=True)
    ativa = models.BooleanField("ativa", default=True)

    class Meta:
        verbose_name = "carteira"
        verbose_name_plural = "carteiras"
        ordering = ["nome"]
        constraints = [models.UniqueConstraint(Lower("nome"), name="carteira_nome_unico_ci")]

    def __str__(self):
        return self.nome


class ConfigCadastro(models.Model):
    """Linha única (CAD-14). O valor das credenciais nunca é guardado aqui, só o NOME."""

    dify_url = models.URLField(
        "URL do Dify",
        max_length=300,
        default="https://eemdevjurdyapi.eem-adv.org/service/api/v1",
    )
    dify_credencial = models.CharField("credencial do Dify", max_length=80, blank=True)
    dify_usuario = models.CharField("usuário do Dify", max_length=80, default="construtor-espaider")
    dify_ca_pem = models.TextField("CA do Dify (PEM)", blank=True)
    datajud_url = models.URLField(
        "URL do DataJud", max_length=300, default="https://api-publica.datajud.cnj.jus.br"
    )
    datajud_credencial = models.CharField("credencial do DataJud", max_length=80, blank=True)
    setores_com_acesso = models.ManyToManyField(
        "contas.Setor", blank=True, related_name="+", verbose_name="setores com acesso"
    )
    datajud_recusado_em = models.DateTimeField(
        "chave do DataJud recusada em", null=True, blank=True, editable=False
    )

    class Meta:
        verbose_name = "configuração do cadastro"
        verbose_name_plural = "configuração do cadastro"

    def __str__(self):
        return "Configuração do cadastro"

    @classmethod
    def obter(cls):
        """A linha única (cria com os padrões se faltar)."""
        return cls.objects.get_or_create(pk=1)[0]

    def setor_tem_acesso(self, setor_id):
        return setor_id is not None and self.setores_com_acesso.filter(pk=setor_id).exists()


class _SoAtivos(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(excluido_em__isnull=True)


class Processo(models.Model):
    COM_PENDENCIAS, CONFERIR, CADASTRADO = "COM_PENDENCIAS", "CONFERIR", "CADASTRADO"
    STATUS = [
        (COM_PENDENCIAS, "Com pendências"),
        (CONFERIR, "Conferir"),
        (CADASTRADO, "Cadastrado no Espaider"),
    ]
    FASES = [
        ("POSTULATORIA", "Postulatória"),
        ("INSTRUTORIA", "Instrutória"),
        ("DECISORIA", "Decisória"),
        ("RECURSAL", "Recursal"),
        ("EXECUCAO_CUMPRIMENTO", "Execução/Cumprimento"),
        ("ARQUIVADO", "Arquivado"),
    ]
    CNJ = [
        ("nao_consultado", "Não consultado"),
        ("confere", "Confere com o CNJ"),
        ("divergente", "Diverge do CNJ"),
        ("nao_encontrado", "Não encontrado no DataJud"),
        ("falhou", "Consulta falhou"),
    ]
    PDF, CNJ_ORIGEM, MANUAL = "pdf", "cnj", "manual"
    ORIGENS = [(PDF, "PDF"), (CNJ_ORIGEM, "CNJ"), (MANUAL, "manual")]

    numero = models.CharField("número", max_length=25)
    numero_digitos = models.CharField("número (dígitos)", max_length=20, db_index=True)
    numero_valido = models.BooleanField("número válido", default=False)
    status = models.CharField("status", max_length=15, choices=STATUS, default=CONFERIR)
    pendencias = models.JSONField("pendências", default=list, blank=True)
    carteira = models.ForeignKey(
        Carteira, null=True, blank=True, on_delete=models.SET_NULL, related_name="processos"
    )
    empresa = models.CharField(max_length=300, blank=True)
    condicao = models.CharField("condição", max_length=100, blank=True)
    advogado_empresa = models.CharField(max_length=300, blank=True)
    adverso_nome = models.CharField(max_length=500, blank=True)
    adverso_cpf_cnpj = models.CharField(max_length=200, blank=True)
    advogado_adverso_nome = models.CharField(max_length=300, blank=True)
    advogado_adverso_oab = models.CharField(max_length=100, blank=True)
    tipo_acao = models.CharField("tipo de ação", max_length=300, blank=True)
    rito = models.CharField(max_length=200, blank=True)
    natureza = models.CharField(max_length=100, blank=True)
    meio_tramitacao = models.CharField("meio de tramitação", max_length=100, blank=True)
    instancia = models.CharField("instância", max_length=100, blank=True)
    desdobramento = models.CharField(max_length=200, blank=True)
    tribunal = models.CharField(max_length=100, blank=True)
    comarca = models.CharField(max_length=200, blank=True)
    juizo = models.CharField("juízo", max_length=300, blank=True)
    estado = models.CharField(max_length=50, blank=True)
    fase_atual = models.CharField(  # noqa: DJ001 - a spec define a fase como texto nulo
        "fase atual", max_length=25, choices=FASES, null=True, blank=True
    )
    distribuido_em = models.DateField("distribuído em", null=True, blank=True)
    data_citacao = models.DateField("data de citação", null=True, blank=True)
    valor_causa = models.DecimalField(
        "valor da causa", max_digits=14, decimal_places=2, null=True, blank=True
    )
    pedidos = models.TextField(blank=True)
    assuntos_cnj = models.TextField("assuntos (CNJ)", blank=True)
    operacoes_vinculadas = models.CharField("operações vinculadas", max_length=500, blank=True)
    andamentos = models.JSONField("andamentos", default=list, blank=True)
    observacoes = models.TextField("observações", blank=True)
    gerencia = models.CharField("gerência", max_length=200, blank=True)
    categoria = models.CharField(max_length=200, blank=True)
    escritorio = models.CharField("escritório", max_length=200, blank=True)
    peticionamento = models.CharField(max_length=200, blank=True)
    na_fase_desde = models.CharField("na fase desde", max_length=100, blank=True)
    responsavel = models.CharField("responsável", max_length=200, blank=True)
    cnj_validacao = models.CharField(
        "validação no CNJ", max_length=15, choices=CNJ, default="nao_consultado"
    )
    cnj_divergencias = models.JSONField("divergências com o CNJ", default=list, blank=True)
    cnj_consultado_em = models.DateTimeField("CNJ consultado em", null=True, blank=True)
    cnj_mensagem = models.CharField("mensagem da consulta ao CNJ", max_length=500, blank=True)
    origem_campos = models.JSONField("origem dos campos", default=dict, blank=True)
    cadastrado_espaider_em = models.DateTimeField(null=True, blank=True)
    cadastrado_espaider_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    proxima_audiencia = models.DateTimeField("próxima audiência", null=True, blank=True)
    proxima_audiencia_tipo = models.CharField(
        "tipo da audiência", max_length=80, blank=True
    )  # só o complemento: 'conciliação', 'instrução e julgamento', 'una'...
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="processos_criados",
    )
    criado_via = models.CharField("criado via", max_length=10, choices=ORIGENS, default=PDF)
    excluido_em = models.DateTimeField(null=True, blank=True)
    excluido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    objects = _SoAtivos()
    todos = models.Manager()  # noqa: DJ012 - `objects` (só ativos) precisa ser o padrão

    class Meta:
        verbose_name = "processo"
        verbose_name_plural = "processos"
        ordering = ["-atualizado_em", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["numero_digitos"],
                condition=Q(numero_valido=True),
                name="processo_numero_valido_unico",
            )
        ]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["proxima_audiencia"])]

    def __str__(self):
        return self.numero

    @property
    def excluido(self):
        return self.excluido_em is not None

    @property
    def manuais(self):
        """Campos só de edição manual (planilha), em uma linha: 'Gerência: G1 · Responsável: …'."""
        rotulos = [(c, self._meta.get_field(c).verbose_name.capitalize()) for c in CAMPOS_MANUAIS]
        return " · ".join(f"{r}: {getattr(self, c)}" for c, r in rotulos if getattr(self, c))

    @property
    def status_rotulo(self):
        return self.get_status_display()


def _caminho_pdf(instancia, nome):
    agora = timezone.now()
    return f"juridico/{agora:%Y}/{agora:%m}/{uuid.uuid4().hex}.pdf"


class Envio(models.Model):
    PDF, CNJ = "pdf", "cnj"
    ORIGENS = [(PDF, "PDF"), (CNJ, "CNJ")]

    origem = models.CharField("origem", max_length=5, choices=ORIGENS)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="envios_cadastro"
    )
    carteira = models.ForeignKey(
        Carteira, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    iniciado_em = models.DateTimeField(null=True, blank=True)
    terminado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "envio"
        verbose_name_plural = "envios"
        ordering = ["-criado_em", "-pk"]

    def __str__(self):
        return f"Envio {self.pk} ({self.get_origem_display()})"

    @property
    def duracao_s(self):
        if self.iniciado_em and self.terminado_em:
            return max(0.0, (self.terminado_em - self.iniciado_em).total_seconds())
        return None


class ItemEnvio(models.Model):
    NA_FILA, PROCESSANDO, CONCLUIDO, ERRO, IGNORADO = (
        "na_fila", "processando", "concluido", "erro", "ignorado",
    )  # fmt: skip
    STATUS = [
        (NA_FILA, "Na fila"),
        (PROCESSANDO, "Processando"),
        (CONCLUIDO, "Concluído"),
        (ERRO, "Erro"),
        (IGNORADO, "Ignorado (duplicado)"),
    ]
    ETAPAS = [
        (e, e)
        for e in (
            "Leitura do PDF",
            "Envio do PDF",
            "IA (Dify)",
            "CNJ (DataJud)",
            "Dados incompletos",
            "Gravação",
        )
    ]
    NOVO, ATUALIZADO = "novo", "atualizado"

    envio = models.ForeignKey(Envio, on_delete=models.CASCADE, related_name="itens")
    arquivo = models.FileField(
        "arquivo", upload_to=_caminho_pdf, storage=ArmazenamentoPrivado(), null=True, blank=True
    )
    nome_arquivo = models.CharField("nome do arquivo", max_length=255, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    numero_informado = models.CharField("número informado", max_length=40, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default=NA_FILA, db_index=True)
    tentativas = models.PositiveIntegerField(default=0)
    etapa_erro = models.CharField(  # noqa: DJ001 - a spec define a etapa como texto nulo
        "etapa do erro", max_length=20, choices=ETAPAS, null=True, blank=True
    )
    motivo = models.CharField(max_length=500, blank=True)
    resolvido = models.BooleanField(default=False)
    processo = models.ForeignKey(
        Processo, null=True, blank=True, on_delete=models.SET_NULL, related_name="itens"
    )
    acao = models.CharField(  # noqa: DJ001 - a spec define a ação como texto nulo
        max_length=10, choices=[(NOVO, "novo"), (ATUALIZADO, "atualizado")], null=True, blank=True
    )
    duplicado_de = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    aviso = models.CharField("aviso de duplicidade", max_length=600, blank=True)
    resposta_ia = models.TextField("resposta da IA", blank=True)
    duracao_ms = models.PositiveIntegerField(null=True, blank=True)
    iniciado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "item de envio"
        verbose_name_plural = "itens de envio"
        ordering = ["pk"]
        indexes = [models.Index(fields=["status", "id"])]

    def __str__(self):
        return self.nome_arquivo or self.numero_informado or f"Item {self.pk}"
