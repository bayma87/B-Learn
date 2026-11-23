from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from appweb.models import ItemConcluido, RegistroResiduo


SENHA = 'senha-forte-ESG-2026'

PAGINAS_PROTEGIDAS = (
    'quiz',
    'painel_residuos',
    'painel_social',
    'painel_recomendacoes',
    'painel_consumo',
    'painel_equipamentos',
    'painel_microlearning',
    'painel_fornecedores',
)

APIS_PROTEGIDAS = (
    'resumo_residuos',
    'indicadores_sociais',
    'recomendacoes',
    'indicadores_consumo',
    'consumo_por_hora_equipamentos',
    'dados_microlearning',
    'dados_fornecedores',
)


def criar_usuario(username):
    return get_user_model().objects.create_user(
        username=username,
        email=f'{username}@example.com',
        password=SENHA,
    )


def responder(cliente, item_id, resposta=None):
    return cliente.post(
        reverse('responder_microlearning'),
        {'id': item_id, 'resposta': resposta},
        content_type='application/json',
        secure=True,
    )


class AcessoAnonimoTests(TestCase):
    def test_paginas_publicas_abrem_sem_login(self):
        for nome in ('home', 'quem_somos', 'entrar', 'cadastro'):
            response = self.client.get(reverse(nome), secure=True)

            self.assertEqual(response.status_code, 200, nome)

    def test_paginas_protegidas_redirecionam_para_login(self):
        for nome in PAGINAS_PROTEGIDAS:
            url = reverse(nome)
            response = self.client.get(
                url, secure=True, HTTP_ACCEPT='text/html',
            )

            self.assertRedirects(
                response,
                f"{reverse('entrar')}?next={url}",
                fetch_redirect_response=False,
                msg_prefix=nome,
            )

    def test_apis_protegidas_respondem_401_em_json(self):
        for nome in APIS_PROTEGIDAS:
            response = self.client.get(reverse(nome), secure=True)

            self.assertEqual(response.status_code, 401, nome)
            self.assertEqual(response.json()['erro'], 'Faça login para continuar.')

    def test_post_anonimo_nao_registra_progresso(self):
        response = responder(self.client, 'd1')

        self.assertEqual(response.status_code, 401)
        self.assertEqual(ItemConcluido.objects.count(), 0)

    def test_post_anonimo_de_simulacao_bloqueado(self):
        response = self.client.post(
            reverse('simular_investimentos'),
            {},
            content_type='application/json',
            secure=True,
        )

        self.assertEqual(response.status_code, 401)

    def test_menu_mostra_entrar_e_criar_conta(self):
        response = self.client.get(reverse('home'), secure=True)

        self.assertContains(response, reverse('entrar'))
        self.assertContains(response, reverse('cadastro'))
        self.assertNotContains(response, reverse('sair'))


class CadastroTests(TestCase):
    def cadastrar(self, **dados):
        corpo = {
            'username': 'ana',
            'email': 'ana@example.com',
            'password1': SENHA,
            'password2': SENHA,
        }
        corpo.update(dados)
        return self.client.post(reverse('cadastro'), corpo, secure=True)

    def test_cadastro_cria_usuario_e_ja_entra(self):
        response = self.cadastrar()

        self.assertRedirects(
            response,
            reverse('painel_microlearning'),
            fetch_redirect_response=False,
        )
        usuario = get_user_model().objects.get(username='ana')
        self.assertTrue(usuario.check_password(SENHA))
        self.assertNotEqual(usuario.password, SENHA)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), usuario.pk,
        )

    def test_cadastro_rejeita_senhas_diferentes(self):
        response = self.cadastrar(password2='outra-senha-ESG-2026')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username='ana').exists())

    def test_cadastro_rejeita_senha_fraca(self):
        response = self.cadastrar(password1='123', password2='123')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username='ana').exists())

    def test_cadastro_rejeita_usuario_ou_email_repetido(self):
        criar_usuario('ana')

        self.assertEqual(self.cadastrar(email='nova@example.com').status_code, 200)
        self.assertEqual(
            self.cadastrar(username='outra', email='ANA@example.com').status_code,
            200,
        )
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_usuario_logado_nao_ve_cadastro(self):
        self.client.force_login(criar_usuario('ana'))

        response = self.client.get(reverse('cadastro'), secure=True)

        self.assertRedirects(
            response,
            reverse('painel_microlearning'),
            fetch_redirect_response=False,
        )


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.usuario = criar_usuario('ana')

    def test_login_valido_respeita_next(self):
        response = self.client.post(
            reverse('entrar'),
            {
                'username': 'ana',
                'password': SENHA,
                'next': reverse('painel_residuos'),
            },
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse('painel_residuos'),
            fetch_redirect_response=False,
        )

    def test_login_ignora_next_para_outro_site(self):
        response = self.client.post(
            reverse('entrar'),
            {
                'username': 'ana',
                'password': SENHA,
                'next': 'https://site-malicioso.example/',
            },
            secure=True,
        )

        self.assertRedirects(
            response,
            reverse('painel_microlearning'),
            fetch_redirect_response=False,
        )

    def test_login_invalido_mostra_erro(self):
        response = self.client.post(
            reverse('entrar'),
            {'username': 'ana', 'password': 'errada'},
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Usuário ou senha incorretos.')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_troca_a_chave_da_sessao(self):
        self.client.get(reverse('entrar'), secure=True)
        self.client.session.save()
        chave_antes = self.client.session.session_key

        self.client.post(
            reverse('entrar'),
            {'username': 'ana', 'password': SENHA},
            secure=True,
        )

        self.assertNotEqual(self.client.session.session_key, chave_antes)

    def test_menu_mostra_usuario_e_sair(self):
        self.client.force_login(self.usuario)

        response = self.client.get(reverse('home'), secure=True)

        self.assertContains(response, 'Conectado como <strong>ana</strong>')
        self.assertContains(response, reverse('sair'))

    def test_logout_exige_post_e_encerra_sessao(self):
        self.client.force_login(self.usuario)

        self.assertEqual(
            self.client.get(reverse('sair'), secure=True).status_code, 405,
        )

        response = self.client.post(reverse('sair'), secure=True)

        self.assertRedirects(
            response, reverse('entrar'), fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.get(reverse('dados_microlearning'), secure=True).status_code,
            401,
        )

    def test_logout_exige_csrf(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)

        response = cliente.post(reverse('sair'), secure=True)

        self.assertEqual(response.status_code, 403)


class IsolamentoEntreUsuariosTests(TestCase):
    def setUp(self):
        self.ana = criar_usuario('ana')
        self.bruno = criar_usuario('bruno')
        self.cliente_ana = Client()
        self.cliente_ana.force_login(self.ana)
        self.cliente_bruno = Client()
        self.cliente_bruno.force_login(self.bruno)

    def progresso(self, cliente):
        return cliente.get(
            reverse('dados_microlearning'), secure=True,
        ).json()['progresso']

    def test_progresso_de_um_usuario_nao_aparece_para_outro(self):
        responder(self.cliente_ana, 'q1', 1)
        responder(self.cliente_ana, 'd3')

        progresso_ana = self.progresso(self.cliente_ana)
        progresso_bruno = self.progresso(self.cliente_bruno)

        self.assertEqual(progresso_ana['pontos'], 30)
        self.assertEqual(sorted(progresso_ana['concluidos']), ['d3', 'q1'])
        self.assertEqual(progresso_bruno['pontos'], 0)
        self.assertEqual(progresso_bruno['concluidos'], [])
        self.assertEqual(progresso_bruno['nivel'], 'Iniciante')

    def test_cada_usuario_evolui_de_nivel_separadamente(self):
        for item in ('d1', 'd2', 'd3'):
            responder(self.cliente_ana, item)
        responder(self.cliente_bruno, 'q1', 1)

        self.assertEqual(self.progresso(self.cliente_ana)['nivel'], 'Engajado')
        self.assertEqual(self.progresso(self.cliente_bruno)['nivel'], 'Iniciante')

    def test_mesmo_item_pontua_para_cada_usuario(self):
        primeira = responder(self.cliente_ana, 'd1').json()
        segunda = responder(self.cliente_bruno, 'd1').json()

        self.assertGreater(primeira['resultado']['pontos_ganhos'], 0)
        self.assertEqual(
            segunda['resultado']['pontos_ganhos'],
            primeira['resultado']['pontos_ganhos'],
        )
        self.assertFalse(segunda['resultado']['ja_concluido'])
        self.assertEqual(ItemConcluido.objects.filter(item_id='d1').count(), 2)

    def test_progresso_persiste_entre_logins(self):
        responder(self.cliente_ana, 'd1')
        self.cliente_ana.post(reverse('sair'), secure=True)

        novo_cliente = Client()
        novo_cliente.post(
            reverse('entrar'),
            {'username': 'ana', 'password': SENHA},
            secure=True,
        )

        self.assertEqual(self.progresso(novo_cliente)['concluidos'], ['d1'])

    def test_quiz_errado_nao_grava_item(self):
        responder(self.cliente_ana, 'q1', 0)

        self.assertFalse(ItemConcluido.objects.filter(usuario=self.ana).exists())

    def test_painel_de_residuos_soma_apenas_registros_do_usuario(self):
        RegistroResiduo.objects.create(
            usuario=self.ana,
            data=date(2026, 11, 1),
            local='Fábrica',
            quantidade_kg=Decimal('10.00'),
            destino='reciclado',
        )
        RegistroResiduo.objects.create(
            usuario=self.bruno,
            data=date(2026, 11, 1),
            local='Escritório',
            quantidade_kg=Decimal('99.00'),
            destino='nao_reciclado',
        )
        RegistroResiduo.objects.create(
            usuario=None,
            data=date(2026, 11, 1),
            local='Registro antigo sem dono',
            quantidade_kg=Decimal('500.00'),
            destino='reciclado',
        )

        contexto_ana = self.cliente_ana.get(
            reverse('painel_residuos'), secure=True,
        ).context
        contexto_bruno = self.cliente_bruno.get(
            reverse('painel_residuos'), secure=True,
        ).context

        self.assertEqual(contexto_ana['total_kg'], Decimal('10.00'))
        self.assertEqual(contexto_ana['taxa_reciclagem'], Decimal('100'))
        self.assertEqual(contexto_bruno['total_kg'], Decimal('99.00'))
        self.assertEqual(contexto_bruno['reciclado_kg'], Decimal('0'))

    def test_excluir_usuario_remove_o_progresso_dele(self):
        responder(self.cliente_ana, 'd1')
        responder(self.cliente_bruno, 'd1')

        self.ana.delete()

        self.assertEqual(
            list(ItemConcluido.objects.values_list('usuario__username', flat=True)),
            ['bruno'],
        )
