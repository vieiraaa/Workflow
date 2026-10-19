from django.urls import path

from . import views

app_name = "juridico"

urlpatterns = [
    path("", views.PainelView.as_view(), name="painel"),
    path("processos/novo/", views.ProcessoNovoView.as_view(), name="processo_novo"),
    path("processos/<int:pk>/", views.ProcessoView.as_view(), name="processo"),
    path(
        "processos/<int:pk>/marcar-cadastrado/",
        views.MarcarCadastradoView.as_view(),
        name="marcar_cadastrado",
    ),
    path(
        "processos/<int:pk>/desfazer-cadastrado/",
        views.DesfazerCadastradoView.as_view(),
        name="desfazer_cadastrado",
    ),
    path(
        "processos/<int:pk>/consultar-cnj/", views.ConsultarCnjView.as_view(), name="consultar_cnj"
    ),
    path("processos/<int:pk>/excluir/", views.ExcluirView.as_view(), name="excluir"),
    path("processos/<int:pk>/restaurar/", views.RestaurarView.as_view(), name="restaurar"),
    path("enviar-pdfs/", views.EnviarPdfsView.as_view(), name="enviar_pdfs"),
    path("enviar-cnj/", views.EnviarCnjView.as_view(), name="enviar_cnj"),
    path("envios/", views.EnviosView.as_view(), name="envios"),
    path("envios/<int:pk>/", views.EnvioView.as_view(), name="envio"),
    path("itens/<int:pk>/pdf/", views.PdfView.as_view(), name="pdf"),
    path("itens/<int:pk>/tentar-de-novo/", views.TentarDeNovoView.as_view(), name="tentar_de_novo"),
    path("itens/<int:pk>/resolver/", views.ResolverView.as_view(), name="resolver"),
    path("erros/", views.ErrosView.as_view(), name="erros"),
    path("audiencias/", views.AudienciasView.as_view(), name="audiencias"),
    path("config/", views.ConfigView.as_view(), name="config"),
    path("config/testar/", views.TestarConexaoView.as_view(), name="testar_conexao"),
    path("config/carteiras/nova/", views.CarteiraNovaView.as_view(), name="carteira_nova"),
    path("config/carteiras/<int:pk>/", views.CarteiraEditarView.as_view(), name="carteira_editar"),
    path("config/excluidos/", views.ExcluidosView.as_view(), name="excluidos"),
    path("status/", views.StatusView.as_view(), name="status"),
]
