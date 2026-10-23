from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('quem-somos/', views.quem_somos, name='quem_somos'),
    path(
        'microlearning/',
        views.painel_microlearning,
        name='painel_microlearning',
    ),
    path(
        'microlearning/dados',
        views.dados_microlearning,
        name='dados_microlearning',
    ),
    path(
        'microlearning/responder',
        views.responder_microlearning,
        name='responder_microlearning',
    ),
    path(
        'fornecedores/',
        views.painel_fornecedores,
        name='painel_fornecedores',
    ),
    path(
        'fornecedores/dados',
        views.dados_fornecedores,
        name='dados_fornecedores',
    ),
]
