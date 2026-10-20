import json
import logging
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET

from .forms import ContactMessageForm
from .consumo import (
    carregar_dados_consumo,
    calcular_indicadores_consumo,
)
from .comparativos import (
    anexar_ausencia_acompanhamento,
    carregar_acompanhamentos,
    montar_acompanhamento,
    validar_acompanhamentos,
)
from .equipamentos import (
    carregar_dados_equipamentos,
    calcular_consumo_por_hora,
)
from .models import RegistroResiduo
from .recomendacoes import gerar_recomendacoes
from .residuos import calcular_resumo_residuos
from .social import calcular_indicadores_sociais
from .sugestoes import selecionar_sugestoes_orientadas

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

def painel_residuos(request):
    resumo = RegistroResiduo.objects.aggregate(
        total_kg=Sum('quantidade_kg', default=0),
    )

    resumo_reciclado = RegistroResiduo.objects.filter(
        destino='reciclado',
    ).aggregate(
        reciclado_kg=Sum('quantidade_kg', default=0),
    )

    total_kg = resumo['total_kg']
    reciclado_kg = resumo_reciclado['reciclado_kg']
    nao_reciclado_kg = total_kg - reciclado_kg

    if total_kg > 0:
        taxa_reciclagem = (reciclado_kg / total_kg) * 100
    else:
        taxa_reciclagem = Decimal('0')

    contexto = {
        'total_kg': total_kg,
        'reciclado_kg': reciclado_kg,
        'nao_reciclado_kg': nao_reciclado_kg,
        'taxa_reciclagem': taxa_reciclagem,
    }

    return render(request, 'appweb/painel_residuos.html', contexto)

@require_GET
def resumo_residuos(request):
    caminho = (
        Path(settings.BASE_DIR)
        / 'appweb'
        / 'dados'
        / 'residuos.json'
    )

    try:
        dados = json.loads(caminho.read_text(encoding='utf-8'))
        resumo = calcular_resumo_residuos(dados)
    except (OSError, UnicodeError, ValueError):
        logger.exception('Erro ao processar os dados de resíduos.')

        return JsonResponse(
            {'erro': 'Não foi possível carregar os indicadores de resíduos.'},
            status=500,
        )

    return JsonResponse(
        resumo,
        json_dumps_params={'ensure_ascii': False},
    )

def painel_social(request):
    return render(request, 'appweb/social.html')


def painel_recomendacoes(request):
    return render(request, 'appweb/painel_recomendacoes.html')


def painel_consumo(request):
    return render(request, 'appweb/painel_consumo.html')


def painel_equipamentos(request):
    return render(request, 'appweb/painel_equipamentos.html')


@require_GET
def indicadores_sociais(request):
    caminho = (
        Path(settings.BASE_DIR)
        / 'appweb'
        / 'dados'
        / 'social.json'
    )

    try:
        dados = json.loads(caminho.read_text(encoding='utf-8'))
        indicadores = calcular_indicadores_sociais(dados)
    except (OSError, UnicodeError, ValueError):
        logger.exception('Erro ao processar os dados sociais.')

        return JsonResponse(
            {'erro': 'Não foi possível carregar os indicadores sociais.'},
            status=500,
        )

    return JsonResponse(
        indicadores,
        json_dumps_params={'ensure_ascii': False},
    )


@require_GET
def indicadores_consumo(request):
    try:
        dados = carregar_dados_consumo()
        indicadores = calcular_indicadores_consumo(dados)
    except ValueError:
        logger.exception('Erro ao processar os dados de consumo.')

        return JsonResponse(
            {'erro': 'Não foi possível carregar os indicadores de consumo.'},
            status=500,
        )

    return JsonResponse(
        indicadores,
        json_dumps_params={'ensure_ascii': False},
    )


@require_GET
def consumo_por_hora_equipamentos(request):
    try:
        dados = carregar_dados_equipamentos()
        indicadores = calcular_consumo_por_hora(dados)
    except ValueError:
        logger.exception('Erro ao processar os dados de equipamentos.')

        return JsonResponse(
            {'erro': 'Não foi possível carregar os indicadores de equipamentos.'},
            status=500,
        )

    return JsonResponse(
        indicadores,
        json_dumps_params={'ensure_ascii': False},
    )


def _carregar_indicadores_para_sugestoes():
    caminho_social = (
        Path(settings.BASE_DIR)
        / 'appweb'
        / 'dados'
        / 'social.json'
    )
    caminho_residuos = (
        Path(settings.BASE_DIR)
        / 'appweb'
        / 'dados'
        / 'residuos.json'
    )
    indicadores_social = calcular_indicadores_sociais(
        json.loads(caminho_social.read_text(encoding='utf-8'))
    )
    indicadores_residuos = calcular_resumo_residuos(
        json.loads(caminho_residuos.read_text(encoding='utf-8'))
    )
    return indicadores_social, indicadores_residuos


@require_GET
def recomendacoes_esg(request):
    try:
        recomendacoes = gerar_recomendacoes()
        indicadores_social, indicadores_residuos = (
            _carregar_indicadores_para_sugestoes()
        )
        sugestoes = selecionar_sugestoes_orientadas(
            recomendacoes,
            indicadores_social,
            indicadores_residuos,
        )
        acompanhamentos_config = validar_acompanhamentos(
            carregar_acompanhamentos()
        )
        ids_configurados = {
            config['id_acao'] for config in acompanhamentos_config
        }
        sugestoes_orientadas = [
            anexar_ausencia_acompanhamento(sugestao, ids_configurados)
            for sugestao in sugestoes['sugestoes_orientadas']
        ]
        acompanhamento = montar_acompanhamento(
            acompanhamentos_config,
            {item['id_acao']: item for item in recomendacoes},
        )
    except (OSError, UnicodeError, ValueError):
        logger.exception('Erro ao processar o catálogo de recomendações.')

        return JsonResponse(
            {'erro': 'Não foi possível carregar as recomendações.'},
            status=500,
        )

    return JsonResponse(
        {
            'origem': 'simulada',
            'total': len(recomendacoes),
            'personalizada_por_indicadores': False,
            'recomendacoes': recomendacoes,
            'sugestoes_orientadas': sugestoes_orientadas,
            'acompanhamento': acompanhamento,
            'avaliacao_fontes': sugestoes['avaliacao_fontes'],
        },
        json_dumps_params={'ensure_ascii': False},
    )
