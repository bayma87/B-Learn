from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('quiz/', views.quiz, name='quiz'),
    path('quem-somos/', views.quem_somos, name='quem_somos'),
    path('residuos/', views.painel_residuos, name='painel_residuos'),
    path('residuos/resumo', views.resumo_residuos, name='resumo_residuos'),
    path('social/', views.painel_social, name='painel_social'),
    path(
        'social/indicadores',
        views.indicadores_sociais,
        name='indicadores_sociais',
    ),
    path(
        'diagnostico/residuos/',
        views.diagnostico_residuos,
        name='diagnostico_residuos',
    ),
    path(
        'diagnostico/residuos/novo/',
        views.diagnostico_residuos_novo,
        name='diagnostico_residuos_novo',
    ),
    path(
        'recomendacoes',
        views.recomendacoes_esg,
        name='recomendacoes',
    ),
    path(
        'painel-recomendacoes/',
        views.painel_recomendacoes,
        name='painel_recomendacoes',
    ),
    path(
        'consumo/indicadores',
        views.indicadores_consumo,
        name='indicadores_consumo',
    ),
    path(
        'equipamentos/consumo-por-hora',
        views.consumo_por_hora_equipamentos,
        name='consumo_por_hora_equipamentos',
    ),
    path(
        'painel-equipamentos/',
        views.painel_equipamentos,
        name='painel_equipamentos',
    ),
    path(
        'painel-consumo/',
        views.painel_consumo,
        name='painel_consumo',
    ),
]
