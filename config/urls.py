from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

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
    lista_terapeutas,
    relatorio_mensal,
    relatorio_pacientes,
    lista_agendas_fixas, 
    nova_agenda_fixa, 
    editar_agenda_fixa, 
    excluir_agenda_fixa,
    ocupacao_salas,
    relatorio_grade_pacientes, 
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
    
    # --- AGENDA FIXA ---
    path('agenda-fixa/', lista_agendas_fixas, name='lista_agendas_fixas'),
    path('agenda-fixa/nova/', nova_agenda_fixa, name='nova_agenda_fixa'),
    path('agenda-fixa/editar/<int:id>/', editar_agenda_fixa, name='editar_agenda_fixa'),
    path('agenda-fixa/excluir/<int:id>/', excluir_agenda_fixa, name='excluir_agenda_fixa'),

    # --- Area da Equipe ---
    path('equipe/novo/', cadastrar_equipe, name='cadastrar_equipe'),
    path('equipe/lista/', lista_terapeutas, name='lista_terapeutas'),
    
    path('relatorios/', relatorio_mensal, name='relatorio_mensal'),
    path('relatorios/pacientes/', relatorio_pacientes, name='relatorio_pacientes'),

    path('relatorios/salas/', ocupacao_salas, name='ocupacao_salas'),
    path('relatorios/grade-pacientes/', relatorio_grade_pacientes, name='relatorio_grade_pacientes'),
]

# --- ROTA PARA ARQUIVOS DE MÍDIA (DEBUG) ---
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)