"""Adaptador da atividade introdutória de interpretação de alertas.

A lógica de comparação pertence a ``microlearning.gatilho_ativo``. Este módulo
apenas:

- lê o catálogo validado existente;
- expõe poucos campos dos gatilhos para o seletor de cenários;
- valida o formato do exercício e a natureza da leitura por cenário;
- aplica a regra sobre uma cópia do gatilho;
- devolve a mensagem e a sugestão associadas no catálogo.

Não há persistência, pontuação, progresso, desafio concluído nem cálculo de
impacto. O cliente não informa limite, condição, unidade, mensagem nem
desafio: todos vêm do catálogo confiável.
"""

import copy
import re
from decimal import Decimal, InvalidOperation

from .microlearning import carregar_catalogo, gatilho_ativo


# Formato numérico e restrições por cenário são tratados separadamente abaixo:
# o formato do exercício e a natureza da medida definem a validação da leitura.
_NUMERO_RE = re.compile(r'(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,2})?\Z')

# Política de entrada da interface por natureza da medida. Limite e condição
# continuam vindo do catálogo; aqui só se decide que valores são informáveis.
POLITICAS_LEITURA = {
    'g1': {'permitir_negativo': False, 'maximo': None},
    'g2': {'permitir_negativo': False, 'maximo': None},
    'g3': {'permitir_negativo': False, 'maximo': None},
    'g4': {'permitir_negativo': False, 'maximo': Decimal('100')},
    'g5': {'permitir_negativo': True, 'maximo': None},
}

MENSAGEM_PAYLOAD = 'O corpo deve ser um objeto JSON.'
MENSAGEM_CENARIO = 'Selecione um cenário.'
MENSAGEM_CENARIO_INEXISTENTE = 'Cenário inexistente.'
MENSAGEM_LEITURA_OBRIGATORIA = 'Informe a leitura do sensor.'
MENSAGEM_LEITURA_TIPO = (
    'Informe a leitura como texto, usando ponto decimal (exemplo: 1.80).'
)
MENSAGEM_LEITURA_FORMATO = (
    'Formato do exercício: use até 8 dígitos inteiros e no máximo 2 casas '
    'decimais, com ponto decimal e sem separador de milhar ou notação '
    'científica (exemplo: 1.80).'
)
MENSAGEM_LEITURA_NEGATIVA = (
    'Para a medida "{unidade}", informe um valor não negativo.'
)
MENSAGEM_LEITURA_PERCENTUAL = (
    'Para a medida "{unidade}", informe um valor entre 0 e 100, inclusive.'
)

LIMITES = [
    'Cenário e limite demonstrativos; não representam norma técnica ou limite legal.',
    'O alerta pede interpretação e não comprova a causa da leitura.',
    'A atividade não executa ação nem calcula impacto, economia, emissões ou risco.',
    'A decisão depende de avaliação humana.',
]


def _catalogo():
    # carregar_catalogo() já retorna o resultado de validar_catalogo().
    return carregar_catalogo()


def carregar_cenarios():
    """Lista os gatilhos expostos, sem mensagens, desafios ou gabaritos."""
    catalogo = _catalogo()

    return [
        {
            'id': gatilho['id'],
            'sensor': gatilho['sensor'],
            'local': gatilho['local'],
            'unidade': gatilho['unidade'],
            'leitura': f"{gatilho['leitura']:.2f}",
            'limite': f"{gatilho['limite']:.2f}",
            'condicao': gatilho['condicao'],
        }
        for gatilho in catalogo['gatilhos']
    ]


def _parse_leitura(valor, gatilho):
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        raise ValueError(MENSAGEM_LEITURA_OBRIGATORIA)

    if not isinstance(valor, str):
        raise ValueError(MENSAGEM_LEITURA_TIPO)

    texto = valor.strip()
    politica = POLITICAS_LEITURA[gatilho['id']]
    permitir_negativo = politica['permitir_negativo']

    if texto.startswith('-') and not permitir_negativo:
        raise ValueError(
            MENSAGEM_LEITURA_NEGATIVA.format(unidade=gatilho['unidade'])
        )

    # O formato do exercício é verificado sem arredondar: no máximo 8 dígitos
    # inteiros e 0 a 2 casas decimais. O sinal permitido não conta como dígito.
    candidato = texto[1:] if permitir_negativo and texto.startswith('-') else texto
    if not _NUMERO_RE.fullmatch(candidato):
        raise ValueError(MENSAGEM_LEITURA_FORMATO)

    try:
        numero = Decimal(texto)
    except InvalidOperation:
        raise ValueError(MENSAGEM_LEITURA_FORMATO) from None

    if not numero.is_finite():
        raise ValueError(MENSAGEM_LEITURA_FORMATO)

    if not permitir_negativo and numero < 0:
        raise ValueError(
            MENSAGEM_LEITURA_NEGATIVA.format(unidade=gatilho['unidade'])
        )

    maximo = politica['maximo']
    if maximo is not None and numero > maximo:
        raise ValueError(
            MENSAGEM_LEITURA_PERCENTUAL.format(unidade=gatilho['unidade'])
        )

    return numero


def _explicacao(gatilho, leitura, ativo):
    comparador = 'acima de' if gatilho['condicao'] == 'acima' else 'abaixo de'
    relacao = 'está' if ativo else 'não está'
    return (
        f"A leitura de {leitura:.2f} {gatilho['unidade']} {relacao} "
        f"{comparador} {gatilho['limite']:.2f} {gatilho['unidade']} "
        'definido neste cenário.'
    )


def processar(payload):
    """Interpreta a leitura enviada.

    Devolve ``(resultado, erros)``. Exceções de carregamento do catálogo são
    propagadas para a view decidir como responder sem expor detalhes internos.
    """
    if not isinstance(payload, dict):
        return None, {'payload': MENSAGEM_PAYLOAD}

    erros = {}
    cenario_id = payload.get('cenario_id')
    leitura = payload.get('leitura')

    if not isinstance(cenario_id, str) or not cenario_id.strip():
        erros['cenario_id'] = MENSAGEM_CENARIO
    if leitura is None or (isinstance(leitura, str) and not leitura.strip()):
        erros['leitura'] = MENSAGEM_LEITURA_OBRIGATORIA
    if erros:
        return None, erros

    catalogo = _catalogo()
    gatilho = next(
        (item for item in catalogo['gatilhos'] if item['id'] == cenario_id.strip()),
        None,
    )
    if gatilho is None:
        return None, {'cenario_id': MENSAGEM_CENARIO_INEXISTENTE}

    try:
        valor = _parse_leitura(leitura, gatilho)
    except ValueError as exc:
        return None, {'leitura': str(exc)}

    copia = copy.deepcopy(gatilho)
    copia['leitura'] = valor
    ativo = gatilho_ativo(copia)

    desafio = next(
        item for item in catalogo['desafios']
        if item['id'] == gatilho['desafio_id']
    )

    resultado = {
        'situacao': 'ativado' if ativo else 'nao_ativado',
        'titulo': (
            'Alerta ativado pela regra do cenário' if ativo
            else 'Alerta não ativado pela regra do cenário'
        ),
        'explicacao': _explicacao(gatilho, valor, ativo),
        'cenario': {
            'id': gatilho['id'],
            'sensor': gatilho['sensor'],
            'local': gatilho['local'],
            'unidade': gatilho['unidade'],
            'leitura': f'{valor:.2f}',
            'limite': f"{gatilho['limite']:.2f}",
            'condicao': gatilho['condicao'],
        },
        'mensagem': gatilho['mensagem'] if ativo else None,
        'sugestao': (
            {
                'id': desafio['id'],
                'titulo': desafio['titulo'],
                'rotulo': 'Sugestão para avaliar',
            }
            if ativo else None
        ),
        'nota_inativa': (
            None if ativo else
            'A leitura não satisfez esta regra; isso não comprova ausência de '
            'outros problemas.'
        ),
        'limites': list(LIMITES),
    }
    return resultado, {}
