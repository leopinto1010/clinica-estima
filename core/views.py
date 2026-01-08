from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta, datetime
from django.db.models import Q
from django.db import transaction
from django import forms
from django.contrib.auth.models import Group

from .models import Paciente, Terapeuta, Agendamento, Consulta, TIPO_ATENDIMENTO_CHOICES, ESPECIALIDADES_CHOICES
from .forms import PacienteForm, AgendamentoForm, ConsultaForm, CadastroEquipeForm
from .decorators import admin_required, terapeuta_required, dono_required, is_admin, is_terapeuta, is_dono
from .utils import setup_grupos, criar_agendamentos_em_lote

# --- DASHBOARD ---
@login_required
def dashboard(request):
    hoje = timezone.localtime(timezone.now()).date()
    
    # Usa o Manager personalizado para trazer apenas ativos automaticamente
    qs = Agendamento.objects.ativos().filter(data=hoje).select_related('paciente', 'terapeuta').order_by('hora_inicio')

    # Filtro de permissão
    if not is_admin(request.user):
        if is_terapeuta(request.user):
            qs = qs.filter(terapeuta=request.user.terapeuta)
        else:
            qs = Agendamento.objects.none()

    total_pacientes = Paciente.objects.count()
    total_agendamentos_hoje = qs.count()
    
    return render(request, 'dashboard.html', {
        'agendamentos_hoje': qs,
        'total_pacientes': total_pacientes,
        'total_agendamentos_hoje': total_agendamentos_hoje,
        'is_admin': is_admin(request.user),
    })

# --- PACIENTES ---
@login_required
def lista_pacientes(request):
    busca = request.GET.get('q')
    filtro_status = request.GET.get('status')
    filtro_tipo = request.GET.get('tipo')

    pacientes = Paciente.objects.all()

    if filtro_status == 'todos':
        pass 
    elif filtro_status == 'inativos':
        pacientes = pacientes.filter(ativo=False)
    else:
        pacientes = pacientes.filter(ativo=True)
        filtro_status = 'ativos'

    if filtro_tipo:
        pacientes = pacientes.filter(tipo_padrao=filtro_tipo)

    if busca:
        pacientes = pacientes.filter(
            Q(nome__icontains=busca) | Q(cpf__icontains=busca)
        )
    
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
        vinculo = Agendamento.objects.ativos().filter(
            paciente=paciente, 
            terapeuta=request.user.terapeuta
        ).exists()
        if vinculo:
            tem_permissao = True
            
    if not tem_permissao:
        messages.error(request, "Sem permissão (sem vínculo terapêutico).")
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
        data_inicio = hoje.replace(day=1)
        prox_mes = data_inicio.replace(day=28) + timedelta(days=4)
        data_fim = prox_mes - timedelta(days=prox_mes.day)

    agendamentos = Agendamento.objects.ativos().select_related('paciente', 'terapeuta').filter(
        data__range=[data_inicio, data_fim]
    ).order_by('data', 'hora_inicio')

    if not is_admin(request.user):
        if is_terapeuta(request.user):
            agendamentos = agendamentos.filter(terapeuta=request.user.terapeuta)
        else:
            agendamentos = Agendamento.objects.none()
    elif filtro_terapeuta:
        agendamentos = agendamentos.filter(terapeuta_id=filtro_terapeuta)
    
    if busca_nome:
        agendamentos = agendamentos.filter(paciente__nome__icontains=busca_nome)
    if filtro_tipo:
        agendamentos = agendamentos.filter(tipo_atendimento=filtro_tipo)
    if filtro_status:
        agendamentos = agendamentos.filter(status=filtro_status)

    return render(request, 'lista_agendamentos.html', {
        'agendamentos': agendamentos, 
        'agora': agora,
        'data_inicio': str(data_inicio), 'data_fim': str(data_fim),
        'filtro_hoje': filtro_hoje, 'filtro_semana': filtro_semana,
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES,
        'terapeutas': Terapeuta.objects.all() if is_admin(request.user) else None,
        'busca_nome': busca_nome or '',
        'filtro_tipo_selecionado': filtro_tipo,
        'filtro_terapeuta_selecionado': int(filtro_terapeuta) if filtro_terapeuta else None,
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
            messages.error(request, "Acesso restrito.")
            return redirect('dashboard')

    if request.method == 'POST' and form.is_valid():
        if not is_admin(request.user):
            form.cleaned_data['terapeuta'] = request.user.terapeuta
        
        try:
            with transaction.atomic():
                criados, conflitos = criar_agendamentos_em_lote(form.cleaned_data, request.user)
            
            if criados > 0:
                msg = f"{criados} agendamentos criados."
                if conflitos:
                    msg += f" (Conflitos ignorados em: {', '.join(conflitos)})"
                    messages.warning(request, msg)
                else:
                    messages.success(request, msg)
                return redirect('lista_agendamentos')
            else:
                messages.error(request, f"Falha: Datas ocupadas ({', '.join(conflitos)}).")
                
        except Exception as e:
            messages.error(request, f"Erro interno: {e}")

    return render(request, 'novo_agendamento.html', {'form': form})

@login_required
def reposicao_agendamento(request, agendamento_id):
    agendamento_antigo = get_object_or_404(Agendamento, id=agendamento_id)
    
    # Verificação de permissão
    if not is_admin(request.user):
        if agendamento_antigo.terapeuta.usuario != request.user:
             messages.error(request, "Acesso negado.")
             return redirect('dashboard')

    # VERIFICAÇÃO DE TEMPO: Só permite repor se for no FUTURO
    dt_consulta = datetime.combine(agendamento_antigo.data, agendamento_antigo.hora_inicio)
    if timezone.is_naive(dt_consulta):
        dt_consulta = timezone.make_aware(dt_consulta, timezone.get_current_timezone())
    
    if dt_consulta <= timezone.now():
        messages.error(request, "A reposição só é permitida antes do horário da consulta.")
        return redirect('lista_agendamentos')

    if request.method == 'POST':
        paciente_selecionado = Paciente.objects.get(id=request.POST.get('paciente'))
        
        # Cria o novo agendamento na vaga
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

        # Marca o antigo como FALTA (se já não for)
        # Não deleta, para manter no histórico como falta
        if agendamento_antigo.status != 'FALTA':
            agendamento_antigo.status = 'FALTA'
            agendamento_antigo.deletado = False
            agendamento_antigo.save()
            messages.success(request, "Reposição realizada! O agendamento anterior foi registrado como Falta.")
        else:
            messages.success(request, "Vaga preenchida com sucesso!")

        return redirect('lista_agendamentos')
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
    agendamento = get_object_or_404(Agendamento.objects.ativos(), id=agendamento_id)
    if not is_admin(request.user) and agendamento.terapeuta.usuario != request.user:
        return redirect('lista_agendamentos')
        
    agendamento.status = 'CONFIRMADO'
    agendamento.save()
    return redirect('lista_agendamentos')

@login_required
def marcar_falta(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento.objects.ativos(), id=agendamento_id)
    if not is_admin(request.user) and agendamento.terapeuta.usuario != request.user:
        return redirect('lista_agendamentos')

    agendamento.status = 'FALTA'
    agendamento.save()
    return redirect('lista_agendamentos')

@login_required
def excluir_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento.objects.ativos(), id=agendamento_id)
    if not is_admin(request.user) and agendamento.terapeuta.usuario != request.user:
        return redirect('lista_agendamentos')

    # Hard Delete (Apagar Permanentemente)
    agendamento.delete()
    messages.success(request, "Agendamento excluído permanentemente.")
    
    return redirect('lista_agendamentos')

@login_required
def realizar_consulta(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento.objects.ativos(), id=agendamento_id)

    if is_admin(request.user) and not is_dono(request.user):
        messages.error(request, "Perfil Administrativo não tem acesso a prontuários médicos.")
        return redirect('lista_agendamentos')

    if not is_dono(request.user):
        if is_terapeuta(request.user) and agendamento.terapeuta.usuario != request.user:
             messages.error(request, "Acesso negado: Este paciente pertence a outro profissional.")
             return redirect('dashboard')

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
            messages.success(request, "Prontuário salvo com sucesso!")
            
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
def limpar_dia(request):
    if request.method == 'POST':
        data = request.POST.get('data_para_limpar')
        if data: 
            qs = Agendamento.objects.ativos().filter(data=data).exclude(status='REALIZADO')
            
            if not is_admin(request.user):
                if is_terapeuta(request.user):
                    qs = qs.filter(terapeuta=request.user.terapeuta)
                else:
                    qs = Agendamento.objects.none()
            
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

    agendamentos = Agendamento.objects.ativos().select_related('paciente', 'terapeuta').order_by('-data', '-hora_inicio')
    
    if not is_admin(request.user):
        if is_terapeuta(request.user):
            agendamentos = agendamentos.filter(terapeuta=request.user.terapeuta)
        else:
            agendamentos = Agendamento.objects.none()

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

            messages.success(request, f"Usuário {user.username} criado como {grupo.name}!")
            return redirect('lista_pacientes') 
    else: 
        form = CadastroEquipeForm()
    return render(request, 'cadastrar_equipe.html', {'form': form})

@login_required
def excluir_agendamentos_futuros(request, paciente_id):
    paciente = get_object_or_404(Paciente, id=paciente_id)
    hoje = timezone.now().date()
    agora_time = timezone.now().time()
    
    filtro_tempo = Q(data__gt=hoje) | Q(data=hoje, hora_inicio__gt=agora_time)
    
    qs = Agendamento.objects.ativos().filter(filtro_tempo, paciente=paciente).exclude(status='REALIZADO')

    if not is_admin(request.user):
         if is_terapeuta(request.user):
            qs = qs.filter(terapeuta=request.user.terapeuta)
         else:
            return redirect('detalhe_paciente', paciente_id=paciente_id)
            
    if request.method == 'POST':
        total = qs.count()
        if total > 0:
            qs.update(deletado=True)
            messages.success(request, f"{total} agendamentos removidos.")
    return redirect('detalhe_paciente', paciente_id=paciente_id)

@login_required
def lista_terapeutas(request):
    if not is_admin(request.user):
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    busca = request.GET.get('q')
    filtro_esp = request.GET.get('especialidade')

    terapeutas = Terapeuta.objects.all().select_related('usuario').order_by('nome')

    if busca:
        terapeutas = terapeutas.filter(nome__icontains=busca)
    
    if filtro_esp:
        terapeutas = terapeutas.filter(especialidade=filtro_esp)
    
    return render(request, 'lista_terapeutas.html', {
        'terapeutas': terapeutas,
        'is_admin': is_admin(request.user),
        'especialidades': ESPECIALIDADES_CHOICES,
        'busca_atual': busca,
        'filtro_esp_selecionado': filtro_esp
    })