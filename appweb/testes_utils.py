from django.contrib.auth import get_user_model
from django.test import TestCase


class TestCaseAutenticado(TestCase):
    """TestCase cujo self.client já começa logado com um usuário de teste.

    Todas as telas e APIs (exceto início, quem somos, entrar e cadastro)
    exigem login; os testes de funcionalidade usam esta base.
    """

    def setUp(self):
        super().setUp()
        self.usuario = get_user_model().objects.create_user(
            username='usuario_teste',
            email='usuario_teste@example.com',
        )  # sem senha: force_login dispensa e evita o custo do hash
        self.client.force_login(self.usuario)
