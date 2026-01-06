from django.contrib.auth.models import Group
from django.utils import timezone
from datetime import timedelta, datetime

def make_datetime_aware(data, hora):
    dt_naive = datetime.combine(data, hora)
    return timezone.make_aware(dt_naive, timezone.get_current_timezone())

def criar_agendamentos_em_lote(form_data, user_request):
    """
    Processa o agendamento inicial e suas repetições.
    Retorna uma tupla: (número_de_criados, lista_de_datas_com_conflito)
    """
    from .models import Agendamento
    
    paciente = form_data['paciente']
    terapeuta = form_data['terapeuta']
    data_base = form_data['data']
    hora_inicio = form_data['hora_inicio']
    hora_fim = form_data['hora_fim']
    repeticoes = form_data.get('repeticoes', 0)
    
    tipo = paciente.tipo_padrao

    criados = 0
    conflitos = []
    
    for i in range(0, repeticoes + 1):
        nova_data = data_base + timedelta(weeks=i)
        
        # Verifica conflito no banco
        # ALTERAÇÃO: Adicionado .exclude(deletado=True)
        conflito_qs = Agendamento.objects.filter(
            terapeuta=terapeuta, 
            data=nova_data
        ).exclude(status__in=['CANCELADO', 'FALTA']).exclude(deletado=True)
        
        conflito_qs = conflito_qs.filter(
            hora_inicio__lt=hora_fim, 
            hora_fim__gt=hora_inicio
        )

        if conflito_qs.exists():
            conflitos.append(nova_data.strftime('%d/%m'))
        else:
            Agendamento.objects.create(
                paciente=paciente,
                terapeuta=terapeuta,
                data=nova_data,
                hora_inicio=hora_inicio,
                hora_fim=hora_fim,
                status='AGUARDANDO',
                tipo_atendimento=tipo
            )
            criados += 1
            
    return criados, conflitos

# --- PERMISSÕES ---
def setup_grupos():
    Group.objects.get_or_create(name='Administrativo')
    Group.objects.get_or_create(name='Terapeutas')
    Group.objects.get_or_create(name='Financeiro')

def is_dono(user):
    return user.is_superuser

def is_admin(user):
    return user.groups.filter(name='Administrativo').exists() or user.is_superuser

def is_terapeuta(user):
    return user.groups.filter(name='Terapeutas').exists()

def is_financeiro(user):
    return user.groups.filter(name='Financeiro').exists() or user.is_superuser