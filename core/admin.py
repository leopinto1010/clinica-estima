from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Paciente, Terapeuta, Agendamento, Consulta

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
    # Mostra colunas importantes na lista
    list_display = ('data_formatada', 'hora_inicio', 'paciente', 'terapeuta_nome', 'status', 'tipo_atendimento')
    
    # Filtros laterais
    list_filter = ('status', 'data', 'terapeuta', 'tipo_atendimento')
    
    # Barra de pesquisa
    search_fields = ('paciente__nome', 'terapeuta__nome')
    
    # Ordenação padrão
    ordering = ('-data', 'hora_inicio')

    def terapeuta_nome(self, obj):
        return obj.terapeuta.nome
    terapeuta_nome.short_description = 'Terapeuta'
    
    def data_formatada(self, obj):
        return obj.data.strftime('%d/%m/%Y')
    data_formatada.short_description = 'Data'

# --- 3. Outros Modelos ---
@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ('nome', 'cpf', 'telefone', 'tipo_padrao')
    search_fields = ('nome', 'cpf')
    list_filter = ('tipo_padrao',)

@admin.register(Terapeuta)
class TerapeutaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'registro_profissional', 'especialidade', 'usuario')

admin.site.register(Consulta)