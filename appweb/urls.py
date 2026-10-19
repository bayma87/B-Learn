from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='home'),
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
        'recomendacoes',
        views.recomendacoes_esg,
        name='recomendacoes',
    ),
    path(
        'painel-recomendacoes/',
        views.painel_recomendacoes,
        name='painel_recomendacoes',
    ),
]
