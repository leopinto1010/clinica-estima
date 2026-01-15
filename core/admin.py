from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Paciente, Terapeuta, Agendamento, Consulta, Convenio

# --- 1. Usuários: Mostrar o "Papel" na lista ---
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'get_groups', 'is_staff', 'is_active')
    list_filter = ('groups', 'is_staff', 'is_active')
    
    def get_groups(self, obj):
        return ", ".join([g.name for g in obj.groups.all()])
    get_groups.short_description = 'Função / Grupo'

# Remove o admin padrão e registra o nosso
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# --- 2. Agendamentos: Visão Geral Completa ---
@admin.register(Agendamento)
class AgendamentoAdmin(admin.ModelAdmin):
    # --- 1. OTIMIZAÇÃO DE BANCO (JOINs) ---
    # Busca os dados relacionados em uma única query SQL
    list_select_related = ('paciente', 'terapeuta')

    # --- 2. PAGINAÇÃO MAIS LEVE ---
    # Carrega menos elementos HTML por vez (padrão é 100)
    list_per_page = 25 
    
    # Evita query de "COUNT(*)" total se a tabela for muito grande
    show_full_result_count = False

    # --- 3. NAVEGAÇÃO OTIMIZADA ---
    # Cria barra de navegação por data no topo (mais rápido que filtro lateral)
    date_hierarchy = 'data'

    list_display = ('data_formatada', 'hora_inicio', 'paciente', 'terapeuta_nome', 'status', 'tipo_atendimento')
    
    # Removemos 'data' daqui pois já temos o date_hierarchy
    list_filter = ('status', 'terapeuta', 'tipo_atendimento')
    
    search_fields = ('paciente__nome', 'terapeuta__nome')
    ordering = ('-data', 'hora_inicio')

    # --- 4. ORDENAÇÃO DE COLUNAS CALCULADAS ---
    # Permite ordenar clicando na coluna 'Terapeuta', usando o índice do banco
    @admin.display(ordering='terapeuta__nome', description='Terapeuta')
    def terapeuta_nome(self, obj):
        return obj.terapeuta.nome
    
    # Permite ordenar clicando na coluna 'Data'
    @admin.display(ordering='data', description='Data')
    def data_formatada(self, obj):
        return obj.data.strftime('%d/%m/%Y')

@admin.register(Convenio)
class ConvenioAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ativo')
    search_fields = ('nome',)
    list_filter = ('ativo',)

# --- 3. Outros Modelos ---
@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ('nome', 'cpf', 'telefone', 'tipo_padrao', 'convenio')
    search_fields = ('nome', 'cpf')
    list_filter = ('tipo_padrao', 'convenio')

@admin.register(Terapeuta)
class TerapeutaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'registro_profissional', 'especialidade', 'usuario')

admin.site.register(Consulta)