import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.conf import settings

from .validacao import (
    PADRAO_DECIMAL,
    ler_data,
    ler_decimal,
    ler_inteiro,
    ler_lista,
    ler_texto,
    registrar_identificador,
    validar_cabecalho,
)


TIPOS_PRODUTO = {'ecologico', 'tradicional'}

# Premissas do protótipo, exibidas na tela para não esconder a conta.
HORIZONTE_MESES = 60
TARIFA_KWH = Decimal('0.90')
REF_ENERGIA_KWH_UNIDADE = Decimal('10')
REF_EMISSOES_KG_UNIDADE = Decimal('5')
NOTA_ALTA = 70
NOTA_BAIXA = 40


def carregar_dados_fornecedores():
    caminho = (
        Path(settings.BASE_DIR)
        / 'appweb'
        / 'dados'
        / 'fornecedores.json'
    )
    return validar_dados_fornecedores(
        json.loads(caminho.read_text(encoding='utf-8'))
    )


def _validar_leitura(registro):
    leitura = {
        'data': ler_data(registro, 'data'),
        'unidades': ler_inteiro(registro, 'unidades_produzidas', minimo=1),
        'energia': ler_decimal(registro, 'energia_kwh'),
        'renovavel': ler_decimal(registro, 'energia_renovavel_kwh'),
        'residuos': ler_decimal(registro, 'residuos_kg'),
        'reciclado': ler_decimal(registro, 'residuos_reciclados_kg'),
        'emissoes': ler_decimal(registro, 'emissoes_kg'),
    }

    if leitura['renovavel'] > leitura['energia']:
        raise ValueError('Energia renovável maior que a energia total.')

    if leitura['reciclado'] > leitura['residuos']:
        raise ValueError('Resíduo reciclado maior que o resíduo total.')

    return leitura


def _validar_auditoria(registro):
    auditoria = registro.get('auditoria')

    if not isinstance(auditoria, dict) or type(auditoria.get('auditado')) is not bool:
        raise ValueError('Auditoria inválida.')

    if not auditoria['auditado']:
        return {'auditado': False, 'auditor': None, 'data': None}

    return {
        'auditado': True,
        'auditor': ler_texto(auditoria, 'auditor', maximo=100),
        'data': ler_data(auditoria, 'data'),
    }


def _validar_fornecedor(registro, ids):
    alegacao = registro.get('alegacao_sustentavel')

    if type(alegacao) is not bool:
        raise ValueError('alegacao_sustentavel deve ser verdadeiro ou falso.')

    return {
        'id': registrar_identificador(registro, ids),
        'nome': ler_texto(registro, 'nome', maximo=100),
        'cidade': ler_texto(registro, 'cidade', maximo=100),
        'alegacao_sustentavel': alegacao,
        'auditoria': _validar_auditoria(registro),
        'telemetria': [
            _validar_leitura(r) for r in ler_lista(registro, 'telemetria')
        ],
    }


def _validar_produto(registro, ids, ids_fornecedores):
    fornecedor_id = ler_texto(registro, 'fornecedor_id', maximo=50)
    tipo = registro.get('tipo')

    if fornecedor_id not in ids_fornecedores:
        raise ValueError(f'Fornecedor inexistente: {fornecedor_id}.')

    if tipo not in TIPOS_PRODUTO:
        raise ValueError('Tipo de produto desconhecido.')

    return {
        'id': registrar_identificador(registro, ids),
        'fornecedor_id': fornecedor_id,
        'nome': ler_texto(registro, 'nome', maximo=100),
        'categoria': ler_texto(registro, 'categoria', maximo=50),
        'tipo': tipo,
        'preco': ler_decimal(registro, 'preco', positivo=True),
        'durabilidade': ler_inteiro(registro, 'durabilidade_meses', minimo=1),
        'consumo': ler_decimal(registro, 'consumo_kwh_mes'),
    }


def validar_dados_fornecedores(dados):
    validar_cabecalho(dados)

    ids = set()
    fornecedores = [
        _validar_fornecedor(r, ids) for r in ler_lista(dados, 'fornecedores')
    ]
    ids_produtos = set()
    produtos = [
        _validar_produto(r, ids_produtos, ids)
        for r in ler_lista(dados, 'produtos')
    ]

    return fornecedores, produtos


def _um_decimal(valor):
    return valor.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


def _duas_casas(valor):
    return valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _nota_inversa(valor, referencia):
    nota = (1 - valor / referencia) * 100
    return max(Decimal('0'), min(Decimal('100'), nota))


def _nivel(nota):
    if nota >= NOTA_ALTA:
        return 'alta'
    if nota >= NOTA_BAIXA:
        return 'media'
    return 'baixa'


def avaliar_fornecedor(fornecedor):
    """Nota ESG (0-100) calculada a partir da telemetria da fábrica."""
    leituras = fornecedor['telemetria']
    unidades = sum(r['unidades'] for r in leituras)
    energia = sum((r['energia'] for r in leituras), Decimal('0'))
    renovavel = sum((r['renovavel'] for r in leituras), Decimal('0'))
    residuos = sum((r['residuos'] for r in leituras), Decimal('0'))
    reciclado = sum((r['reciclado'] for r in leituras), Decimal('0'))
    emissoes = sum((r['emissoes'] for r in leituras), Decimal('0'))

    energia_unidade = energia / unidades
    emissoes_unidade = emissoes / unidades
    pct_renovavel = renovavel / energia * 100 if energia > 0 else Decimal('0')
    # Sem resíduos não há o que reciclar: não penaliza o fornecedor.
    pct_reciclagem = reciclado / residuos * 100 if residuos > 0 else Decimal('100')

    nota = round(
        (
            _nota_inversa(energia_unidade, REF_ENERGIA_KWH_UNIDADE)
            + pct_renovavel
            + pct_reciclagem
            + _nota_inversa(emissoes_unidade, REF_EMISSOES_KG_UNIDADE)
        ) / 4
    )
    auditado = fornecedor['auditoria']['auditado']

    alertas = []
    if fornecedor['alegacao_sustentavel'] and not auditado:
        alertas.append(
            'Diz ser sustentável, mas os dados não foram auditados. '
            'Risco de greenwashing.'
        )
    if fornecedor['alegacao_sustentavel'] and nota < NOTA_BAIXA:
        alertas.append(
            'Diz ser sustentável, mas a telemetria mostra desempenho baixo. '
            'Risco de greenwashing.'
        )

    return {
        'id': fornecedor['id'],
        'nome': fornecedor['nome'],
        'cidade': fornecedor['cidade'],
        'alegacao_sustentavel': fornecedor['alegacao_sustentavel'],
        'auditado': auditado,
        'auditor': fornecedor['auditoria']['auditor'],
        'data_auditoria': (
            fornecedor['auditoria']['data'].isoformat() if auditado else None
        ),
        'ultima_leitura': max(r['data'] for r in leituras).isoformat(),
        'nota_esg': nota,
        'nivel': _nivel(nota),
        'indicadores': {
            'energia_kwh_por_unidade': str(_duas_casas(energia_unidade)),
            'energia_renovavel_pct': str(_um_decimal(pct_renovavel)),
            'reciclagem_pct': str(_um_decimal(pct_reciclagem)),
            'emissoes_kg_por_unidade': str(_duas_casas(emissoes_unidade)),
        },
        'alertas': alertas,
    }


def calcular_custo_produto(produto):
    """Custo por mês de uso e no horizonte (compra diluída + energia)."""
    custo_compra_mes = produto['preco'] / produto['durabilidade']
    custo_energia_mes = produto['consumo'] * TARIFA_KWH
    custo_mes = custo_compra_mes + custo_energia_mes

    return {
        'id': produto['id'],
        'fornecedor_id': produto['fornecedor_id'],
        'nome': produto['nome'],
        'categoria': produto['categoria'],
        'tipo': produto['tipo'],
        'preco': str(_duas_casas(produto['preco'])),
        'durabilidade_meses': produto['durabilidade'],
        'consumo_kwh_mes': str(_duas_casas(produto['consumo'])),
        'custo_mensal': str(_duas_casas(custo_mes)),
        'custo_horizonte': str(_duas_casas(custo_mes * HORIZONTE_MESES)),
        'compras_no_horizonte': str(
            _um_decimal(Decimal(HORIZONTE_MESES) / produto['durabilidade'])
        ),
        '_custo_mes': custo_mes,
        '_produto': produto,
    }


def _publico(produto_calculado):
    return {
        k: v for k, v in produto_calculado.items() if not k.startswith('_')
    }


def _melhor(produtos, tipo):
    candidatos = [p for p in produtos if p['tipo'] == tipo]
    return min(
        candidatos,
        key=lambda p: (p['_custo_mes'], p['id']),
        default=None,
    )


def comparar_categoria(categoria, produtos):
    eco = _melhor(produtos, 'ecologico')
    trad = _melhor(produtos, 'tradicional')

    if eco is None or trad is None:
        return None

    economia_mes = trad['_custo_mes'] - eco['_custo_mes']
    energia_evitada = (
        (trad['_produto']['consumo'] - eco['_produto']['consumo'])
        * HORIZONTE_MESES
    )
    compras_evitadas = (
        Decimal(HORIZONTE_MESES) / trad['_produto']['durabilidade']
        - Decimal(HORIZONTE_MESES) / eco['_produto']['durabilidade']
    )

    return {
        'categoria': categoria,
        'ecologico': _publico(eco),
        'tradicional': _publico(trad),
        'economia_horizonte': str(_duas_casas(economia_mes * HORIZONTE_MESES)),
        'economia_pct': str(_um_decimal(economia_mes / trad['_custo_mes'] * 100)),
        'energia_evitada_kwh': str(_duas_casas(energia_evitada)),
        'compras_evitadas': str(_um_decimal(compras_evitadas)),
        'ecologico_compensa': economia_mes > 0,
    }


def interpretar_filtros(parametros):
    """Converte a query string em filtros validados (ValueError se inválida)."""
    categoria = parametros.get('categoria', '').strip()

    if len(categoria) > 50:
        raise ValueError('Categoria inválida.')

    texto_nota = parametros.get('nota_minima', '0').strip() or '0'
    if not texto_nota.isascii() or not texto_nota.isdigit() or int(texto_nota) > 100:
        raise ValueError('A nota mínima deve ser um inteiro de 0 a 100.')

    texto_preco = parametros.get('preco_maximo', '').strip()
    if texto_preco and not PADRAO_DECIMAL.fullmatch(texto_preco):
        raise ValueError('O preço máximo deve ser um número não negativo.')

    auditados = parametros.get('somente_auditados', 'true').strip().lower()
    if auditados not in {'true', 'false'}:
        raise ValueError('somente_auditados deve ser true ou false.')

    return {
        'categoria': categoria or None,
        'nota_minima': int(texto_nota),
        'preco_maximo': Decimal(texto_preco) if texto_preco else None,
        'somente_auditados': auditados == 'true',
    }


def consultar_catalogo(fornecedores, produtos, filtros):
    avaliacoes = {f['id']: avaliar_fornecedor(f) for f in fornecedores}
    calculados = [calcular_custo_produto(p) for p in produtos]

    def produto_visivel(produto):
        return (
            (not filtros['categoria'] or produto['categoria'] == filtros['categoria'])
            and (
                filtros['preco_maximo'] is None
                or produto['_produto']['preco'] <= filtros['preco_maximo']
            )
        )

    def fornecedor_visivel(avaliacao):
        return (
            avaliacao['nota_esg'] >= filtros['nota_minima']
            and (avaliacao['auditado'] or not filtros['somente_auditados'])
        )

    resultado = []
    visiveis = []

    for avaliacao in sorted(
        avaliacoes.values(), key=lambda a: (-a['nota_esg'], a['nome'])
    ):
        if not fornecedor_visivel(avaliacao):
            continue

        do_fornecedor = [
            p for p in calculados
            if p['fornecedor_id'] == avaliacao['id'] and produto_visivel(p)
        ]

        if do_fornecedor:
            visiveis.extend(do_fornecedor)
            resultado.append(
                {**avaliacao, 'produtos': [_publico(p) for p in do_fornecedor]}
            )

    categorias = sorted({p['categoria'] for p in visiveis})

    return {
        'origem': 'simulada',
        'premissas': {
            'horizonte_meses': HORIZONTE_MESES,
            'tarifa_kwh': str(TARIFA_KWH),
        },
        'categorias_disponiveis': sorted({p['categoria'] for p in produtos}),
        'total': len(resultado),
        'fornecedores': resultado,
        'comparativos': [
            comparacao
            for categoria in categorias
            if (
                comparacao := comparar_categoria(
                    categoria,
                    [p for p in visiveis if p['categoria'] == categoria],
                )
            )
        ],
    }
