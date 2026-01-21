from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta, datetime
from django.db.models import Count, Q, F, Case, When, FloatField
from django.db import transaction
from django import forms
from django.contrib.auth.models import Group
import calendar
from collections import defaultdict
import unicodedata

from .models import (
    Paciente, Terapeuta, Agendamento, Consulta, AnexoConsulta, 
    TIPO_ATENDIMENTO_CHOICES, ESPECIALIDADES_CHOICES,
    AgendaFixa, Sala
)

from .forms import (
    PacienteForm, AgendamentoForm, ConsultaForm, 
    CadastroEquipeForm, RegistrarFaltaForm, AgendaFixaForm
)

from .decorators import admin_required, terapeuta_required, dono_required, is_admin, is_terapeuta, is_dono
from .utils import setup_grupos, criar_agendamentos_em_lote, gerar_agenda_futura, get_horarios_clinica
from django.urls import reverse

def remover_acentos(texto):
    if not texto: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

# ... (Mantenha as outras views: dashboard, lista_pacientes, etc. sem alterações até lista_agendamentos) ...

@login_required
def dashboard(request):
    hoje = timezone.localtime(timezone.now()).date()
    qs = Agendamento.objects.ativos().filter(data=hoje).select_related('paciente', 'terapeuta', 'sala').order_by('hora_inicio')

    if not is_admin(request.user):
        if is_terapeuta(request.user):
            qs = qs.filter(terapeuta=request.user.terapeuta)
        else:
            qs = Agendamento.objects.none()

    total_pacientes = Paciente.objects.filter(ativo=True).count()
    total_agendamentos_hoje = qs.count()
    
    return render(request, 'dashboard.html', {
        'agendamentos_hoje': qs,
        'total_pacientes': total_pacientes,
        'total_agendamentos_hoje': total_agendamentos_hoje,
        'is_admin': is_admin(request.user),
        'agora': hoje
    })

@login_required
def lista_pacientes(request):
    busca = request.GET.get('q')
    filtro_status = request.GET.get('status')
    filtro_tipo = request.GET.get('tipo')

    if is_admin(request.user):
        pacientes = Paciente.objects.all()
        if filtro_status == 'ativos':
            pacientes = pacientes.filter(ativo=True)
        elif filtro_status == 'inativos':
            pacientes = pacientes.filter(ativo=False)
    else:
        pacientes = Paciente.objects.filter(
            ativo=True, 
            agendamento__terapeuta=request.user.terapeuta
        ).distinct()

    if busca:
        busca_limpa = remover_acentos(busca).lower()
        pacientes = pacientes.filter(Q(nome_search__icontains=busca_limpa) | Q(cpf__icontains=busca))
    
    if filtro_tipo:
        pacientes = pacientes.filter(tipo_padrao=filtro_tipo)
    
    pacientes = pacientes.order_by('nome')

    return render(request, 'lista_pacientes.html', {
        'pacientes': pacientes,
        'is_admin': is_admin(request.user),
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES,
        'filtro_status_selecionado': filtro_status,
        'filtro_tipo_selecionado': filtro_tipo,
        'busca_atual': busca
    })

@admin_required
def cadastro_paciente(request):
    if request.method == 'POST':
        form = PacienteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Paciente cadastrado!")
            return redirect('lista_pacientes')
    else:
        form = PacienteForm()
    return render(request, 'cadastro_paciente.html', {'form': form})

@admin_required
def editar_paciente(request, paciente_id):
    paciente = get_object_or_404(Paciente, id=paciente_id)
    filtros = request.GET.urlencode()
    
    if request.method == 'POST':
        filtros_post = request.POST.get('filtros_persistentes', '')
        form = PacienteForm(request.POST, instance=paciente)
        if form.is_valid():
            form.save()
            messages.success(request, f"Dados atualizados!")
            url_destino = redirect('lista_pacientes').url
            if filtros_post: url_destino += f"?{filtros_post}"
            return redirect(url_destino)
    else:
        form = PacienteForm(instance=paciente)
        
    return render(request, 'cadastro_paciente.html', {
        'form': form, 'editando': True, 'filtros_persistentes': filtros
    })

@login_required
def detalhe_paciente(request, paciente_id):
    paciente = get_object_or_404(Paciente, id=paciente_id)
    tem_permissao = False
    
    if is_admin(request.user): tem_permissao = True
    elif is_terapeuta(request.user):
        vinculo = Agendamento.objects.ativos().filter(paciente=paciente, terapeuta=request.user.terapeuta).exists()
        if vinculo: tem_permissao = True
            
    if not tem_permissao:
        messages.error(request, "Sem permissão.")
        return redirect('lista_pacientes')

    historico = Consulta.objects.filter(
        agendamento__paciente=paciente,
        agendamento__deletado=False
    ).select_related('agendamento__terapeuta').order_by('-agendamento__data', '-agendamento__hora_inicio')
    
    terapeutas_ids = historico.values_list('agendamento__terapeuta', flat=True).distinct()
    terapeutas_filtros = Terapeuta.objects.filter(id__in=terapeutas_ids)
    
    ocultar_evolucao = is_admin(request.user) and not is_dono(request.user)
    
    return render(request, 'detalhe_paciente.html', {
        'paciente': paciente,
        'historico': historico,
        'terapeutas_filtros': terapeutas_filtros,
        'ocultar_evolucao': ocultar_evolucao,
        'is_admin': is_admin(request.user)
    })

# --- VIEW ATUALIZADA ---
@login_required
def lista_agendamentos(request):
    data_inicio_get = request.GET.get('data_inicio')
    data_fim_get = request.GET.get('data_fim')
    filtro_hoje = request.GET.get('filtro_hoje')
    filtro_semana = request.GET.get('filtro_semana')
    
    # ALTERADO: Filtro por ID em vez de busca por texto
    filtro_paciente = request.GET.get('filtro_paciente')
    
    filtro_tipo = request.GET.get('filtro_tipo')
    filtro_terapeuta = request.GET.get('filtro_terapeuta')
    filtro_status = request.GET.get('filtro_status')
    filtro_sala = request.GET.get('filtro_sala')

    agora = timezone.localtime(timezone.now())
    hoje = agora.date()
    
    if filtro_hoje:
        data_inicio, data_fim = hoje, hoje
    elif data_inicio_get and data_fim_get:
        data_inicio = datetime.strptime(data_inicio_get, '%Y-%m-%d').date()
        data_fim = datetime.strptime(data_fim_get, '%Y-%m-%d').date()
    else:
        # Padrão: Semana atual (Seg-Dom)
        start_week = hoje - timedelta(days=hoje.weekday())
        data_inicio, data_fim = start_week, start_week + timedelta(days=6)
        filtro_semana = '1'

    agendamentos = Agendamento.objects.ativos().select_related('paciente', 'terapeuta', 'sala', 'agenda_fixa').filter(
        data__range=[data_inicio, data_fim]
    ).order_by('data', 'hora_inicio')

    if not is_admin(request.user):
        if is_terapeuta(request.user):
            agendamentos = agendamentos.filter(terapeuta=request.user.terapeuta)
        else:
            agendamentos = Agendamento.objects.none()
    else:
        if filtro_terapeuta == 'todos': 
            pass 
        elif filtro_terapeuta: 
            agendamentos = agendamentos.filter(terapeuta_id=filtro_terapeuta)
        else:
            pass
    
    # ALTERADO: Filtra pelo ID exato do paciente selecionado
    if filtro_paciente:
        agendamentos = agendamentos.filter(paciente_id=filtro_paciente)

    if filtro_tipo: agendamentos = agendamentos.filter(tipo_atendimento=filtro_tipo)
    if filtro_status: agendamentos = agendamentos.filter(status=filtro_status)
    if filtro_sala: agendamentos = agendamentos.filter(sala_id=filtro_sala)

    # Preparação da Grade
    horarios_grade = get_horarios_clinica()
    
    delta = data_fim - data_inicio
    dates_in_range = []
    for i in range(delta.days + 1):
        dates_in_range.append(data_inicio + timedelta(days=i))

    agenda_map = {t.strftime('%H:%M'): {d.strftime('%Y-%m-%d'): [] for d in dates_in_range} for t in horarios_grade}

    for item in agendamentos:
        h_str = item.hora_inicio.strftime('%H:%M')
        d_str = item.data.strftime('%Y-%m-%d')
        
        if h_str in agenda_map and d_str in agenda_map[h_str]:
            agenda_map[h_str][d_str].append(item)

    return render(request, 'lista_agendamentos.html', {
        'agenda_map': agenda_map,
        'horarios_grade': horarios_grade,
        'dates_in_range': dates_in_range,
        'agora': agora,
        'data_inicio': str(data_inicio), 'data_fim': str(data_fim),
        'filtro_hoje': filtro_hoje, 'filtro_semana': filtro_semana,
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES,
        
        # ALTERADO: Passamos a lista de pacientes ativos para o select
        'pacientes': Paciente.objects.filter(ativo=True).order_by('nome'),
        'filtro_paciente_selecionado': int(filtro_paciente) if filtro_paciente else None,
        
        'terapeutas': Terapeuta.objects.all() if is_admin(request.user) else None,
        'salas': Sala.objects.all(),
        'filtro_tipo_selecionado': filtro_tipo,
        'filtro_terapeuta_selecionado': filtro_terapeuta, 
        'filtro_sala_selecionado': filtro_sala,
        'status_choices': Agendamento.STATUS_CHOICES,
        'filtro_status_selecionado': filtro_status,
        'is_admin': is_admin(request.user)
    })

# ... (Mantenha o restante das views: novo_agendamento, lista_agendas_fixas, etc.) ...
@login_required
def novo_agendamento(request):
    if not is_admin(request.user):
        messages.error(request, "Acesso restrito. Agendamentos são feitos apenas pela administração.")
        return redirect('lista_agendamentos')

    if request.method == 'POST':
        form = AgendamentoForm(request.POST)
    else:
        form = AgendamentoForm()

    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                criados, conflitos = criar_agendamentos_em_lote(form.cleaned_data, request.user)
            
            if criados > 0:
                msg = f"{criados} agendamentos avulsos criados."
                if conflitos: msg += f" (Conflitos ignorados: {', '.join(conflitos)})"
                if conflitos: messages.warning(request, msg)
                else: messages.success(request, msg)
                return redirect('lista_agendamentos')
            else:
                messages.error(request, f"Falha: Datas ocupadas ({', '.join(conflitos)}).")
        except Exception as e:
            messages.error(request, f"Erro interno: {e}")

    return render(request, 'novo_agendamento.html', {'form': form})

@login_required
def lista_agendas_fixas(request):
    if not is_admin(request.user):
        messages.error(request, "Acesso restrito. Apenas a administração gerencia a Agenda Fixa.")
        return redirect('dashboard')
        
    agendas = AgendaFixa.objects.filter(ativo=True).select_related('paciente', 'terapeuta', 'sala')
    
    terapeuta_id = request.GET.get('terapeuta')
    if terapeuta_id:
        agendas = agendas.filter(terapeuta_id=terapeuta_id)
    
    horarios_grade = get_horarios_clinica()
    range_dias = range(6) 
    
    agenda_map = {t.strftime('%H:%M'): {d: [] for d in range_dias} for t in horarios_grade}
    
    for item in agendas:
        h_str = item.hora_inicio.strftime('%H:%M')
        d = item.dia_semana
        if h_str in agenda_map and d in range_dias:
            agenda_map[h_str][d].append(item)
            
    nomes_dias = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado']

    return render(request, 'lista_agendas_fixas.html', {
        'agenda_map': agenda_map,
        'horarios_grade': horarios_grade,
        'nomes_dias': nomes_dias,
        'terapeutas': Terapeuta.objects.all(),
        'is_admin': True, 
        'filtro_terapeuta': terapeuta_id
    })

@login_required
def nova_agenda_fixa(request):
    if not is_admin(request.user):
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    if request.method == 'POST':
        form = AgendaFixaForm(request.POST)
        if form.is_valid():
            nova_grade = form.save()
            qtd = gerar_agenda_futura(agenda_especifica=nova_grade) 
            messages.success(request, f"Regra criada! {qtd} agendamentos foram lançados no calendário.")
            return redirect(f"{reverse('lista_agendas_fixas')}?terapeuta={nova_grade.terapeuta.id}")
            
    else:
        form = AgendaFixaForm()

    return render(request, 'form_agenda_fixa.html', {'form': form, 'titulo': 'Nova Agenda Fixa'})

@login_required
def editar_agenda_fixa(request, id):
    agenda = get_object_or_404(AgendaFixa, id=id)
    
    if not is_admin(request.user):
        messages.error(request, "Permissão negada.")
        return redirect('dashboard')

    if request.method == 'POST':
        dia_semana_antigo = agenda.dia_semana
        form = AgendaFixaForm(request.POST, instance=agenda)
        if form.is_valid():
            nova_agenda = form.save()
            hoje = timezone.now().date()
            
            if nova_agenda.data_fim:
                Agendamento.objects.filter(
                    agenda_fixa=nova_agenda, data__gt=nova_agenda.data_fim, status='AGUARDANDO'
                ).delete()

            qs_futuros = Agendamento.objects.filter(
                agenda_fixa=nova_agenda, data__gte=hoje, status='AGUARDANDO'
            )
            
            msg_extra = ""
            if nova_agenda.dia_semana != dia_semana_antigo:
                total_removidos = qs_futuros.count()
                qs_futuros.delete()
                msg_extra = f" ({total_removidos} horários realocados para o novo dia)."
            else:
                total_atualizados = qs_futuros.update(
                    terapeuta=nova_agenda.terapeuta, sala=nova_agenda.sala,
                    hora_inicio=nova_agenda.hora_inicio, hora_fim=nova_agenda.hora_fim
                )
                if total_atualizados > 0:
                    msg_extra = f" ({total_atualizados} agendamentos futuros atualizados)."

            gerar_agenda_futura(agenda_especifica=nova_agenda)
            messages.success(request, f"Agenda Fixa salva e sincronizada.{msg_extra}")
            return redirect('lista_agendas_fixas')
    else:
        form = AgendaFixaForm(instance=agenda)

    return render(request, 'form_agenda_fixa.html', {'form': form, 'titulo': 'Editar Agenda Fixa'})

@login_required
def excluir_agenda_fixa(request, id):
    agenda = get_object_or_404(AgendaFixa, id=id)
    
    if not is_admin(request.user):
        messages.error(request, "Permissão negada.")
        return redirect('dashboard')

    if request.method == 'POST':
        # Captura os filtros que vieram do formulário oculto
        filtros_origem = request.POST.get('filtros_origem', '')
        
        agenda.ativo = False
        agenda.save()
        
        limpar = request.POST.get('limpar_futuros')
        msg_extra = ""
        if limpar:
            hoje = timezone.now().date()
            qtd = Agendamento.objects.filter(agenda_fixa=agenda, data__gte=hoje, status='AGUARDANDO').update(deletado=True)
            msg_extra = f" {qtd} agendamentos futuros foram removidos."
            
        messages.success(request, f"Agenda fixa desativada.{msg_extra}")
        
        # Monta a URL de retorno mantendo os filtros
        url_destino = reverse('lista_agendas_fixas')
        if filtros_origem:
            url_destino += f"?{filtros_origem}"
            
        return redirect(url_destino)
    
    # No GET, pegamos os filtros da URL atual para passar ao template
    filtros_origem = request.GET.urlencode()
    
    return render(request, 'confirmar_exclusao_fixa.html', {
        'agenda': agenda,
        'filtros_origem': filtros_origem # Passamos para o template
    })

@login_required
def reposicao_agendamento(request, agendamento_id):
    agendamento_antigo = get_object_or_404(Agendamento, id=agendamento_id)
    filtros = request.GET.urlencode()

    if not is_admin(request.user):
         messages.error(request, "Acesso negado. Contate a administração.")
         return redirect('dashboard')

    precisa_justificar = (agendamento_antigo.status != 'FALTA')

    if request.method == 'POST':
        paciente_id = request.POST.get('paciente')
        
        form_falta = None
        dados_falta_validos = True
        
        if precisa_justificar:
            form_falta = RegistrarFaltaForm(request.POST, prefix='falta', instance=agendamento_antigo)
            if not form_falta.is_valid():
                dados_falta_validos = False
        
        if paciente_id and dados_falta_validos:
            try:
                paciente_selecionado = Paciente.objects.get(id=paciente_id)
                
                if precisa_justificar:
                    agendamento_antigo = form_falta.save(commit=False)
                    agendamento_antigo.status = 'FALTA'
                
                agendamento_antigo.deletado = True
                agendamento_antigo.save()

                Agendamento.objects.create(
                    paciente=paciente_selecionado,
                    terapeuta=agendamento_antigo.terapeuta,
                    sala=agendamento_antigo.sala,
                    data=agendamento_antigo.data,
                    hora_inicio=agendamento_antigo.hora_inicio,
                    hora_fim=agendamento_antigo.hora_fim,
                    status='AGUARDANDO',
                    tipo_atendimento=paciente_selecionado.tipo_padrao
                )

                messages.success(request, "Reposição realizada! Vaga preenchida.")
                url_retorno = redirect('lista_agendamentos').url
                if filtros: url_retorno += f'?{filtros}'
                return redirect(url_retorno)
                
            except Paciente.DoesNotExist:
                messages.error(request, "Paciente inválido.")
        else:
            if not paciente_id: messages.error(request, "Selecione o novo paciente.")
            if form_falta and not form_falta.is_valid(): messages.error(request, "Justifique a falta anterior.")
    
    else:
        if precisa_justificar:
            form_falta = RegistrarFaltaForm(prefix='falta', initial={'tipo_cancelamento': 'JUSTIFICADA'})
        else:
            form_falta = None

    form_paciente = AgendamentoForm() 
    
    return render(request, 'form_reposicao.html', {
        'form_falta': form_falta,
        'form_paciente': form_paciente,
        'agendamento_antigo': agendamento_antigo,
        'precisa_justificar': precisa_justificar
    })

@login_required
def confirmar_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento.objects.ativos(), id=agendamento_id)
    filtros = request.GET.urlencode()

    if not is_admin(request.user) and agendamento.terapeuta.usuario != request.user:
        return redirect('lista_agendamentos')
        
    agendamento.status = 'CONFIRMADO'
    agendamento.save()
    
    url_retorno = redirect('lista_agendamentos').url
    if filtros: url_retorno += f'?{filtros}'
    return redirect(url_retorno)

@login_required
def marcar_falta(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento.objects.ativos(), id=agendamento_id)
    filtros = request.GET.urlencode()

    if not is_admin(request.user) and agendamento.terapeuta.usuario != request.user:
        return redirect('lista_agendamentos')

    if request.method == 'POST':
        form = RegistrarFaltaForm(request.POST, instance=agendamento)
        if form.is_valid():
            agendamento = form.save(commit=False)
            agendamento.status = 'FALTA'
            agendamento.save()
            messages.success(request, "Falta registrada.")
            url_retorno = redirect('lista_agendamentos').url
            if filtros: url_retorno += f'?{filtros}'
            return redirect(url_retorno)
    else:
        form = RegistrarFaltaForm(instance=agendamento)
    
    return render(request, 'form_falta.html', {
        'form': form, 
        'agendamento': agendamento
    })

@login_required
def excluir_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento.objects.ativos(), id=agendamento_id)
    filtros = request.GET.urlencode()

    if not is_admin(request.user):
        messages.error(request, "Apenas a administração pode excluir agendamentos.")
        return redirect('lista_agendamentos')

    if agendamento.agenda_fixa:
        messages.error(request, "Este é um horário de Agenda Fixa. Não é possível excluí-lo individualmente.")
        return redirect('lista_agendamentos')

    agendamento.delete()
    messages.success(request, "Agendamento avulso excluído.")
    
    url_retorno = redirect('lista_agendamentos').url
    if filtros: url_retorno += f'?{filtros}'
    return redirect(url_retorno)

@login_required
def realizar_consulta(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento.objects.ativos(), id=agendamento_id)

    if is_admin(request.user) and not is_dono(request.user):
        messages.error(request, "Perfil Administrativo não tem acesso a prontuários.")
        return redirect('lista_agendamentos')

    if not is_dono(request.user):
        if is_terapeuta(request.user) and agendamento.terapeuta.usuario != request.user:
             messages.error(request, "Acesso negado: Paciente de outro profissional.")
             return redirect('dashboard')

    consulta, _ = Consulta.objects.get_or_create(agendamento=agendamento)
    anexos_existentes = consulta.anexos.all()
    
    params = request.GET.copy()
    origem = params.pop('origem', [''])[0]
    query_string = params.urlencode()
    
    url_voltar = redirect('lista_consultas_geral').url if origem == 'historico' else redirect('lista_agendamentos').url
    if query_string: url_voltar += f"?{query_string}"

    if request.method == 'POST':
        anexo_para_excluir = request.POST.get('excluir_anexo_id')
        if anexo_para_excluir:
            anexo = get_object_or_404(AnexoConsulta, id=anexo_para_excluir, consulta=consulta)
            anexo.arquivo.delete()
            anexo.delete()
            messages.success(request, "Anexo removido.")
            return redirect(request.path + '?' + request.GET.urlencode())

        form = ConsultaForm(request.POST, instance=consulta)
        if form.is_valid():
            form.save()
            
            arquivos = request.FILES.getlist('arquivos_anexos')
            count_anexos = 0
            count_erro_tamanho = 0
            LIMITE_MB = 10
            
            for f in arquivos:
                if f.size > LIMITE_MB * 1024 * 1024:
                    count_erro_tamanho += 1
                    continue
                AnexoConsulta.objects.create(consulta=consulta, arquivo=f)
                count_anexos += 1
            
            agendamento.status = 'REALIZADO'
            if is_dono(request.user):
                novo_tipo = request.POST.get('tipo_atendimento_select')
                if novo_tipo: agendamento.tipo_atendimento = novo_tipo
            agendamento.save()
            
            msg = "Prontuário salvo com sucesso!"
            if count_anexos > 0: msg += f" (+{count_anexos} arquivos)."
            
            if count_erro_tamanho > 0:
                messages.warning(request, f"{msg} Porém, {count_erro_tamanho} arquivo(s) foram ignorados por serem maiores que {LIMITE_MB}MB.")
            else:
                messages.success(request, msg)
            
            return redirect(url_voltar)
    else:
        form = ConsultaForm(instance=consulta)
    
    return render(request, 'realizar_consulta.html', {
        'form': form, 
        'agendamento': agendamento, 
        'anexos': anexos_existentes,
        'url_voltar': url_voltar,
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES 
    })

@login_required
def limpar_dia(request):
    if request.method == 'POST':
        data = request.POST.get('data_para_limpar')
        if data: 
            qs = Agendamento.objects.ativos().filter(data=data).exclude(status='REALIZADO')
            if not is_admin(request.user):
                if is_terapeuta(request.user): qs = qs.filter(terapeuta=request.user.terapeuta)
                else: qs = Agendamento.objects.none()
            qs.update(deletado=True)
            messages.info(request, "Agenda limpa.")
    return redirect('lista_agendamentos')

@login_required
def lista_consultas_geral(request):
    data_inicio_get = request.GET.get('data_inicio')
    data_fim_get = request.GET.get('data_fim')
    filtro_hoje = request.GET.get('filtro_hoje')
    filtro_semana = request.GET.get('filtro_semana')
    busca_nome = request.GET.get('busca_nome')
    filtro_tipo = request.GET.get('filtro_tipo')
    filtro_terapeuta = request.GET.get('filtro_terapeuta')
    filtro_status = request.GET.get('filtro_status')
    
    agora = timezone.localtime(timezone.now())
    hoje = agora.date()
    
    if filtro_hoje: data_inicio, data_fim = hoje, hoje
    elif filtro_semana:
        start = hoje - timedelta(days=hoje.weekday())
        data_inicio, data_fim = start, start + timedelta(days=6)
    elif data_inicio_get and data_fim_get: data_inicio, data_fim = data_inicio_get, data_fim_get
    else:
        data_inicio = hoje.replace(day=1)
        prox_mes = (data_inicio + timedelta(days=32)).replace(day=1)
        data_fim = prox_mes - timedelta(days=1)

    agendamentos = Agendamento.objects.filter(
        Q(deletado=False) | Q(status='FALTA')
    ).exclude(status='AGUARDANDO').select_related('paciente', 'terapeuta').order_by('-data', '-hora_inicio')
    
    if not is_admin(request.user):
        if is_terapeuta(request.user): agendamentos = agendamentos.filter(terapeuta=request.user.terapeuta)
        else: agendamentos = Agendamento.objects.none()

    if data_inicio and data_fim: agendamentos = agendamentos.filter(data__range=[data_inicio, data_fim])
    
    if busca_nome:
        busca_limpa = remover_acentos(busca_nome).lower()
        agendamentos = agendamentos.filter(paciente__nome_search__icontains=busca_limpa)

    if filtro_tipo: agendamentos = agendamentos.filter(tipo_atendimento=filtro_tipo)
    
    if filtro_status == 'FALTA_REPOSTA': agendamentos = agendamentos.filter(status='FALTA', deletado=True)
    elif filtro_status == 'FALTA': agendamentos = agendamentos.filter(status='FALTA', deletado=False)
    elif filtro_status: agendamentos = agendamentos.filter(status=filtro_status)

    if is_admin(request.user) and filtro_terapeuta:
        agendamentos = agendamentos.filter(terapeuta_id=filtro_terapeuta)
        
    return render(request, 'lista_consultas.html', {
        'agendamentos': agendamentos, 
        'terapeutas': Terapeuta.objects.all() if is_admin(request.user) else None,
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES,
        'busca_nome': busca_nome or '',
        'filtro_tipo_selecionado': filtro_tipo,
        'filtro_status_selecionado': filtro_status, 
        'filtro_terapeuta_selecionado': int(filtro_terapeuta) if filtro_terapeuta else None,
        'data_inicio': str(data_inicio) if data_inicio else '',
        'data_fim': str(data_fim) if data_fim else '',
        'filtro_hoje': filtro_hoje,
        'filtro_semana': filtro_semana,
        'is_admin': is_admin(request.user)
    })

@dono_required
def cadastrar_equipe(request):
    setup_grupos()
    if request.method == 'POST':
        form = CadastroEquipeForm(request.POST)
        papel = request.POST.get('papel_sistema') 
        if form.is_valid():
            user = form.save(commit=False)
            user.is_staff = False 
            user.save()
            grupo = None
            if papel == 'admin': grupo = Group.objects.get(name='Administrativo')
            elif papel == 'financeiro': grupo = Group.objects.get(name='Financeiro')
            elif papel == 'dono': grupo = Group.objects.get(name='Donos')
            else: 
                grupo = Group.objects.get(name='Terapeutas')
                Terapeuta.objects.create(
                    usuario=user, nome=form.cleaned_data['nome_completo'],
                    registro_profissional=form.cleaned_data['registro'], especialidade=form.cleaned_data['especialidade']
                )
            user.groups.add(grupo)
            messages.success(request, f"Usuário {user.username} criado como {grupo.name}!")
            return redirect('lista_pacientes') 
    else: 
        form = CadastroEquipeForm()
    return render(request, 'cadastrar_equipe.html', {'form': form})

@login_required
def lista_terapeutas(request):
    if not is_admin(request.user):
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')
    busca = request.GET.get('q')
    filtro_esp = request.GET.get('especialidade')
    terapeutas = Terapeuta.objects.all().select_related('usuario').order_by('nome')
    if busca: terapeutas = terapeutas.filter(nome__icontains=busca)
    if filtro_esp: terapeutas = terapeutas.filter(especialidade=filtro_esp)
    return render(request, 'lista_terapeutas.html', {
        'terapeutas': terapeutas, 'is_admin': is_admin(request.user),
        'especialidades': ESPECIALIDADES_CHOICES, 'busca_atual': busca, 'filtro_esp_selecionado': filtro_esp
    })

@login_required
def ocupacao_salas(request):
    import re # Necessário para identificar os números nos nomes das salas

    if not is_admin(request.user):
        messages.error(request, "Acesso restrito à administração.")
        return redirect('dashboard')

    # 1. Definição de datas
    data_get = request.GET.get('data')
    if data_get:
        data_atual = datetime.strptime(data_get, '%Y-%m-%d').date()
    else:
        data_atual = timezone.now().date()
    
    data_anterior = (data_atual - timedelta(days=1)).strftime('%Y-%m-%d')
    data_proxima = (data_atual + timedelta(days=1)).strftime('%Y-%m-%d')

    # --- 2. Busca e Ordenação Personalizada das Salas ---
    # Ordem desejada: 1, 1A, 2, 3... 8, Reunião, 9... 16
    todas_salas = Sala.objects.all()
    
    def sort_key(sala):
        # Normaliza o nome (minúsculo e sem acentos)
        nome = remover_acentos(sala.nome).lower()
        
        # Regras Específicas
        if '1a' in nome: return 1.5       # "1A" vale 1.5 (fica entre 1 e 2)
        if 'reuniao' in nome: return 8.5  # "Reunião" vale 8.5 (fica entre 8 e 9)
        
        # Regra Numérica: Extrai o primeiro número encontrado
        numeros = re.findall(r'\d+', nome)
        if numeros:
            return float(numeros[0])
            
        return 999.0 # Salas sem número e sem regra ficam no final
    
    # Aplica a ordenação na lista de salas
    salas = sorted(todas_salas, key=sort_key)
    # ----------------------------------------------------

    # 3. Busca agendamentos do dia
    agendamentos = Agendamento.objects.ativos().filter(
        data=data_atual
    ).select_related('paciente', 'terapeuta', 'sala', 'agenda_fixa')

    # 4. Agrupamento (Lógica de "Ana + Bia")
    agrupados = {}

    for item in agendamentos:
        if not item.sala: continue 

        h_str = item.hora_inicio.strftime('%H:%M')
        s_id = item.sala.id
        p_id = item.paciente.id
        
        chave = (h_str, s_id, p_id)
        
        # Pega apenas o primeiro nome do terapeuta
        nome_terapeuta = item.terapeuta.nome.split()[0]

        if chave in agrupados:
            agrupados[chave]['terapeutas'].append(nome_terapeuta)
            if item.agenda_fixa:
                agrupados[chave]['agenda_fixa'] = True
        else:
            agrupados[chave] = {
                'paciente_nome': item.paciente.nome,
                'terapeutas': [nome_terapeuta],
                'agenda_fixa': True if item.agenda_fixa else False
            }

    # 5. Monta a Grade Final
    horarios_grade = get_horarios_clinica()
    agenda_map = {t.strftime('%H:%M'): {s.id: [] for s in salas} for t in horarios_grade}

    for (h_str, s_id, p_id), dados in agrupados.items():
        if h_str in agenda_map and s_id in agenda_map[h_str]:
            texto_terapeutas = " + ".join(dados['terapeutas'])
            
            item_display = {
                'paciente_nome': dados['paciente_nome'],
                'terapeuta_nome': texto_terapeutas,
                'agenda_fixa': dados['agenda_fixa']
            }
            agenda_map[h_str][s_id].append(item_display)

    return render(request, 'ocupacao_salas.html', {
        'agenda_map': agenda_map,
        'horarios_grade': horarios_grade,
        'salas': salas, # Agora enviamos a lista ordenada
        'data_atual': data_atual,
        'data_input': data_atual.strftime('%Y-%m-%d'),
        'data_anterior': data_anterior,
        'data_proxima': data_proxima,
        'is_admin': is_admin(request.user)
    })

@login_required
def relatorio_mensal(request):
    hoje = timezone.now()
    mes_get = request.GET.get('mes')
    mes_filtro = int(mes_get) if mes_get and mes_get != '0' else (hoje.month if mes_get != '0' else 0)
    ano_filtro = int(request.GET.get('ano', hoje.year))
    semana_filtro = request.GET.get('semana')
    
    semanas_opcoes = []
    if mes_filtro:
        cal = calendar.Calendar(firstweekday=0) 
        calendario_mes = cal.monthdatescalendar(ano_filtro, mes_filtro)
        for i, semana in enumerate(calendario_mes):
            semanas_opcoes.append({'id': str(i), 'inicio': semana[0], 'fim': semana[-1], 'label': f"Semana {i+1} ({semana[0].strftime('%d/%m')} - {semana[-1].strftime('%d/%m')})"})

    filtros_base = {'data__year': ano_filtro, 'deletado': False}
    if mes_filtro: filtros_base['data__month'] = mes_filtro
    qs_base = Agendamento.objects.filter(**filtros_base).exclude(status='AGUARDANDO')

    if mes_filtro and semana_filtro:
        try:
            idx = int(semana_filtro)
            if 0 <= idx < len(semanas_opcoes): qs_base = qs_base.filter(data__range=[semanas_opcoes[idx]['inicio'], semanas_opcoes[idx]['fim']])
        except ValueError: pass 

    terapeutas_para_analise = Terapeuta.objects.none()
    titulo_pagina = ""

    if is_admin(request.user):
        terapeutas_para_analise = Terapeuta.objects.all()
        titulo_pagina = "Relatório Geral da Clínica"
    elif is_terapeuta(request.user):
        try: meu_perfil = request.user.terapeuta; terapeutas_para_analise = Terapeuta.objects.filter(id=meu_perfil.id); qs_base = qs_base.filter(terapeuta=meu_perfil); titulo_pagina = "Meu Desempenho Individual"
        except: messages.error(request, "Perfil de terapeuta não encontrado."); return redirect('dashboard')
    else: messages.error(request, "Acesso restrito."); return redirect('dashboard')

    total_realizados = qs_base.filter(status='REALIZADO').count()
    total_faltas = qs_base.filter(status='FALTA').count()
    total_efetivos = total_realizados + total_faltas
    taxa_faltas_geral = round((total_faltas / total_efetivos) * 100, 1) if total_efetivos > 0 else 0

    filtros_tabela = Q(agendamento__data__year=ano_filtro, agendamento__deletado=False)
    if mes_filtro: filtros_tabela &= Q(agendamento__data__month=mes_filtro)
    if mes_filtro and semana_filtro and 'data_ini' in locals(): filtros_tabela &= Q(agendamento__data__range=[semanas_opcoes[int(semana_filtro)]['inicio'], semanas_opcoes[int(semana_filtro)]['fim']])

    stats_terapeutas = terapeutas_para_analise.annotate(
        qtd_atendimentos=Count('agendamento', filter=filtros_tabela & Q(agendamento__status='REALIZADO')),
        qtd_faltas=Count('agendamento', filter=filtros_tabela & Q(agendamento__status='FALTA'))
    ).order_by('-qtd_atendimentos')

    meses = [(1, 'Janeiro'), (2, 'Fevereiro'), (3, 'Março'), (4, 'Abril'), (5, 'Maio'), (6, 'Junho'), (7, 'Julho'), (8, 'Agosto'), (9, 'Setembro'), (10, 'Outubro'), (11, 'Novembro'), (12, 'Dezembro')]

    return render(request, 'relatorio_mensal.html', {
        'titulo_pagina': titulo_pagina, 'stats_terapeutas': stats_terapeutas, 'total_realizados': total_realizados, 'total_faltas': total_faltas,
        'taxa_faltas_geral': taxa_faltas_geral, 'mes_atual': mes_filtro, 'ano_atual': ano_filtro, 'meses': meses,
        'anos_disponiveis': range(hoje.year - 2, hoje.year + 2), 'is_admin': is_admin(request.user), 'semanas_opcoes': semanas_opcoes, 'semana_atual': semana_filtro
    })

@login_required
def relatorio_pacientes(request):
    if not (is_admin(request.user) or is_terapeuta(request.user)): messages.error(request, "Acesso restrito."); return redirect('dashboard')
    hoje = timezone.now(); mes_get = request.GET.get('mes')
    mes_filtro = int(mes_get) if mes_get and mes_get != '0' else (hoje.month if mes_get != '0' else 0)
    ano_filtro = int(request.GET.get('ano', hoje.year))
    tipo_filtro = request.GET.get('tipo_atend')
    ordem_filtro = request.GET.get('ordem', 'taxa_desc') 

    pacientes_base = Paciente.objects.filter(ativo=True)
    filtros_agendamento = Q(agendamento__data__year=ano_filtro)
    condicao_status = ((Q(agendamento__deletado=False) & Q(agendamento__status__in=['REALIZADO', 'FALTA'])) | (Q(agendamento__deletado=True) & Q(agendamento__status='FALTA')))
    filtros_agendamento &= condicao_status

    if mes_filtro: filtros_agendamento &= Q(agendamento__data__month=mes_filtro)
    if is_terapeuta(request.user) and not is_admin(request.user):
        try: meu_perfil = request.user.terapeuta; filtros_agendamento &= Q(agendamento__terapeuta=meu_perfil); pacientes_base = pacientes_base.filter(agendamento__terapeuta=meu_perfil).distinct()
        except: return redirect('dashboard')
    if tipo_filtro: pacientes_base = pacientes_base.filter(tipo_padrao=tipo_filtro)

    ranking_pacientes = pacientes_base.annotate(
        total_agendado=Count('agendamento', filter=filtros_agendamento),
        total_faltas=Count('agendamento', filter=filtros_agendamento & Q(agendamento__status='FALTA') & ~Q(agendamento__tipo_cancelamento='TERAPEUTA')),
        total_realizados=Count('agendamento', filter=filtros_agendamento & Q(agendamento__status='REALIZADO'))
    ).annotate(
        taxa_falta=Case(When(total_agendado=0, then=0.0), default=100.0 * F('total_faltas') / F('total_agendado'), output_field=FloatField())
    ).filter(total_agendado__gt=0)

    if ordem_filtro == 'taxa_desc': ranking_pacientes = ranking_pacientes.order_by('-taxa_falta', '-total_faltas')
    elif ordem_filtro == 'taxa_asc': ranking_pacientes = ranking_pacientes.order_by('taxa_falta', 'total_faltas')
    elif ordem_filtro == 'faltas_desc': ranking_pacientes = ranking_pacientes.order_by('-total_faltas')
    elif ordem_filtro == 'atend_desc': ranking_pacientes = ranking_pacientes.order_by('-total_realizados')
    else: ranking_pacientes = ranking_pacientes.order_by('-taxa_falta')

    meses = [(1, 'Janeiro'), (2, 'Fevereiro'), (3, 'Março'), (4, 'Abril'), (5, 'Maio'), (6, 'Junho'), (7, 'Julho'), (8, 'Agosto'), (9, 'Setembro'), (10, 'Outubro'), (11, 'Novembro'), (12, 'Dezembro')]

    return render(request, 'relatorio_pacientes.html', {
        'ranking_pacientes': ranking_pacientes, 'mes_atual': mes_filtro, 'ano_atual': ano_filtro, 'tipo_atual': tipo_filtro, 'ordem_atual': ordem_filtro, 'meses': meses, 'anos_disponiveis': range(hoje.year - 2, hoje.year + 2), 'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES, 'is_admin': is_admin(request.user)
    })

@login_required
def relatorio_grade_pacientes(request):
    if not is_admin(request.user):
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    pacientes_ids = AgendaFixa.objects.filter(ativo=True).values_list('paciente_id', flat=True).distinct()
    pacientes = Paciente.objects.filter(id__in=pacientes_ids).order_by('nome')
    
    relatorio = []

    for paciente in pacientes:
        agendas = AgendaFixa.objects.filter(paciente=paciente, ativo=True).select_related('terapeuta')
        
        grade_map = defaultdict(lambda: defaultdict(list))
        
        horarios_unicos = set()

        for item in agendas:
            if 0 <= item.dia_semana <= 4: 
                dia = item.dia_semana
                hora = item.hora_inicio
                horarios_unicos.add(hora)
                
                especialidade = item.terapeuta.especialidade if item.terapeuta.especialidade else "Terapeuta"
                if especialidade == 'Terapeuta Ocupacional': especialidade = 'TO'
                
                primeiro_nome = item.terapeuta.nome.split()[0]
                texto = f"{especialidade} ({primeiro_nome})"
                
                grade_map[hora][dia].append(texto)

        horarios_ordenados = sorted(list(horarios_unicos))
        
        linhas_tabela = []
        for hora in horarios_ordenados:
            colunas = []
            for dia in range(5): 
                lista_atendimentos = grade_map[hora][dia]
                if lista_atendimentos:
                    conteudo = " + ".join(lista_atendimentos)
                else:
                    conteudo = ""
                colunas.append(conteudo)
            
            linhas_tabela.append({
                'hora': hora,
                'colunas': colunas
            })

        if linhas_tabela:
            relatorio.append({
                'paciente': paciente,
                'linhas': linhas_tabela
            })

    return render(request, 'relatorio_grade_pacientes.html', {
        'relatorio': relatorio,
        'dias_semana': ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira']
    })

@login_required
def relatorio_atrasos(request):
    # Permite acesso se for Admin OU Terapeuta
    eh_admin = is_admin(request.user)
    eh_terapeuta = is_terapeuta(request.user)

    if not (eh_admin or eh_terapeuta):
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    agora = timezone.localtime(timezone.now())
    # Atraso = Agora > (Fim do atendimento + 24h)
    # Ou seja: Fim do atendimento <= Agora - 24h
    limite_corte = agora - timedelta(hours=24)

    # 1. Query inicial
    candidatos = Agendamento.objects.ativos().filter(
        status='AGUARDANDO',
        data__lte=limite_corte.date()
    ).select_related('terapeuta', 'paciente', 'sala').order_by('terapeuta__nome', 'data')

    # SE FOR TERAPEUTA (E NÃO ADMIN), FILTRA APENAS OS DELE
    if not eh_admin and eh_terapeuta:
        candidatos = candidatos.filter(terapeuta=request.user.terapeuta)

    # 2. Processamento refinado (Data + Hora)
    mapa_atrasos = defaultdict(list)
    total_geral = 0
    
    for item in candidatos:
        hora_ref = item.hora_fim if item.hora_fim else item.hora_inicio
        dt_termino_naive = datetime.combine(item.data, hora_ref)
        dt_termino_aware = timezone.make_aware(dt_termino_naive, timezone.get_current_timezone())
        
        # Verifica 24h exatas
        if dt_termino_aware <= limite_corte:
            delta = agora - dt_termino_aware
            item.atraso_dias = delta.days # Dias inteiros de atraso
            
            # Se for 0 dias (mas > 24h, ex: 25h), mostramos "1 dia" ou tratamos no template
            # Mas o pedido foi "dias exatos". Se delta.days for 0, significa < 48h desde o fim.
            
            mapa_atrasos[item.terapeuta].append(item)
            total_geral += 1

    # 3. Monta lista para o template
    relatorio = []
    for terapeuta, lista in mapa_atrasos.items():
        relatorio.append({
            'terapeuta': terapeuta,
            'quantidade': len(lista),
            'agendamentos': lista
        })

    relatorio.sort(key=lambda x: x['quantidade'], reverse=True)

    return render(request, 'relatorio_atrasos.html', {
        'relatorio': relatorio,
        'total_geral': total_geral,
        'data_corte': limite_corte,
        'is_admin': eh_admin # Passamos flag para personalizar msg no template
    })