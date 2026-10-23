"""Dados fictícios do cadastro para a demo local (T-078): 3 processos e 1 envio com erro.

Nada aqui aponta para Dify ou DataJud: as credenciais ficam vazias (o worker falharia com
mensagem clara). Idempotente. Só dados inventados.
"""

from django.utils import timezone

from apps.contas.models import Setor, Usuario

from . import cnj, mescla
from .models import Carteira, ConfigCadastro, Envio, ItemEnvio, Processo

PROCESSOS = [
    # (sequencial, ano, tr, status desejado, dados)
    (4101, 2023, 26, Processo.CONFERIR, {
        "adverso_nome": "Marta Souza Ficticia", "adverso_cpf_cnpj": "111.444.777-35",
        "tribunal": "TJSP", "comarca": "São Paulo", "juizo": "3ª Vara Cível",
        "valor_causa": "12500.00", "distribuido_em": "2023-02-10", "empresa": "Volvo",
    }),
    (4102, 2023, 19, Processo.COM_PENDENCIAS, {
        "adverso_nome": "Comercial Exemplo Ltda", "adverso_cpf_cnpj": "11.222.333/0001-81",
        "tribunal": "TJRJ", "comarca": "Rio de Janeiro", "empresa": "Toyota",
    }),
    (4103, 2022, 26, Processo.CADASTRADO, {
        "adverso_nome": "Paulo Andrade Ficticio", "adverso_cpf_cnpj": "529.982.247-25",
        "tribunal": "TJSP", "comarca": "Campinas", "juizo": "1ª Vara Cível",
        "valor_causa": "8000.00", "distribuido_em": "2022-08-01", "empresa": "Ailos",
    }),
]  # fmt: skip


def semear():
    config = ConfigCadastro.obter()
    geral = Setor.objects.filter(nome="Geral").first()
    if geral:
        config.setores_com_acesso.add(geral)
    adm = Usuario.objects.filter(email="adm@exemplo.test").first()
    if adm is None or Processo.todos.exists():
        return
    carteiras = {c.nome.lower(): c for c in Carteira.objects.all()}
    for sequencial, ano, tr, status, dados in PROCESSOS:
        numero = cnj.numero_valido_de(sequencial, ano, 8, tr, 100)
        processo = Processo(
            numero=numero,
            numero_digitos=cnj.so_digitos(numero),
            numero_valido=True,
            criado_por=adm,
            criado_via=Processo.PDF,
            carteira=carteiras.get(dados["empresa"].lower()),
            origem_campos={campo: "pdf" for campo in dados},
        )
        for campo, valor in dados.items():
            setattr(processo, campo, valor)
        mescla.recalcular(processo)
        if status == Processo.CADASTRADO:
            processo.status = Processo.CADASTRADO
            processo.cadastrado_espaider_em = timezone.now()
            processo.cadastrado_espaider_por = adm
        processo.save()
    envio = Envio.objects.create(
        origem=Envio.PDF,
        enviado_por=adm,
        iniciado_em=timezone.now(),
        terminado_em=timezone.now(),
    )
    ItemEnvio.objects.create(
        envio=envio,
        nome_arquivo="processo-ficticio.pdf",
        status=ItemEnvio.ERRO,
        etapa_erro="IA (Dify)",
        motivo="A IA não respondeu: Credencial do Dify não configurada: escolha-a em Configuração.",
    )
