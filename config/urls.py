from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from core.views import (
    dashboard,
    lista_pacientes, 
    cadastro_paciente, 
    editar_paciente,
    lista_agendamentos, 
    novo_agendamento,
    reposicao_agendamento,
    realizar_consulta,
    detalhe_paciente,
    confirmar_agendamento, 
    marcar_falta,          
    excluir_agendamento,
    limpar_dia,
    lista_consultas_geral,
    cadastrar_equipe,
    excluir_agendamentos_futuros,
    lista_terapeutas,
    relatorio_mensal,
    relatorio_pacientes
)

urlpatterns = [
    path('admin/', admin.site.urls),
    
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    path('', dashboard, name='dashboard'),

    path('pacientes/', lista_pacientes, name='lista_pacientes'),
    path('pacientes/novo/', cadastro_paciente, name='cadastro_paciente'),
    path('pacientes/editar/<int:paciente_id>/', editar_paciente, name='editar_paciente'),
    path('paciente/<int:paciente_id>/', detalhe_paciente, name='detalhe_paciente'),
    
    path('agendamentos/', lista_agendamentos, name='lista_agendamentos'),
    path('agendamentos/novo/', novo_agendamento, name='novo_agendamento'),
    path('agendamentos/reposicao/<int:agendamento_id>/', reposicao_agendamento, name='reposicao_agendamento'),
    path('consultas/historico/', lista_consultas_geral, name='lista_consultas_geral'),
    
    path('agendamentos/confirmar/<int:agendamento_id>/', confirmar_agendamento, name='confirmar_agendamento'),
    path('agendamentos/atender/<int:agendamento_id>/', realizar_consulta, name='realizar_consulta'),
    path('agendamentos/falta/<int:agendamento_id>/', marcar_falta, name='marcar_falta'),
    path('agendamentos/excluir/<int:agendamento_id>/', excluir_agendamento, name='excluir_agendamento'),
    path('agendamentos/limpar-dia/', limpar_dia, name='limpar_dia'),
    
    # --- Area da Equipe ---
    path('equipe/novo/', cadastrar_equipe, name='cadastrar_equipe'),
    path('equipe/lista/', lista_terapeutas, name='lista_terapeutas'), # <--- Nova Rota
    
    path('paciente/<int:paciente_id>/limpar-agenda/', excluir_agendamentos_futuros, name='excluir_agendamentos_futuros'),

    path('relatorios/', relatorio_mensal, name='relatorio_mensal'),
    path('relatorios/pacientes/', relatorio_pacientes, name='relatorio_pacientes'),
]