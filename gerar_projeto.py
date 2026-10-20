import os

ficheiros = {
    "backend/data/acoes_esg.json": '''[
  {"id": "A01", "nome": "Substituição de iluminação por lâmpadas LED", "pilar": "E (Ambiental)", "custo": 2500.00, "economia_mensal": 450.00},
  {"id": "A02", "nome": "Sistema de desligamento automático de equipamentos", "pilar": "E (Ambiental)", "custo": 4000.00, "economia_mensal": 800.00},
  {"id": "A03", "nome": "Reparação de fugas na rede de água", "pilar": "E (Ambiental)", "custo": 1200.00, "economia_mensal": 300.00},
  {"id": "A04", "nome": "Manutenção preventiva de máquinas e equipamentos", "pilar": "E (Ambiental)", "custo": 6000.00, "economia_mensal": 950.00},
  {"id": "A05", "nome": "Implementação de recolha seletiva de resíduos", "pilar": "E (Ambiental)", "custo": 800.00, "economia_mensal": 150.00},
  {"id": "A06", "nome": "Formação em segurança do trabalho e uso de EPIs", "pilar": "S (Social)", "custo": 1500.00, "economia_mensal": 200.00}
]''',

    "backend/services/recomendacoes.py": '''import json
import os

def carregar_catalogo_acoes(caminho_json=None):
    if caminho_json is None:
        caminho_json = os.path.join(os.path.dirname(_file_), '../data/acoes_esg.json')
    with open(caminho_json, 'r', encoding='utf-8') as f:
        return json.load(f)

def gerar_recomendacoes(acoes=None):
    if acoes is None:
        acoes = carregar_catalogo_acoes()
    recomendacoes = []
    for acao in acoes:
        custo = float(acao["custo"])
        economia = float(acao["economia_mensal"])
        payback_meses = round(custo / economia, 1) if economia > 0 else float('inf')
        prioridade = "Alta" if payback_meses <= 6 else ("Média" if payback_meses <= 12 else "Baixa")
        recomendacoes.append({
            "id": acao["id"],
            "acao": acao["nome"],
            "pilar": acao["pilar"],
            "investimento_sugerido": {"minimo": round(custo * 0.85, 2), "recomendado": custo, "maximo": round(custo * 1.25, 2)},
            "economia_estimada_mensal": economia,
            "payback_meses": payback_meses,
            "prioridade": prioridade,
            "dados_simulados": True
        })
    recomendacoes.sort(key=lambda x: (-x["economia_estimada_mensal"], x["payback_meses"]))
    return recomendacoes
''',

    "backend/app.py": '''from flask import Flask, jsonify
from services.recomendacoes import gerar_recomendacoes

app = Flask(_name_)

@app.route('/recomendacoes', methods=['GET'])
def get_recomendacoes():
    return jsonify(gerar_recomendacoes()), 200

if _name_ == '_main_':
    app.run(debug=True, port=5000)
''',

    "backend/tests/test_recomendacoes.py": '''from services.recomendacoes import gerar_recomendacoes

def test_calculo_payback():
    acoes = [{"id": "T1", "nome": "Teste", "pilar": "E", "custo": 1000.0, "economia_mensal": 200.0}]
    res = gerar_recomendacoes(acoes)
    assert res[0]["payback_meses"] == 5.0
    assert res[0]["prioridade"] == "Alta"
''',

    "frontend/static/css/base.css": ''':root {
  --primary-color: #1b4332; --secondary-color: #2d6a4f; --accent-color: #52b788;
  --bg-color: #f8f9fa; --text-color: #212529; --card-bg: #ffffff; --border-color: #dee2e6;
}
body { font-family: Arial, sans-serif; background-color: var(--bg-color); color: var(--text-color); margin: 0; padding: 0; line-height: 1.6; }
.navbar { background-color: var(--primary-color); color: white; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; }
.navbar nav ul { list-style: none; margin: 0; padding: 0; display: flex; gap: 1.5rem; }
.navbar nav a { color: #d8f3dc; text-decoration: none; }
.container { max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }
.alerta-simulacao { background: #e9ecef; border-left: 4px solid var(--secondary-color); padding: 0.75rem 1rem; margin-bottom: 1.5rem; }
.grid-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }
.card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 1.25rem; }
.badge { padding: 0.25rem 0.6rem; border-radius: 4px; color: white; font-size: 0.8rem; font-weight: bold; }
.badge-alta { background-color: #d90429; } .badge-media { background-color: #f77f00; } .badge-baixa { background-color: #38b000; }
''',

    "frontend/templates/recomendacoes.html": '''<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="UTF-8">
  <title>Recomendações ESG</title>
  <link rel="stylesheet" href="../static/css/base.css">
</head>
<body>
  <header class="navbar">
    <div class="logo">Plataforma IoT ESG</div>
    <nav>
      <ul>
        <li><a href="consumo.html">Consumo & Equipamentos</a></li>
        <li><a href="resultados.html">Resultados</a></li>
        <li><a href="recomendacoes.html" class="active">Recomendações</a></li>
        <li><a href="social.html">Social</a></li>
        <li><a href="residuos.html">Resíduos</a></li>
      </ul>
    </nav>
  </header>
  <main class="container">
    <h1>Recomendações de Investimento ESG</h1>
    <div class="alerta-simulacao">ℹ️ Nota: Todos os valores são estimativas calculadas com base em dados simulados.</div>
    <div id="grid-recomendacoes" class="grid-cards">A carregar...</div>
  </main>
  <script>
    fetch('/recomendacoes')
      .then(res => res.json())
      .then(dados => {
        document.getElementById('grid-recomendacoes').innerHTML = dados.map(item => `
          <div class="card">
            <h3>${item.acao}</h3>
            <p><strong>Pilar:</strong> ${item.pilar}</p>
            <p><strong>Economia:</strong> R$ ${item.economia_estimada_mensal.toFixed(2)} / mês</p>
            <p><strong>Payback:</strong> ${item.payback_meses} meses</p>
            <p><strong>Investimento:</strong> R$ ${item.investimento_sugerido.recomendado.toFixed(2)}</p>
          </div>
        `).join('');
      });
  </script>
</body>
</html>'''
}

for caminho, conteudo in ficheiros.items():
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(caminho, 'w', encoding='utf-8') as f:
        f.write(conteudo)

print("✅ Todos os ficheiros da Pessoa B foram criados com sucesso!")