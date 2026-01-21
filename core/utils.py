from django.contrib.auth.models import Group
from django.utils import timezone
from datetime import timedelta, datetime, date
from django.db.models import Q

def make_datetime_aware(data, hora):
    dt_naive = datetime.combine(data, hora)
    return timezone.make_aware(dt_naive, timezone.get_current_timezone())

def get_horarios_clinica():
    """Gera a lista de horários de 45min com intervalo de almoço"""
    horarios = []
    
    # Manhã: Início 7:15 até 11:45 (7 slots) -> Fim 12:30
    inicio_manha = datetime(2000, 1, 1, 7, 15)
    for i in range(7):
        horarios.append((inicio_manha + timedelta(minutes=45*i)).time())
        
    # Tarde: Início 13:30 até 18:45 (8 slots) -> Fim 19:30
    inicio_tarde = datetime(2000, 1, 1, 13, 30)
    for i in range(8):
        horarios.append((inicio_tarde + timedelta(minutes=45*i)).time())
        
    return horarios

def gerar_agenda_futura(dias_a_frente=None, agenda_especifica=None):
    from .models import Agendamento, AgendaFixa
    
    hoje = timezone.now().date()
    # ano_atual = hoje.year
    # fim_do_ano = date(ano_atual, 12, 31)
    
    # Se não definir dias, faz por 365 dias (1 ano)
    if dias_a_frente:
        limite = hoje + timedelta(days=dias_a_frente)
    else:
        limite = hoje + timedelta(days=365)
    
    if agenda_especifica:
        grades = [agenda_especifica]
    else:
        grades = AgendaFixa.objects.filter(ativo=True)
    
    total_criados = 0
    
    for grade in grades:
        data_atual = max(grade.data_inicio, hoje)
        limite_grade = limite
        if grade.data_fim:
            limite_grade = min(limite, grade.data_fim)
            
        while data_atual <= limite_grade:
            if data_atual.weekday() == grade.dia_semana:
                
                tem_conflito = Agendamento.verificar_conflito(
                    terapeuta=grade.terapeuta,
                    data=data_atual,
                    hora_inicio=grade.hora_inicio,
                    hora_fim=grade.hora_fim
                )
                
                if not tem_conflito:
                    Agendamento.objects.create(
                        agenda_fixa=grade,
                        paciente=grade.paciente,
                        terapeuta=grade.terapeuta,
                        sala=grade.sala,
                        data=data_atual,
                        hora_inicio=grade.hora_inicio,
                        hora_fim=grade.hora_fim,
                        tipo_atendimento=grade.paciente.tipo_padrao,
                        status='AGUARDANDO'
                    )
                    total_criados += 1
            
            data_atual += timedelta(days=1)
            
    return total_criados

def criar_agendamentos_em_lote(form_data, user_request):
    from .models import Agendamento
    
    paciente = form_data['paciente']
    terapeuta = form_data['terapeuta']
    sala = form_data.get('sala')
    data_base = form_data['data']
    hora_inicio = form_data['hora_inicio']
    hora_fim = form_data['hora_fim']
    repeticoes = form_data.get('repeticoes', 0)
    
    tipo = paciente.tipo_padrao

    criados = 0
    conflitos = []
    
    for i in range(0, repeticoes + 1):
        nova_data = data_base + timedelta(weeks=i)
        
        # Verifica conflito apenas com agendamentos ativos
        tem_conflito = Agendamento.verificar_conflito(
            terapeuta=terapeuta,
            data=nova_data,
            hora_inicio=hora_inicio,
            hora_fim=hora_fim
        )

        if tem_conflito:
            conflitos.append(nova_data.strftime('%d/%m'))
        else:
            # Remove "sobras" de faltas deletadas ou agendamentos deletados
            Agendamento.objects.ativos().filter(
                terapeuta=terapeuta,
                data=nova_data,
                status='FALTA',
                hora_inicio__lt=hora_fim,
                hora_fim__gt=hora_inicio
            ).update(deletado=True)

            Agendamento.objects.create(
                paciente=paciente,
                terapeuta=terapeuta,
                sala=sala,
                data=nova_data,
                hora_inicio=hora_inicio,
                hora_fim=hora_fim,
                status='AGUARDANDO',
                tipo_atendimento=tipo
            )
            criados += 1
            
    return criados, conflitos

def setup_grupos():
    Group.objects.get_or_create(name='Administrativo')
    Group.objects.get_or_create(name='Terapeutas')
    Group.objects.get_or_create(name='Financeiro')
    Group.objects.get_or_create(name='Donos')