from django.core.exceptions import ValidationError


class SenhaRepetitivaValidator:
    """Recusa senhas com poucos caracteres distintos (ex.: 'aaaaaaaaaaaa', 'abababababab')."""

    def __init__(self, minimo_distintos=5):
        self.minimo_distintos = minimo_distintos

    def validate(self, password, user=None):
        if len(set(password)) < self.minimo_distintos:
            raise ValidationError(
                "Esta senha é muito repetitiva. Use mais caracteres diferentes.",
                code="senha_repetitiva",
            )

    def get_help_text(self):
        return f"A senha precisa ter pelo menos {self.minimo_distintos} caracteres diferentes."
