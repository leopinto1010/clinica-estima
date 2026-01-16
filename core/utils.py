from django.contrib.auth.models import Group
from django.utils import timezone
from datetime import timedelta, datetime, date
from django.db.models import Q

def make_datetime_aware(data, hora):
    dt_naive = datetime.combine(data, hora)
    return timezone.make_aware(dt_naive, timezone.get_current_timezone())

def gerar_agenda_futura(dias_a_frente=None):
    """
    Lê a tabela AgendaFixa e cria agendamentos reais (materializa a grade).
    Regra: Se dias_a_frente não for informado, gera até 31/12 do ano corrente.
    """
    # Importação atrasada para evitar ciclo de imports
    from .models import Agendamento, AgendaFixa
    
    hoje = timezone.now().date()
    ano_atual = hoje.year
    
    # Define o limite padrão como 31 de Dezembro do ano atual
    fim_do_ano = date(ano_atual, 12, 31)
    
    # Se foi passado um limite específico (ex: 30 dias), usa ele.
    # Caso contrário, usa o fim do ano.
    if dias_a_frente:
        limite = hoje + timedelta(days=dias_a_frente)
    else:
        limite = fim_do_ano
    
    # Busca todas as grades ativas
    grades = AgendaFixa.objects.filter(ativo=True)
    
    total_criados = 0
    
    for grade in grades:
        # Começa a verificar de "Hoje" ou do "Inicio do Contrato" (o que for maior)
        # Isso evita recriar agenda passada se o contrato for antigo
        data_atual = max(grade.data_inicio, hoje)
        
        # O limite final desta grade específica é o MENOR entre:
        # 1. O fim do ano (limite global de processamento)
        # 2. A data fim do contrato (se a grade tiver validade definida)
        limite_grade = limite
        if grade.data_fim:
            limite_grade = min(limite, grade.data_fim)
            
        while data_atual <= limite_grade:
            # Verifica se o dia atual da iteração bate com o dia da semana da grade
            if data_atual.weekday() == grade.dia_semana:
                
                # Verifica duplicidade para não criar 2x o mesmo horário
                ja_existe = Agendamento.objects.filter(
                    terapeuta=grade.terapeuta,
                    data=data_atual,
                    hora_inicio=grade.hora_inicio
                ).exists()
                
                if not ja_existe:
                    Agendamento.objects.create(
                        agenda_fixa=grade,      # Vincula à regra mãe
                        paciente=grade.paciente,
                        terapeuta=grade.terapeuta,
                        sala=grade.sala,        # Atribui a Sala da grade
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
    """
    Mantido para agendamentos AVULSOS manuais (criados via botão 'Novo Agendamento').
    """
    from .models import Agendamento
    
    paciente = form_data['paciente']
    terapeuta = form_data['terapeuta']
    sala = form_data.get('sala') # Pode ser None
    data_base = form_data['data']
    hora_inicio = form_data['hora_inicio']
    hora_fim = form_data['hora_fim']
    repeticoes = form_data.get('repeticoes', 0)
    
    tipo = paciente.tipo_padrao

    criados = 0
    conflitos = []
    
    for i in range(0, repeticoes + 1):
        nova_data = data_base + timedelta(weeks=i)
        
        # Verifica conflito REAL (ignora faltas, mas respeita agendamentos ativos)
        tem_conflito = Agendamento.verificar_conflito(
            terapeuta=terapeuta,
            data=nova_data,
            hora_inicio=hora_inicio,
            hora_fim=hora_fim
        )

        if tem_conflito:
            conflitos.append(nova_data.strftime('%d/%m'))
        else:
            # Limpeza automática de faltas antigas no mesmo horário
            # Se tentar agendar num horário que tem "Falta", a falta é arquivada (soft delete)
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

# --- PERMISSÕES ---
def setup_grupos():
    Group.objects.get_or_create(name='Administrativo')
    Group.objects.get_or_create(name='Terapeutas')
    Group.objects.get_or_create(name='Financeiro')
    Group.objects.get_or_create(name='Donos')