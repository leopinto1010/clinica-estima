from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta, datetime
from django.db.models import Q
from django.db import transaction
from django import forms
from django.contrib.auth.models import Group

from .models import Paciente, Terapeuta, Agendamento, Consulta, TIPO_ATENDIMENTO_CHOICES
from .forms import PacienteForm, AgendamentoForm, ConsultaForm, CadastroEquipeForm

from .utils import (
    is_dono, is_admin, is_terapeuta, setup_grupos, 
    criar_agendamentos_em_lote, make_datetime_aware
)

# --- DASHBOARD ---
@login_required
def dashboard(request):
    hoje = timezone.localtime(timezone.now()).date()
    
    if is_admin(request.user):
        agendamentos_lista = Agendamento.objects.select_related('paciente', 'terapeuta').filter(data=hoje, deletado=False).order_by('hora_inicio')
    elif is_terapeuta(request.user):
        try:
            agendamentos_lista = Agendamento.objects.select_related('paciente', 'terapeuta').filter(
                data=hoje, 
                terapeuta=request.user.terapeuta,
                deletado=False
            ).order_by('hora_inicio')
        except AttributeError:
            agendamentos_lista = Agendamento.objects.none()
    else:
        agendamentos_lista = Agendamento.objects.none()

    total_pacientes = Paciente.objects.count()
    total_agendamentos_hoje = agendamentos_lista.count()
    
    return render(request, 'dashboard.html', {
        'agendamentos_hoje': agendamentos_lista,
        'total_pacientes': total_pacientes,
        'total_agendamentos_hoje': total_agendamentos_hoje,
        'is_admin': is_admin(request.user),
    })

# --- PACIENTES ---
@login_required
def lista_pacientes(request):
    query = request.GET.get('q')
    if query:
        pacientes = Paciente.objects.filter(
            Q(nome__icontains=query) | Q(cpf__icontains=query)
        ).order_by('nome')
    else:
        pacientes = Paciente.objects.all().order_by('nome')
    
    return render(request, 'lista_pacientes.html', {
        'pacientes': pacientes,
        'is_admin': is_admin(request.user)
    })

@login_required
def cadastro_paciente(request):
    if not is_admin(request.user):
        messages.error(request, "Permissão negada: Apenas administração cadastra pacientes.")
        return redirect('lista_pacientes')

    if request.method == 'POST':
        form = PacienteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Paciente cadastrado!")
            return redirect('lista_pacientes')
    else:
        form = PacienteForm()
    return render(request, 'cadastro_paciente.html', {'form': form})

@login_required
def editar_paciente(request, paciente_id):
    if not is_admin(request.user):
        messages.error(request, "Permissão negada.")
        return redirect('detalhe_paciente', paciente_id=paciente_id)

    paciente = get_object_or_404(Paciente, id=paciente_id)
    if request.method == 'POST':
        form = PacienteForm(request.POST, instance=paciente)
        if form.is_valid():
            form.save()
            messages.success(request, f"Dados de {paciente.nome} atualizados!")
            return redirect('lista_pacientes')
    else:
        form = PacienteForm(instance=paciente)
    return render(request, 'cadastro_paciente.html', {'form': form, 'editando': True})

@login_required
def detalhe_paciente(request, paciente_id):
    paciente = get_object_or_404(Paciente, id=paciente_id)
    
    tem_permissao = False
    
    if is_admin(request.user):
        tem_permissao = True
    elif is_terapeuta(request.user):
        try:
            vinculo = Agendamento.objects.filter(
                paciente=paciente, 
                terapeuta=request.user.terapeuta
            ).exists()
            if vinculo:
                tem_permissao = True
        except AttributeError:
            pass 
    
    if not tem_permissao:
        messages.error(request, "Você não tem permissão para visualizar o prontuário deste paciente (sem vínculo terapêutico).")
        return redirect('lista_pacientes')

    historico = Consulta.objects.filter(
        agendamento__paciente=paciente,
        agendamento__deletado=False 
    ).select_related('agendamento__terapeuta').order_by('-agendamento__data', '-agendamento__hora_inicio')
    
    terapeutas_ids = historico.values_list('agendamento__terapeuta', flat=True).distinct()
    terapeutas_filtros = Terapeuta.objects.filter(id__in=terapeutas_ids)
    
    ocultar_evolucao = False
    if is_admin(request.user) and not is_dono(request.user):
        ocultar_evolucao = True
    
    return render(request, 'detalhe_paciente.html', {
        'paciente': paciente,
        'historico': historico,
        'terapeutas_filtros': terapeutas_filtros,
        'ocultar_evolucao': ocultar_evolucao,
        'is_admin': is_admin(request.user)
    })

# --- AGENDAMENTOS ---
@login_required
def lista_agendamentos(request):
    data_inicio_get = request.GET.get('data_inicio')
    data_fim_get = request.GET.get('data_fim')
    filtro_hoje = request.GET.get('filtro_hoje')
    filtro_semana = request.GET.get('filtro_semana')
    busca_nome = request.GET.get('busca_nome')
    filtro_tipo = request.GET.get('filtro_tipo')
    filtro_terapeuta = request.GET.get('filtro_terapeuta')
    
    # [ALTERAÇÃO] Captura o filtro de status
    filtro_status = request.GET.get('filtro_status')

    agora = timezone.localtime(timezone.now())
    hoje = agora.date()
    
    if filtro_hoje:
        data_inicio, data_fim = hoje, hoje
    elif filtro_semana:
        start_week = hoje - timedelta(days=hoje.weekday())
        data_inicio, data_fim = start_week, start_week + timedelta(days=6)
    elif data_inicio_get and data_fim_get:
        data_inicio, data_fim = data_inicio_get, data_fim_get
    else:
        if is_admin(request.user):
             data_inicio = hoje.replace(day=1)
             data_fim = (data_inicio + timedelta(days=65)).replace(day=1) - timedelta(days=1)
        else:
             data_inicio = hoje.replace(month=1, day=1)
             data_fim = hoje.replace(month=12, day=31)

    # Base da query com Soft Delete (deletado=False)
    agendamentos = Agendamento.objects.select_related('paciente', 'terapeuta').filter(
        data__range=[data_inicio, data_fim], 
        deletado=False
    ).order_by('data', 'hora_inicio')

    if is_admin(request.user):
        if filtro_terapeuta:
            agendamentos = agendamentos.filter(terapeuta_id=filtro_terapeuta)
    elif is_terapeuta(request.user):
        try:
            agendamentos = agendamentos.filter(terapeuta=request.user.terapeuta)
        except AttributeError:
            agendamentos = Agendamento.objects.none()
    
    if busca_nome:
        agendamentos = agendamentos.filter(paciente__nome__icontains=busca_nome)
    
    if filtro_tipo:
        agendamentos = agendamentos.filter(tipo_atendimento=filtro_tipo)

    # [ALTERAÇÃO] Aplica o filtro de status se selecionado
    if filtro_status:
        agendamentos = agendamentos.filter(status=filtro_status)

    return render(request, 'lista_agendamentos.html', {
        'agendamentos': agendamentos, 
        'agora': agora,
        'data_inicio': str(data_inicio),
        'data_fim': str(data_fim),
        'filtro_hoje': filtro_hoje,
        'filtro_semana': filtro_semana,
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES,
        'terapeutas': Terapeuta.objects.all() if is_admin(request.user) else None,
        'busca_nome': busca_nome or '',
        'filtro_tipo_selecionado': filtro_tipo,
        'filtro_terapeuta_selecionado': int(filtro_terapeuta) if filtro_terapeuta else None,
        
        # [ALTERAÇÃO] Passa opções e valor atual do status para o template
        'status_choices': Agendamento.STATUS_CHOICES,
        'filtro_status_selecionado': filtro_status,
        
        'is_admin': is_admin(request.user)
    })

@login_required
def novo_agendamento(request):
    if request.method == 'POST':
        form = AgendamentoForm(request.POST)
    else:
        form = AgendamentoForm()

    if not is_admin(request.user):
        try:
            terapeuta_logado = request.user.terapeuta
            form.fields['terapeuta'].widget = forms.HiddenInput()
            form.fields['terapeuta'].initial = terapeuta_logado
        except AttributeError:
            messages.error(request, "Seu usuário não tem perfil de Terapeuta.")
            return redirect('dashboard')

    if request.method == 'POST':
        if form.is_valid():
            if not is_admin(request.user):
                form.cleaned_data['terapeuta'] = request.user.terapeuta
            
            try:
                with transaction.atomic():
                    criados, conflitos = criar_agendamentos_em_lote(form.cleaned_data, request.user)
                
                if criados > 0:
                    msg = f"{criados} agendamento(s) realizado(s) com sucesso!"
                    if conflitos:
                        msg += f" Porém, houve conflito nas datas: {', '.join(conflitos)}."
                        messages.warning(request, msg)
                    else:
                        messages.success(request, msg)
                    return redirect('lista_agendamentos')
                else:
                    messages.error(request, f"Não foi possível agendar. Todas as datas selecionadas ({', '.join(conflitos)}) estão ocupadas.")
                    
            except Exception as e:
                messages.error(request, f"Erro inesperado ao salvar: {e}")

    return render(request, 'novo_agendamento.html', {'form': form})

@login_required
def reposicao_agendamento(request, agendamento_id):
    agendamento_antigo = get_object_or_404(Agendamento, id=agendamento_id)
    
    if not is_admin(request.user):
        if agendamento_antigo.terapeuta.usuario != request.user:
             messages.error(request, "Acesso não autorizado.")
             return redirect('dashboard')

    filtros = request.GET.urlencode()
    
    if request.method == 'POST':
        paciente_selecionado = Paciente.objects.get(id=request.POST.get('paciente'))
        novo = Agendamento(
            paciente=paciente_selecionado,
            terapeuta=agendamento_antigo.terapeuta,
            data=agendamento_antigo.data,
            hora_inicio=agendamento_antigo.hora_inicio,
            hora_fim=agendamento_antigo.hora_fim,
            status='AGUARDANDO',
            tipo_atendimento=paciente_selecionado.tipo_padrao 
        )
        novo.save()

        agendamento_antigo.deletado = True
        agendamento_antigo.save()

        url_retorno = redirect('lista_agendamentos').url
        if filtros: url_retorno += f'?{filtros}'
        return redirect(url_retorno)
    else:
        form = AgendamentoForm(initial={
            'terapeuta': agendamento_antigo.terapeuta, 
            'data': agendamento_antigo.data,
            'hora_inicio': agendamento_antigo.hora_inicio,
            'hora_fim': agendamento_antigo.hora_fim
        })
    return render(request, 'form_reposicao.html', {'form': form, 'agendamento_antigo': agendamento_antigo})

# --- AÇÕES GERAIS ---
@login_required
def confirmar_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)
    
    if not is_admin(request.user):
        if agendamento.terapeuta.usuario != request.user:
             messages.error(request, "Acesso negado.")
             return redirect('lista_agendamentos')

    agendamento.status = 'CONFIRMADO'
    agendamento.save()
    return redirect('lista_agendamentos')

@login_required
def marcar_falta(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)

    if not is_admin(request.user):
        if agendamento.terapeuta.usuario != request.user:
             messages.error(request, "Acesso negado.")
             return redirect('lista_agendamentos')

    agendamento.status = 'FALTA'
    agendamento.save()
    return redirect('lista_agendamentos')

@login_required
def cancelar_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)

    if not is_admin(request.user):
        if agendamento.terapeuta.usuario != request.user:
             messages.error(request, "Acesso negado.")
             return redirect('lista_agendamentos')
             
    agendamento.status = 'CANCELADO'
    agendamento.save()
    return redirect('lista_agendamentos')

@login_required
def realizar_consulta(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)

    if is_admin(request.user) and not is_dono(request.user):
        messages.error(request, "Acesso Negado: Perfil Administrativo não acessa prontuários.")
        return redirect(request.META.get('HTTP_REFERER', 'lista_agendamentos'))

    if is_terapeuta(request.user):
        if agendamento.terapeuta.usuario != request.user:
             messages.error(request, "Você não pode atender este paciente.")
             return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

    consulta, _ = Consulta.objects.get_or_create(agendamento=agendamento)
    filtros = request.GET.urlencode()
    
    if request.method == 'POST':
        form = ConsultaForm(request.POST, instance=consulta)
        if form.is_valid():
            form.save()
            agendamento.status = 'REALIZADO'
            if is_dono(request.user):
                novo_tipo = request.POST.get('tipo_atendimento_select')
                if novo_tipo: agendamento.tipo_atendimento = novo_tipo
            
            agendamento.save()
            messages.success(request, "Atendimento finalizado!")
            
            url_retorno = redirect('lista_agendamentos').url
            if filtros: url_retorno += f'?{filtros}'
            return redirect(url_retorno)
    else:
        form = ConsultaForm(instance=consulta)
    
    return render(request, 'realizar_consulta.html', {
        'form': form, 'agendamento': agendamento, 'filtros': filtros,
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES 
    })

@login_required
def excluir_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)

    if not is_admin(request.user):
        if agendamento.terapeuta.usuario != request.user:
             messages.error(request, "Acesso negado.")
             return redirect('lista_agendamentos')

    # Soft Delete
    agendamento.deletado = True
    agendamento.save()
    
    messages.success(request, "Agendamento removido da visualização.")
    return redirect('lista_agendamentos')

@login_required
def limpar_dia(request):
    if request.method == 'POST':
        data = request.POST.get('data_para_limpar')
        if data: 
            qs = Agendamento.objects.filter(data=data).exclude(status='REALIZADO')
            
            if not is_admin(request.user):
                try:
                    qs = qs.filter(terapeuta=request.user.terapeuta)
                except AttributeError:
                    return redirect('lista_agendamentos')
            
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
    data_inicio, data_fim = None, None

    if filtro_hoje: data_inicio, data_fim = hoje, hoje
    elif filtro_semana:
        start = hoje - timedelta(days=hoje.weekday())
        data_inicio, data_fim = start, start + timedelta(days=6)
    elif data_inicio_get and data_fim_get:
        data_inicio, data_fim = data_inicio_get, data_fim_get

    # Histórico mostra tudo, inclusive deletados
    agendamentos = Agendamento.objects.select_related('paciente', 'terapeuta').all().order_by('-data', '-hora_inicio')
    
    if not is_admin(request.user):
        try: agendamentos = agendamentos.filter(terapeuta=request.user.terapeuta)
        except AttributeError: agendamentos = Agendamento.objects.none()

    if data_inicio and data_fim:
        agendamentos = agendamentos.filter(data__range=[data_inicio, data_fim])

    if busca_nome:
        agendamentos = agendamentos.filter(paciente__nome__icontains=busca_nome)
        
    if filtro_tipo:
        agendamentos = agendamentos.filter(tipo_atendimento=filtro_tipo)
    
    if filtro_status:
        agendamentos = agendamentos.filter(status=filtro_status)
        
    if is_admin(request.user) and filtro_terapeuta:
        agendamentos = agendamentos.filter(terapeuta_id=filtro_terapeuta)
        
    return render(request, 'lista_consultas.html', {
        'agendamentos': agendamentos, 
        'terapeutas': Terapeuta.objects.all() if is_admin(request.user) else None,
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES,
        'status_choices': Agendamento.STATUS_CHOICES, 
        'busca_nome': busca_nome or '',
        'filtro_tipo_selecionado': filtro_tipo,
        'filtro_status_selecionado': filtro_status, 
        'filtro_terapeuta_selecionado': int(filtro_terapeuta) if filtro_terapeuta else None,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'filtro_hoje': filtro_hoje,
        'filtro_semana': filtro_semana,
        'is_admin': is_admin(request.user)
    })

@login_required
def cadastrar_equipe(request):
    if not is_dono(request.user):
        messages.error(request, "Acesso restrito ao Dono.")
        return redirect('dashboard')
    
    setup_grupos()

    if request.method == 'POST':
        form = CadastroEquipeForm(request.POST)
        papel = request.POST.get('papel_sistema') 
        
        if form.is_valid():
            user = form.save(commit=False)
            user.is_staff = False 
            user.is_superuser = False
            user.save()
            
            if papel == 'admin':
                grupo = Group.objects.get(name='Administrativo')
                user.groups.add(grupo)
            elif papel == 'financeiro':
                grupo = Group.objects.get(name='Financeiro')
                user.groups.add(grupo)
            else: 
                grupo = Group.objects.get(name='Terapeutas')
                user.groups.add(grupo)
                Terapeuta.objects.create(
                    usuario=user, nome=form.cleaned_data['nome_completo'],
                    registro_profissional=form.cleaned_data['registro'], especialidade=form.cleaned_data['especialidade']
                )

            messages.success(request, f"Usuário {user.username} cadastrado como {grupo.name}!")
            return redirect('lista_pacientes') 
    else: form = CadastroEquipeForm()
    return render(request, 'cadastrar_equipe.html', {'form': form})

@login_required
def excluir_agendamentos_futuros(request, paciente_id):
    paciente = get_object_or_404(Paciente, id=paciente_id)
    hoje = timezone.now().date()
    agora_time = timezone.now().time()
    
    filtro_tempo = Q(data__gt=hoje) | Q(data=hoje, hora_inicio__gt=agora_time)
    
    agendamentos = Agendamento.objects.filter(filtro_tempo, paciente=paciente, deletado=False).exclude(status='REALIZADO')

    if not is_admin(request.user):
        try: agendamentos = agendamentos.filter(terapeuta=request.user.terapeuta)
        except AttributeError: return redirect('detalhe_paciente', paciente_id=paciente_id)
            
    if request.method == 'POST':
        total = agendamentos.count()
        if total > 0:
            agendamentos.update(deletado=True)
            messages.success(request, f"{total} agendamentos removidos.")
    return redirect('detalhe_paciente', paciente_id=paciente_id)