from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Paciente, Terapeuta, Agendamento, Consulta, Convenio, Sala, AgendaFixa, AnexoConsulta
from .utils import gerar_agenda_futura

# --- Ação customizada para gerar agenda em massa ---
@admin.action(description='Gerar agenda futura para os selecionados (Materializar)')
def acao_gerar_agenda(modeladmin, request, queryset):
    # Nota: O queryset aqui não é muito usado pois a função gera para todos os ativos,
    # mas mantemos o padrão do Django Admin.
    total = gerar_agenda_futura() 
    modeladmin.message_user(request, f"Processo concluído. {total} novos agendamentos criados no total baseados na grade ativa.")

# --- 1. Usuários (Customização para mostrar grupos) ---
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'get_groups', 'is_staff', 'is_active')
    list_filter = ('groups', 'is_staff', 'is_active')
    
    def get_groups(self, obj):
        return ", ".join([g.name for g in obj.groups.all()])
    get_groups.short_description = 'Função / Grupo'

admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# --- 2. Agendamentos ---
@admin.register(Agendamento)
class AgendamentoAdmin(admin.ModelAdmin):
    list_select_related = ('paciente', 'terapeuta', 'sala', 'agenda_fixa')
    list_per_page = 25 
    date_hierarchy = 'data'
    
    list_display = ('data_formatada', 'hora_inicio', 'paciente', 'terapeuta_nome', 'sala', 'status', 'tem_grade')
    list_filter = ('status', 'terapeuta', 'tipo_atendimento', 'sala')
    search_fields = ('paciente__nome', 'terapeuta__nome')
    ordering = ('-data', 'hora_inicio')

    @admin.display(ordering='terapeuta__nome', description='Terapeuta')
    def terapeuta_nome(self, obj):
        return obj.terapeuta.nome
    
    @admin.display(ordering='data', description='Data')
    def data_formatada(self, obj):
        return obj.data.strftime('%d/%m/%Y')
    
    @admin.display(boolean=True, description='Fixo?')
    def tem_grade(self, obj):
        return obj.agenda_fixa is not None

# --- 3. Agenda Fixa (NOVO) ---
@admin.register(AgendaFixa)
class AgendaFixaAdmin(admin.ModelAdmin):
    list_display = ('get_dia_semana_display', 'hora_inicio', 'paciente', 'terapeuta', 'sala', 'ativo')
    list_filter = ('dia_semana', 'terapeuta', 'sala', 'ativo')
    search_fields = ('paciente__nome', 'terapeuta__nome')
    ordering = ('dia_semana', 'hora_inicio')
    actions = [acao_gerar_agenda] 

# --- 4. Salas (NOVO) ---
@admin.register(Sala)
class SalaAdmin(admin.ModelAdmin):
    list_display = ('nome',)
    search_fields = ('nome',)

# --- 5. Outros Modelos ---
@admin.register(Convenio)
class ConvenioAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ativo')
    search_fields = ('nome',)
    list_filter = ('ativo',)

@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ('nome', 'cpf', 'telefone', 'tipo_padrao', 'convenio', 'ativo')
    search_fields = ('nome', 'cpf')
    list_filter = ('ativo', 'tipo_padrao', 'convenio')

@admin.register(Terapeuta)
class TerapeutaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'registro_profissional', 'especialidade', 'usuario')

class AnexoInline(admin.TabularInline):
    model = AnexoConsulta
    extra = 0

@admin.register(Consulta)
class ConsultaAdmin(admin.ModelAdmin):
    list_display = ('agendamento', 'data_registro')
    inlines = [AnexoInline]