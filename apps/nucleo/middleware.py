class EncerraSessaoInvalidaMiddleware:
    """PAP-04: sessão que aponta para usuário inativo/inexistente ou com hash antigo é apagada.

    Vem depois do AuthenticationMiddleware: se a sessão guarda um usuário mas `request.user`
    é anônimo, a sessão é descartada (reativar o usuário não a ressuscita).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if "_auth_user_id" in request.session and not request.user.is_authenticated:
            request.session.flush()
        return self.get_response(request)
