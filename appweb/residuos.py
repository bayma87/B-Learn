import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


DESTINOS_VALIDOS = {'reciclado', 'nao_reciclado'}


def validar_dados_residuos(dados):
    if not isinstance(dados, dict):
        raise ValueError('A entrada deve ser um objeto JSON.')

    if type(dados.get('versao')) is not int or dados['versao'] != 1:
        raise ValueError('A versão deve ser o número inteiro 1.')

    if dados.get('origem') != 'simulada':
        raise ValueError('Esta versão aceita apenas origem simulada.')

    registros = dados.get('registros')

    if not isinstance(registros, list) or not registros:
        raise ValueError('Informe uma lista não vazia de registros.')

    validados = []
    identificadores = set()

    for posicao, registro in enumerate(registros, start=1):
        if not isinstance(registro, dict):
            raise ValueError(f'Registro {posicao}: formato inválido.')

        identificador = registro.get('id_leitura')
        local = registro.get('local')
        data_texto = registro.get('data')
        quantidade_texto = registro.get('quantidade_kg')
        destino = registro.get('destino')

        if not isinstance(identificador, str) or not identificador.strip():
            raise ValueError(f'Registro {posicao}: id_leitura obrigatório.')

        identificador = identificador.strip()

        if identificador in identificadores:
            raise ValueError(f'Identificador repetido: {identificador}.')

        if not isinstance(local, str) or not 1 <= len(local.strip()) <= 100:
            raise ValueError(f'Registro {posicao}: local inválido.')

        if not isinstance(data_texto, str):
            raise ValueError(f'Registro {posicao}: data obrigatória.')

        try:
            data_registro = date.fromisoformat(data_texto)
        except ValueError:
            raise ValueError(f'Registro {posicao}: data inválida.') from None

        if data_registro.isoformat() != data_texto:
            raise ValueError(f'Registro {posicao}: use data AAAA-MM-DD.')

        if not isinstance(quantidade_texto, str):
            raise ValueError(f'Registro {posicao}: quantidade deve ser texto.')

        if not re.fullmatch(r'[0-9]{1,8}\.[0-9]{2}', quantidade_texto):
            raise ValueError(
                f'Registro {posicao}: quantidade inválida. '
                'Use um valor não negativo, como 12.50, '
                'com até oito dígitos antes do ponto.'
            )

        if not isinstance(destino, str) or destino not in DESTINOS_VALIDOS:
            raise ValueError(f'Registro {posicao}: destino desconhecido.')

        identificadores.add(identificador)

        validados.append({
            'id_leitura': identificador,
            'data': data_registro,
            'local': local.strip(),
            'quantidade_kg': Decimal(quantidade_texto),
            'destino': destino,
        })

    return validados

def _resumir_grupo(registros):
    total = sum(
        (registro['quantidade_kg'] for registro in registros),
        Decimal('0'),
    )

    reciclado = sum(
        (
            registro['quantidade_kg']
            for registro in registros
            if registro['destino'] == 'reciclado'
        ),
        Decimal('0'),
    )

    nao_reciclado = total - reciclado

    taxa = (reciclado / total) * 100 if total > 0 else Decimal('0')
    taxa = taxa.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    return {
        'total_kg': f'{total:.2f}',
        'reciclado_kg': f'{reciclado:.2f}',
        'nao_reciclado_kg': f'{nao_reciclado:.2f}',
        'taxa_reciclagem': str(taxa),
        'tem_quantidade': total > 0,
    }


def calcular_resumo_residuos(dados):
    registros = validar_dados_residuos(dados)

    por_dia = {}
    por_mes = {}

    for registro in registros:
        dia = registro['data'].isoformat()
        mes = dia[:7]

        por_dia.setdefault(dia, []).append(registro)
        por_mes.setdefault(mes, []).append(registro)

    return {
        'origem': dados['origem'],
        'unidade': 'kg',
        'total': _resumir_grupo(registros),
        'por_dia': [
            {'data': dia, **_resumir_grupo(por_dia[dia])}
            for dia in sorted(por_dia)
        ],
        'por_mes': [
            {'mes': mes, **_resumir_grupo(por_mes[mes])}
            for mes in sorted(por_mes)
        ],
    }