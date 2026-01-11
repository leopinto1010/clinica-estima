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
    # Importação atrasada para evitar erro de ciclo (Model <-> Utils)
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
        
        # --- ATUALIZAÇÃO CRÍTICA ---
        # Agora usamos o método centralizado do Model para checar conflitos.
        # Isso garante que a regra é a mesma em todo o sistema.
        tem_conflito = Agendamento.verificar_conflito(
            terapeuta=terapeuta,
            data=nova_data,
            hora_inicio=hora_inicio,
            hora_fim=hora_fim
        )

        if tem_conflito:
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
    Group.objects.get_or_create(name='Donos') # <--- NOVO GRUPO