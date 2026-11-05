from django.contrib.auth.models import Group
from django.utils import timezone
from datetime import timedelta, datetime, date
from django.db.models import Q
from django.db import transaction


STATUS_AGENDAMENTO_IMUTAVEIS = ('REALIZADO', 'FALTA')

def make_datetime_aware(data, hora):
    dt_naive = datetime.combine(data, hora)
    return timezone.make_aware(dt_naive, timezone.get_current_timezone())

def get_horarios_clinica(extras=None):
    """
    Gera a lista de horários padrão de 45min, mas adiciona
    horários extras (ex: 30min) se fornecidos, garantindo que
    apareçam na visualização.
    """
    horarios = set() # Usar set para evitar duplicatas
    
    # --- Grade Padrão (Manhã) ---
    inicio_manha = datetime(2000, 1, 1, 7, 15)
    for i in range(7):
        horarios.add((inicio_manha + timedelta(minutes=45*i)).time())
        
    # --- Grade Padrão (Tarde) ---
    inicio_tarde = datetime(2000, 1, 1, 13, 30)
    for i in range(8):
        horarios.add((inicio_tarde + timedelta(minutes=45*i)).time())

    # --- Mesclar com horários extras (os que existem de fato no banco) ---
    if extras:
        for h in extras:
            if h: # Garante que não é None
                horarios.add(h)

    # Retorna lista ordenada
    return sorted(list(horarios))

def _limite_materializacao(hoje, dias_a_frente=None):
    if dias_a_frente is not None:
        return hoje + timedelta(days=dias_a_frente)
    return date(hoje.year, 12, 31)


def _agenda_vigente_na_data(agenda, data_agendamento):
    return (
        agenda.ativo
        and data_agendamento >= agenda.data_inicio
        and (not agenda.data_fim or data_agendamento <= agenda.data_fim)
        and data_agendamento.weekday() == agenda.dia_semana
    )


def _dados_materializados(agenda):
    return {
        'paciente_id': agenda.paciente_id,
        'terapeuta_id': agenda.terapeuta_id,
        'modalidade': agenda.modalidade,
        'sala_id': agenda.sala_id,
        'hora_inicio': agenda.hora_inicio,
        'hora_fim': agenda.hora_fim,
        'tipo_atendimento': agenda.paciente.tipo_padrao,
    }


@transaction.atomic
def sincronizar_agenda_fixa(agenda, dias_a_frente=None, data_referencia=None):
    """Sincroniza somente copias futuras e mutaveis de uma AgendaFixa.

    AgendaFixa e a fonte da regra recorrente. Agendamento continua sendo o
    snapshot operacional usado pelas agendas diaria/profissional e pelas salas.
    Registros passados e estados finais nunca sao reescritos.
    """
    from .models import Agendamento

    hoje = data_referencia or timezone.localdate()
    limite = _limite_materializacao(hoje, dias_a_frente)
    dados = _dados_materializados(agenda)
    total_alterados = 0

    # Inclui deletados para que uma reativacao reutilize a mesma copia, sem
    # produzir duplicatas. Estados finais e datas passadas sao historico.
    vinculados = list(
        Agendamento.objects.filter(agenda_fixa=agenda, data__gte=hoje)
        .exclude(status__in=STATUS_AGENDAMENTO_IMUTAVEIS)
        .order_by('data', 'deletado', 'id')
    )
    vinculados_por_data = {}
    for agendamento in vinculados:
        vinculados_por_data.setdefault(agendamento.data, []).append(agendamento)

    for data_agendamento, copias in vinculados_por_data.items():
        if not _agenda_vigente_na_data(agenda, data_agendamento):
            ids_ativos = [copia.id for copia in copias if not copia.deletado]
            if ids_ativos:
                total_alterados += Agendamento.objects.filter(id__in=ids_ativos).update(deletado=True)
            continue

        principal, *duplicados = copias
        valores_principal = dict(dados, deletado=False)
        campos_mudaram = principal.deletado or any(
            getattr(principal, campo) != valor
            for campo, valor in valores_principal.items()
        )
        if campos_mudaram:
            Agendamento.objects.filter(pk=principal.pk).update(**valores_principal)
            total_alterados += 1

        ids_duplicados_ativos = [copia.id for copia in duplicados if not copia.deletado]
        if ids_duplicados_ativos:
            total_alterados += Agendamento.objects.filter(id__in=ids_duplicados_ativos).update(deletado=True)

    if not agenda.ativo:
        return total_alterados

    data_atual = max(agenda.data_inicio, hoje)
    limite_grade = min(limite, agenda.data_fim) if agenda.data_fim else limite

    while data_atual <= limite_grade:
        if data_atual.weekday() != agenda.dia_semana:
            data_atual += timedelta(days=1)
            continue

        # Qualquer copia ativa vinculada, inclusive final, representa a data.
        if Agendamento.objects.filter(
            agenda_fixa=agenda, data=data_atual, deletado=False
        ).exists():
            data_atual += timedelta(days=1)
            continue

        conflito = (
            Agendamento.objects.ativos()
            .filter(terapeuta_id=agenda.terapeuta_id, data=data_atual)
            .exclude(status='FALTA')
            .filter(hora_inicio__lt=agenda.hora_fim, hora_fim__gt=agenda.hora_inicio)
            .first()
        )

        # Mantem a compatibilidade com o legado: um agendamento avulso do
        # mesmo paciente pode ser absorvido, mas nunca rouba outra AgendaFixa.
        if (
            conflito
            and conflito.paciente_id == agenda.paciente_id
            and conflito.agenda_fixa_id is None
            and conflito.status not in STATUS_AGENDAMENTO_IMUTAVEIS
        ):
            Agendamento.objects.filter(pk=conflito.pk).update(
                agenda_fixa=agenda,
                **dados,
            )
            total_alterados += 1
        elif not conflito:
            Agendamento.objects.create(
                agenda_fixa=agenda,
                data=data_atual,
                status='AGUARDANDO',
                deletado=False,
                **dados,
            )
            total_alterados += 1

        data_atual += timedelta(days=1)

    return total_alterados


def gerar_agenda_futura(dias_a_frente=None, agenda_especifica=None):
    from .models import AgendaFixa

    grades = [agenda_especifica] if agenda_especifica else AgendaFixa.objects.filter(ativo=True)
    return sum(
        sincronizar_agenda_fixa(grade, dias_a_frente=dias_a_frente)
        for grade in grades
    )

def criar_agendamentos_em_lote(form_data, user_request):
    from .models import Agendamento
    
    paciente = form_data['paciente']
    terapeuta = form_data['terapeuta']
    sala = form_data.get('sala')
    data_base = form_data['data']
    hora_inicio = form_data['hora_inicio']
    hora_fim = form_data['hora_fim']
    repeticoes = form_data.get('repeticoes', 0)
    
    # --- NOVO: Pega a modalidade do form ---
    modalidade = form_data.get('modalidade', 'FISIOTERAPIA') 
    
    tipo = paciente.tipo_padrao

    criados = 0
    conflitos = []
    
    for i in range(0, repeticoes + 1):
        nova_data = data_base + timedelta(weeks=i)

        agendamento_duplicado = Agendamento.objects.filter(
            paciente=paciente,
            terapeuta=terapeuta,
            data=nova_data,
            hora_inicio=hora_inicio,
            hora_fim=hora_fim,
            deletado=False,
        ).exists()

        if agendamento_duplicado:
            conflitos.append(nova_data.strftime('%d/%m'))
            continue

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
                modalidade=modalidade,
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
    Group.objects.get_or_create(name='Coordenação')
    Group.objects.get_or_create(name='Donos')
