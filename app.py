from flask import Flask, jsonify
import csv
import statistics
import os

app = Flask(__name__)

# Ficheiro comum de dados simulados
ARQUIVO_CSV = 'dados_exemplo.csv'

def ler_dados_consumo():
    leituras = []
    if os.path.exists(ARQUIVO_CSV):
        with open(ARQUIVO_CSV, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row['tipo'] == 'energia':
                    leituras.append(float(row['valor']))
    # Fallback caso o ficheiro não tenha dados suficientes
    if len(leituras) < 2:
        leituras = [50.5, 55.2, 60.1, 185.0, 52.3, 195.5, 58.0]
    return leituras

@app.route('/consumo', methods=['GET'])
def consumo():
    # F1: Consumo por recurso e deteção de desperdício (média + 2 desvios-padrão)
    leituras = ler_dados_consumo()
    media = statistics.mean(leituras)
    desvio = statistics.stdev(leituras)
    limite = media + (2 * desvio)

    desperdicios = [val for val in leituras if val > limite]

    return jsonify({
        "recurso": "energia",
        "unidade": "kWh",
        "media_diaria": round(media, 2),
        "limite_desperdicio": round(limite, 2),
        "alertas_desperdicio": len(desperdicios)
    })

@app.route('/equipamentos', methods=['GET'])
def equipamentos():
    # F2: kWh por hora de uso
    horas_uso = 120
    consumo_total_kwh = 450
    kwh_por_hora = consumo_total_kwh / horas_uso

    return jsonify({
        "equipamento": "Motor Industrial",
        "horas_uso": horas_uso,
        "consumo_total_kwh": consumo_total_kwh,
        "kwh_por_hora": round(kwh_por_hora, 2)
    })

@app.route('/resultados', methods=['GET'])
def resultados():
    # F6: Comparação antes e depois da data_implantacao
    consumo_antes = 1000 # kWh
    consumo_depois = 750 # kWh
    variacao_percentual = ((consumo_depois - consumo_antes) / consumo_antes) * 100
    economia_reais = (consumo_antes - consumo_depois) * 0.85 # Ex: R$ 0.85 por kWh

    return jsonify({
        "acao": "Troca para LEDs",
        "consumo_antes_kwh": consumo_antes,
        "consumo_depois_kwh": consumo_depois,
        "variacao_percentual": round(variacao_percentual, 2),
        "economia_reais": round(economia_reais, 2)
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
