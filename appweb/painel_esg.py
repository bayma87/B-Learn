"""API consolidada do painel ESG (História 5).

Agrega serviços já existentes no projeto. As fontes atualmente disponíveis
são demonstrativas/simuladas; o serviço não inventa valores ausentes.
"""
import json
import logging
from pathlib import Path

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .comparativos import (
    anexar_ausencia_acompanhamento,
    carregar_acompanhamentos,
    montar_acompanhamento,
    validar_acompanhamentos,
)
from .consumo import carregar_dados_consumo, calcular_indicadores_consumo
from .equipamentos import carregar_dados_equipamentos, calcular_consumo_por_hora
from .models import AssessmentResult
from .recomendacoes import gerar_recomendacoes
from .residuos import calcular_resumo_residuos
from .social import calcular_indicadores_sociais
from .sugestoes import selecionar_sugestoes_orientadas

logger = logging.getLogger(__name__)
DADOS_DIR = Path(__file__).parent / "dados"


def _carregar_json(nome):
    try:
        return json.loads((DADOS_DIR / nome).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Não foi possível carregar {nome}.") from exc


def _governanca_e_historico():
    avaliacoes = list(AssessmentResult.objects.order_by("-created_at")[:10])

    def serializar(item):
        return {
            "pontuacao_ambiental": item.environmental_score,
            "pontuacao_social": item.social_score,
            "pontuacao_governanca": item.governance_score,
            "pontuacao_geral": item.overall_score,
            "pilar_com_menor_pontuacao": item.weakest_pillar,
            "data": item.created_at.isoformat() if item.created_at else None,
        }

    if not avaliacoes:
        return {
            "situacao": "sem_dados",
            "ultima_avaliacao": None,
            "historico": [],
        }

    return {
        "situacao": "avaliada",
        "ultima_avaliacao": serializar(avaliacoes[0]),
        "historico": [serializar(item) for item in reversed(avaliacoes)],
    }


def _priorizar_recomendacoes(recomendacoes, sugestoes_orientadas):
    evidencias_por_id = {
        item["id_acao"]: item for item in sugestoes_orientadas
    }
    ordem_financeira = {"Alta": 0, "Média": 1, "Baixa": 2}
    itens = []

    for recomendacao in recomendacoes:
        item = dict(recomendacao)
        evidencia = evidencias_por_id.get(item["id_acao"])
        investimento = item.get("investimento_sugerido", {})
        item["impacto_observado"] = (
            "evidencia_relacionada" if evidencia else "nao_mensurado"
        )
        item["justificativa_por_indicadores"] = (
            evidencia.get("justificativa") if evidencia else None
        )
        item["evidencias"] = (
            evidencia.get("evidencias", []) if evidencia else []
        )
        item["custo_recomendado"] = investimento.get("recomendado")
        item["viabilidade_financeira"] = {
            "prioridade_por_retorno": item.get("prioridade"),
            "payback_meses": item.get("payback_meses"),
            "payback_indisponivel": item.get("payback_indisponivel"),
        }
        itens.append(item)

    def chave(item):
        custo = item.get("custo_recomendado")
        return (
            0 if item["impacto_observado"] == "evidencia_relacionada" else 1,
            ordem_financeira.get(item.get("prioridade"), 3),
            float(custo) if custo is not None else float("inf"),
        )

    itens.sort(key=chave)
    for posicao, item in enumerate(itens, start=1):
        item["posicao_prioridade"] = posicao
    return itens


@require_GET
def painel_esg_api(request):
    """Retorna indicadores, resultados e recomendações em um único JSON."""
    try:
        consumo = calcular_indicadores_consumo(carregar_dados_consumo())
        equipamentos = calcular_consumo_por_hora(
            carregar_dados_equipamentos()
        )
        social = calcular_indicadores_sociais(_carregar_json("social.json"))
        residuos = calcular_resumo_residuos(_carregar_json("residuos.json"))
        recomendacoes = gerar_recomendacoes()

        sugestoes = selecionar_sugestoes_orientadas(
            recomendacoes, social, residuos
        )
        configuracoes = validar_acompanhamentos(carregar_acompanhamentos())
        ids_configurados = {
            item["id_acao"] for item in configuracoes
        }
        sugestoes_orientadas = [
            anexar_ausencia_acompanhamento(item, ids_configurados)
            for item in sugestoes["sugestoes_orientadas"]
        ]
        acompanhamento = montar_acompanhamento(
            configuracoes,
            {item["id_acao"]: item for item in recomendacoes},
        )
        recomendacoes_priorizadas = _priorizar_recomendacoes(
            recomendacoes, sugestoes_orientadas
        )
        governanca = _governanca_e_historico()

    except (OSError, UnicodeError, ValueError, KeyError):
        logger.exception("Erro ao consolidar o painel ESG.")
        return JsonResponse(
            {"erro": "Não foi possível consolidar os indicadores ESG."},
            status=500,
        )

    return JsonResponse(
        {
            "origem": "simulada",
            "atualizado_em": timezone.now().isoformat(),
            "indicadores": {
                "ambiental": {
                    "consumo": consumo,
                    "equipamentos": equipamentos,
                    "residuos": residuos,
                },
                "social": social,
                "governanca": governanca,
            },
            "resultados_acoes": acompanhamento,
            "recomendacoes": {
                "total": len(recomendacoes_priorizadas),
                "personalizada_por_indicadores": bool(sugestoes_orientadas),
                "criterios_priorizacao": [
                    "evidências dos indicadores disponíveis",
                    "prioridade por retorno financeiro estimado",
                    "menor custo recomendado em caso de empate",
                ],
                "itens": recomendacoes_priorizadas,
                "avaliacao_fontes": sugestoes["avaliacao_fontes"],
            },
            "observacoes": [
                "Os dados atuais são demonstrativos e simulados.",
                "Impactos sem evidência disponível são identificados como não mensurados.",
                "A prioridade financeira é uma estimativa e não substitui análise financeira.",
                "O histórico depende de avaliações registradas no banco de dados.",
            ],
        },
        json_dumps_params={"ensure_ascii": False},
    )
