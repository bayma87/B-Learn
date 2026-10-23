import json
import logging

from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET, require_POST

from .forms import ContactMessageForm
from .fornecedores import (
    carregar_dados_fornecedores,
    consultar_catalogo,
    interpretar_filtros,
)
from .microlearning import (
    calcular_progresso,
    carregar_catalogo,
    montar_painel,
    registrar_resposta,
)

logger = logging.getLogger(__name__)


QUESTIONS = [
    {'id': 'e1', 'pillar': 'Ambiental', 'text': 'A empresa monitora mensamente o consumo de energia e água?', 'weight': 1},
    {'id': 'e2', 'pillar': 'Ambiental', 'text': 'Há gestão de resíduos e percentual de reciclagem?', 'weight': 1},
    {'id': 'e3', 'pillar': 'Ambiental', 'text': 'Existem políticas para reduzir emissões e desperdícios?', 'weight': 1},
    {'id': 's1', 'pillar': 'Social', 'text': 'A empresa possui políticas de diversidade, inclusão e bem-estar?', 'weight': 1},
    {'id': 's2', 'pillar': 'Social', 'text': 'Há treinamento e capacitação de colaboradores com frequência?', 'weight': 1},
    {'id': 's3', 'pillar': 'Social', 'text': 'A organização acompanha a segurança, saúde e engajamento da equipe?', 'weight': 1},
    {'id': 'g1', 'pillar': 'Governança', 'text': 'Existe código de ética e canais de denúncia claros?', 'weight': 1},
    {'id': 'g2', 'pillar': 'Governança', 'text': 'A empresa define metas de sustentabilidade e acompanhamento de risco?', 'weight': 1},
    {'id': 'g3', 'pillar': 'Governança', 'text': 'Há transparência e prestação de contas para a liderança e stakeholders?', 'weight': 1},
]

PILLAR_ORDER = ['Ambiental', 'Social', 'Governança']


def calculate_scores(answer_map):
    scores = {pillar: 0 for pillar in PILLAR_ORDER}
    totals = {pillar: 0 for pillar in PILLAR_ORDER}

    for question in QUESTIONS:
        response = int(answer_map.get(question['id'], 0))
        scores[question['pillar']] += response
        totals[question['pillar']] += 2

    pillar_scores = {}
    for pillar in PILLAR_ORDER:
        if totals[pillar] == 0:
            pillar_scores[pillar] = 0
        else:
            pillar_scores[pillar] = round((scores[pillar] / totals[pillar]) * 100)

    overall_score = round(sum(pillar_scores.values()) / len(PILLAR_ORDER))
    weakest_pillar = min(pillar_scores, key=pillar_scores.get)

    return pillar_scores, overall_score, weakest_pillar


def get_recommendations(weakest_pillar):
    recommendations = {
        'Ambiental': [
            'Implementar indicadores mensais de consumo de energia, água e resíduos.',
            'Definir plano de redução de desperdícios e aumentar a reciclagem.',
            'Estabelecer metas de eficiência ambiental para produção e logística.',
        ],
        'Social': [
            'Reforçar políticas de inclusão, bem-estar e capacitação dos colaboradores.',
            'Implementar diagnóstico de clima organizacional e ações de engajamento.',
            'Padronizar treinamentos em saúde, segurança e desenvolvimento profissional.',
        ],
        'Governança': [
            'Atualizar código de ética, políticas internas e canais de denúncia.',
            'Estabelecer KPIs de sustentabilidade para a liderança e reuniões do conselho.',
            'Criar rotina de governança ESG com indicadores e rastreio de riscos.',
        ],
    }
    return recommendations.get(weakest_pillar, recommendations['Governança'])


def home(request):
    return render(request, 'appweb/home.html')


def quem_somos(request):
    if request.method == 'POST':
        form = ContactMessageForm(request.POST)
        if form.is_valid():
            try:
                form.save()
            except Exception:
                logger.exception('Erro ao salvar mensagem de contato.')
                return render(request, 'appweb/quem_somos.html', {
                    'form': form,
                    'error_message': 'Não foi possível enviar sua pergunta no momento. Tente novamente em alguns minutos.'
                })

            return render(request, 'appweb/quem_somos.html', {
                'form': ContactMessageForm(),
                'success_message': 'Pergunta enviada com sucesso! Nossa equipe responderá em breve.'
            })
    else:
        form = ContactMessageForm()

    return render(request, 'appweb/quem_somos.html', {'form': form})


def _concluidos_da_sessao(request):
    concluidos = request.session.get('microlearning', [])

    if not isinstance(concluidos, list):
        return set()

    return {item for item in concluidos if isinstance(item, str)}


def painel_microlearning(request):
    return render(request, 'appweb/microlearning.html')


@require_GET
def dados_microlearning(request):
    try:
        catalogo = carregar_catalogo()
    except (OSError, UnicodeError, ValueError):
        logger.exception('Erro ao processar o catálogo de microlearning.')

        return JsonResponse(
            {'erro': 'Não foi possível carregar o conteúdo de aprendizado.'},
            status=500,
        )

    return JsonResponse(
        montar_painel(catalogo, _concluidos_da_sessao(request)),
        json_dumps_params={'ensure_ascii': False},
    )


@require_POST
def responder_microlearning(request):
    try:
        catalogo = carregar_catalogo()
    except (OSError, UnicodeError, ValueError):
        logger.exception('Erro ao processar o catálogo de microlearning.')

        return JsonResponse(
            {'erro': 'Não foi possível carregar o conteúdo de aprendizado.'},
            status=500,
        )

    try:
        corpo = json.loads(request.body)

        if not isinstance(corpo, dict):
            raise ValueError('O corpo deve ser um objeto JSON.')

        resultado, concluidos = registrar_resposta(
            catalogo,
            _concluidos_da_sessao(request),
            corpo.get('id'),
            corpo.get('resposta'),
        )
    except ValueError as erro:
        return JsonResponse(
            {'erro': str(erro)},
            status=400,
            json_dumps_params={'ensure_ascii': False},
        )

    request.session['microlearning'] = sorted(concluidos)

    return JsonResponse(
        {
            'resultado': resultado,
            'progresso': calcular_progresso(catalogo, concluidos),
        },
        json_dumps_params={'ensure_ascii': False},
    )


def painel_fornecedores(request):
    return render(request, 'appweb/fornecedores.html')


@require_GET
def dados_fornecedores(request):
    try:
        filtros = interpretar_filtros(request.GET)
    except ValueError as erro:
        return JsonResponse(
            {'erro': str(erro)},
            status=400,
            json_dumps_params={'ensure_ascii': False},
        )

    try:
        fornecedores, produtos = carregar_dados_fornecedores()
    except (OSError, UnicodeError, ValueError):
        logger.exception('Erro ao processar os dados de fornecedores.')

        return JsonResponse(
            {'erro': 'Não foi possível carregar o catálogo de fornecedores.'},
            status=500,
        )

    return JsonResponse(
        consultar_catalogo(fornecedores, produtos, filtros),
        json_dumps_params={'ensure_ascii': False},
    )
