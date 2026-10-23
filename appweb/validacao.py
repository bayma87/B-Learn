import re
from datetime import date
from decimal import Decimal


PADRAO_DECIMAL = re.compile(r'[0-9]{1,8}(\.[0-9]{1,2})?')


def validar_cabecalho(dados):
    if not isinstance(dados, dict):
        raise ValueError('A entrada deve ser um objeto JSON.')

    if type(dados.get('versao')) is not int or dados['versao'] != 1:
        raise ValueError('A versão deve ser o número inteiro 1.')

    if dados.get('origem') != 'simulada':
        raise ValueError('Esta versão aceita apenas origem simulada.')


def ler_lista(dados, campo, permitir_vazia=False):
    lista = dados.get(campo)

    if not isinstance(lista, list) or (not lista and not permitir_vazia):
        raise ValueError(f'{campo}: informe uma lista não vazia.')

    for posicao, item in enumerate(lista, start=1):
        if not isinstance(item, dict):
            raise ValueError(f'{campo} {posicao}: formato inválido.')

    return lista


def ler_texto(registro, campo, maximo=200):
    valor = registro.get(campo)

    if not isinstance(valor, str) or not 1 <= len(valor.strip()) <= maximo:
        raise ValueError(f'Campo {campo} inválido.')

    return valor.strip()


def ler_decimal(registro, campo, positivo=False):
    valor = registro.get(campo)

    if not isinstance(valor, str) or not PADRAO_DECIMAL.fullmatch(valor):
        raise ValueError(
            f'Campo {campo} inválido. Use texto numérico não negativo, '
            'como 12.50.'
        )

    numero = Decimal(valor)

    if positivo and numero <= 0:
        raise ValueError(f'Campo {campo} deve ser maior que zero.')

    return numero


def ler_inteiro(registro, campo, minimo=0):
    valor = registro.get(campo)

    if type(valor) is not int or valor < minimo:
        raise ValueError(f'Campo {campo} deve ser inteiro >= {minimo}.')

    return valor


def ler_data(registro, campo):
    valor = registro.get(campo)

    try:
        data = date.fromisoformat(valor)
    except (TypeError, ValueError):
        raise ValueError(f'Campo {campo} inválido.') from None

    if data.isoformat() != valor:
        raise ValueError(f'Campo {campo}: use data AAAA-MM-DD.')

    return data


def registrar_identificador(registro, usados):
    identificador = ler_texto(registro, 'id', maximo=50)

    if identificador in usados:
        raise ValueError(f'Identificador repetido: {identificador}.')

    usados.add(identificador)
    return identificador
