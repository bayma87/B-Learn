import re
from datetime import date
from decimal import Decimal


TIPOS_VALIDOS = {'alerta_seguranca', 'uso_equipamento'}


def status_seguranca(alertas):
    if type(alertas) is not int or alertas < 0:
        raise ValueError(
            'A quantidade de alertas deve ser inteira e não negativa.'
        )

   
    if alertas == 0:
        return 'verde'
    if alertas <= 3:
        return 'amarelo'
    return 'vermelho'


def validar_dados_sociais(dados):
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
        tipo = registro.get('tipo')
        data_texto = registro.get('data')

        if not isinstance(identificador, str) or not identificador.strip():
            raise ValueError(f'Registro {posicao}: id_leitura obrigatório.')

        identificador = identificador.strip()

        if identificador in identificadores:
            raise ValueError(f'Identificador repetido: {identificador}.')

        if not isinstance(local, str) or not 1 <= len(local.strip()) <= 100:
            raise ValueError(f'Registro {posicao}: local inválido.')

        if not isinstance(tipo, str) or tipo not in TIPOS_VALIDOS:
            raise ValueError(f'Registro {posicao}: tipo desconhecido.')

        try:
            data_registro = date.fromisoformat(data_texto)
        except (TypeError, ValueError):
            raise ValueError(f'Registro {posicao}: data inválida.') from None

        if data_registro.isoformat() != data_texto:
            raise ValueError(f'Registro {posicao}: use data AAAA-MM-DD.')

        horas = Decimal('0')
        equipamento = None

        if tipo == 'uso_equipamento':
            equipamento = registro.get('equipamento')
            horas_texto = registro.get('horas_uso')

            if (
                not isinstance(equipamento, str)
                or not 1 <= len(equipamento.strip()) <= 100
            ):
                raise ValueError(f'Registro {posicao}: equipamento inválido.')

            if (
                not isinstance(horas_texto, str)
                or not re.fullmatch(r'[0-9]{1,2}\.[0-9]{2}', horas_texto)
            ):
                raise ValueError(f'Registro {posicao}: use horas como 2.50.')

            horas = Decimal(horas_texto)

            if horas > 24:
                raise ValueError(
                    f'Registro {posicao}: máximo de 24 horas por evento.'
                )

            equipamento = equipamento.strip()

        elif 'horas_uso' in registro or 'equipamento' in registro:
            raise ValueError(
                f'Registro {posicao}: alerta não deve conter dados de uso.'
            )

        identificadores.add(identificador)

        validados.append({
            'id_leitura': identificador,
            'data': data_registro,
            'local': local.strip(),
            'tipo': tipo,
            'equipamento': equipamento,
            'horas_uso': horas,
        })

    return validados


def _resumir_grupo_social(registros):
    alertas = sum(
        registro['tipo'] == 'alerta_seguranca'
        for registro in registros
    )

    horas = sum(
        (registro['horas_uso'] for registro in registros),
        Decimal('0'),
    )

    return {
        'alertas_seguranca': alertas,
        'horas_uso': f'{horas:.2f}',
        'status': status_seguranca(alertas),
    }


def calcular_indicadores_sociais(dados):
    registros = validar_dados_sociais(dados)

    por_dia = {}
    por_mes = {}

    for registro in registros:
        dia = registro['data'].isoformat()
        mes = dia[:7]

        por_dia.setdefault(dia, []).append(registro)
        por_mes.setdefault(mes, []).append(registro)

    return {
        'origem': dados['origem'],
        'unidade_horas': 'h',
        'total': _resumir_grupo_social(registros),
        'por_dia': [
            {'data': dia, **_resumir_grupo_social(por_dia[dia])}
            for dia in sorted(por_dia)
        ],
        'por_mes': [
            {'mes': mes, **_resumir_grupo_social(por_mes[mes])}
            for mes in sorted(por_mes)
        ],
    }