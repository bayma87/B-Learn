from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.http import JsonResponse
from django.shortcuts import redirect


class RestrictAdminMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/painel-secreto/'):
            if not request.user.is_authenticated or not request.user.is_staff:
                return redirect('home')
        return self.get_response(request)


def _espera_html(request):
    """Navegação do navegador pede text/html; o fetch() das telas não."""
    return 'text/html' in request.headers.get('Accept', '')


class LoginObrigatorioMiddleware(LoginRequiredMiddleware):
    """Bloqueia o acesso de visitantes anônimos.

    Páginas redirecionam para a tela de login (com ?next=). Endpoints de dados
    chamados via fetch() recebem 401 em JSON, em vez de um redirecionamento
    para HTML que quebraria o parse da resposta.
    """

    def handle_no_permission(self, request, view_func):
        if request.method == 'GET' and _espera_html(request):
            return super().handle_no_permission(request, view_func)

        return JsonResponse(
            {'erro': 'Faça login para continuar.'},
            status=401,
            json_dumps_params={'ensure_ascii': False},
        )
