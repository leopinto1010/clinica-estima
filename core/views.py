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

from .models import Paciente, Terapeuta, Agendamento, Consulta, TIPO_ATENDIMENTO_CHOICES, ESPECIALIDADES_CHOICES
from .forms import PacienteForm, AgendamentoForm, ConsultaForm, CadastroEquipeForm
from .decorators import admin_required, terapeuta_required, dono_required, is_admin, is_terapeuta, is_dono
from .utils import setup_grupos, criar_agendamentos_em_lote

# --- DASHBOARD ---
@login_required
def dashboard(request):
    hoje = timezone.localtime(timezone.now()).date()
    
    qs = Agendamento.objects.ativos().filter(data=hoje).select_related('paciente', 'terapeuta').order_by('hora_inicio')

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
    filtros = request.GET.urlencode()
    
    if request.method == 'POST':
        filtros_post = request.POST.get('filtros_persistentes', '')
        form = PacienteForm(request.POST, instance=paciente)
        if form.is_valid():
            form.save()
            messages.success(request, f"Dados de {paciente.nome} atualizados!")
            url_destino = redirect('lista_pacientes').url
            if filtros_post:
                url_destino += f"?{filtros_post}"
            return redirect(url_destino)
    else:
        form = PacienteForm(instance=paciente)
        
    return render(request, 'cadastro_paciente.html', {
        'form': form, 
        'editando': True,
        'filtros_persistentes': filtros
    })

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
    filtros = request.GET.urlencode()

    if not is_admin(request.user):
        if agendamento_antigo.terapeuta.usuario != request.user:
             messages.error(request, "Acesso negado.")
             return redirect('dashboard')

    dt_consulta = datetime.combine(agendamento_antigo.data, agendamento_antigo.hora_inicio)
    if timezone.is_naive(dt_consulta):
        dt_consulta = timezone.make_aware(dt_consulta, timezone.get_current_timezone())
    
    if dt_consulta <= timezone.now():
        messages.error(request, "A reposição só é permitida para horários futuros.")
        url_retorno = redirect('lista_agendamentos').url
        if filtros: url_retorno += f'?{filtros}'
        return redirect(url_retorno)

    if request.method == 'POST':
        paciente_id = request.POST.get('paciente')
        if paciente_id:
            try:
                paciente_selecionado = Paciente.objects.get(id=paciente_id)
                
                Agendamento.objects.create(
                    paciente=paciente_selecionado,
                    terapeuta=agendamento_antigo.terapeuta,
                    data=agendamento_antigo.data,
                    hora_inicio=agendamento_antigo.hora_inicio,
                    hora_fim=agendamento_antigo.hora_fim,
                    status='AGUARDANDO',
                    tipo_atendimento=paciente_selecionado.tipo_padrao
                )

                agendamento_antigo.status = 'FALTA'
                agendamento_antigo.deletado = True
                agendamento_antigo.save()

                messages.success(request, "Vaga preenchida! O agendamento anterior foi removido da visualização.")
                url_retorno = redirect('lista_agendamentos').url
                if filtros: url_retorno += f'?{filtros}'
                return redirect(url_retorno)
                
            except Paciente.DoesNotExist:
                messages.error(request, "Paciente inválido.")
        else:
            messages.error(request, "Por favor, selecione um paciente.")

    form = AgendamentoForm()
    del form.fields['terapeuta']
    del form.fields['data']
    del form.fields['hora_inicio']
    del form.fields['hora_fim']
    
    return render(request, 'form_reposicao.html', {'form': form, 'agendamento_antigo': agendamento_antigo})

# --- AÇÕES GERAIS ---

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

    agendamento.status = 'FALTA'
    agendamento.save()
    
    url_retorno = redirect('lista_agendamentos').url
    if filtros: url_retorno += f'?{filtros}'
    return redirect(url_retorno)

@login_required
def excluir_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento.objects.ativos(), id=agendamento_id)
    filtros = request.GET.urlencode()

    if not is_admin(request.user) and agendamento.terapeuta.usuario != request.user:
        return redirect('lista_agendamentos')

    agendamento.delete()
    messages.success(request, "Agendamento excluído permanentemente.")
    
    url_retorno = redirect('lista_agendamentos').url
    if filtros: url_retorno += f'?{filtros}'
    return redirect(url_retorno)

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
    
    params = request.GET.copy()
    origem = params.pop('origem', [''])[0]
    query_string = params.urlencode()
    
    if origem == 'historico':
        url_voltar = redirect('lista_consultas_geral').url
    else:
        url_voltar = redirect('lista_agendamentos').url
        
    if query_string:
        url_voltar += f"?{query_string}"

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
            
            return redirect(url_voltar)
    else:
        form = ConsultaForm(instance=consulta)
    
    return render(request, 'realizar_consulta.html', {
        'form': form, 
        'agendamento': agendamento, 
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
    
    if filtro_hoje: 
        data_inicio, data_fim = hoje, hoje
    elif filtro_semana:
        start = hoje - timedelta(days=hoje.weekday())
        data_inicio, data_fim = start, start + timedelta(days=6)
    elif data_inicio_get and data_fim_get:
        data_inicio, data_fim = data_inicio_get, data_fim_get
    else:
        data_inicio = hoje.replace(day=1)
        prox_mes = (data_inicio + timedelta(days=32)).replace(day=1)
        data_fim = prox_mes - timedelta(days=1)

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

# --- RELATÓRIOS ---
@login_required
def relatorio_mensal(request):
    hoje = timezone.now()
    mes_filtro = int(request.GET.get('mes', hoje.month))
    ano_filtro = int(request.GET.get('ano', hoje.year))
    semana_filtro = request.GET.get('semana')

    # --- LÓGICA DE SEMANAS ---
    cal = calendar.Calendar(firstweekday=0) 
    calendario_mes = cal.monthdatescalendar(ano_filtro, mes_filtro)
    
    semanas_opcoes = []
    for i, semana in enumerate(calendario_mes):
        inicio = semana[0]
        fim = semana[-1]
        label = f"Semana {i+1} ({inicio.strftime('%d/%m')} - {fim.strftime('%d/%m')})"
        semanas_opcoes.append({
            'id': str(i), 
            'inicio': inicio,
            'fim': fim,
            'label': label
        })

    # QuerySet Base (Mês e Ano)
    # --- CORREÇÃO AQUI: Filtrar deletado=False para ignorar reposições ---
    qs_base = Agendamento.objects.filter(
        data__month=mes_filtro, 
        data__year=ano_filtro,
        deletado=False 
    ).exclude(status='AGUARDANDO')

    # --- APLICA FILTRO DE SEMANA ---
    if semana_filtro:
        try:
            idx = int(semana_filtro)
            if 0 <= idx < len(semanas_opcoes):
                data_ini = semanas_opcoes[idx]['inicio']
                data_fim = semanas_opcoes[idx]['fim']
                qs_base = qs_base.filter(data__range=[data_ini, data_fim])
        except ValueError:
            pass 

    # --- LÓGICA DE PERMISSÃO ---
    terapeutas_para_analise = Terapeuta.objects.none()
    titulo_pagina = ""

    if is_admin(request.user):
        terapeutas_para_analise = Terapeuta.objects.all()
        titulo_pagina = "Relatório Geral da Clínica"
    elif is_terapeuta(request.user):
        try:
            meu_perfil = request.user.terapeuta
            terapeutas_para_analise = Terapeuta.objects.filter(id=meu_perfil.id)
            qs_base = qs_base.filter(terapeuta=meu_perfil)
            titulo_pagina = "Meu Desempenho Individual"
        except Exception:
            messages.error(request, "Perfil de terapeuta não encontrado.")
            return redirect('dashboard')
    else:
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    # 1. Totais Gerais
    total_geral = qs_base.count()
    total_realizados = qs_base.filter(status='REALIZADO').count()
    total_faltas = qs_base.filter(status='FALTA').count()
    
    taxa_faltas_geral = 0
    if total_geral > 0:
        taxa_faltas_geral = round((total_faltas / total_geral) * 100, 1)

    # 2. Dados da Tabela
    # --- CORREÇÃO AQUI: Adicionar agendamento__deletado=False nos filtros da tabela ---
    filtros_tabela = Q(
        agendamento__data__month=mes_filtro,
        agendamento__data__year=ano_filtro,
        agendamento__deletado=False # Ignora faltas que foram repostas
    )
    
    if semana_filtro and 'data_ini' in locals():
        filtros_tabela &= Q(agendamento__data__range=[data_ini, data_fim])

    stats_terapeutas = terapeutas_para_analise.annotate(
        qtd_atendimentos=Count('agendamento', filter=filtros_tabela & Q(agendamento__status='REALIZADO')),
        qtd_faltas=Count('agendamento', filter=filtros_tabela & Q(agendamento__status='FALTA'))
    ).order_by('-qtd_atendimentos')

    meses = [
        (1, 'Janeiro'), (2, 'Fevereiro'), (3, 'Março'), (4, 'Abril'),
        (5, 'Maio'), (6, 'Junho'), (7, 'Julho'), (8, 'Agosto'),
        (9, 'Setembro'), (10, 'Outubro'), (11, 'Novembro'), (12, 'Dezembro')
    ]

    return render(request, 'relatorio_mensal.html', {
        'titulo_pagina': titulo_pagina,
        'stats_terapeutas': stats_terapeutas,
        'total_realizados': total_realizados,
        'total_faltas': total_faltas,
        'taxa_faltas_geral': taxa_faltas_geral,
        'mes_atual': mes_filtro,
        'ano_atual': ano_filtro,
        'meses': meses,
        'anos_disponiveis': range(hoje.year - 2, hoje.year + 2),
        'is_admin': is_admin(request.user),
        'semanas_opcoes': semanas_opcoes,
        'semana_atual': semana_filtro
    })

@login_required
def relatorio_pacientes(request):
    # Apenas Admin e Terapeutas podem ver dados de pacientes
    if not (is_admin(request.user) or is_terapeuta(request.user)):
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    hoje = timezone.now()
    mes_filtro = int(request.GET.get('mes', hoje.month))
    ano_filtro = int(request.GET.get('ano', hoje.year))
    tipo_filtro = request.GET.get('tipo_atend')
    ordem_filtro = request.GET.get('ordem', 'taxa_desc') # Padrão: Maior % de falta

    # --- LÓGICA DE PERMISSÃO ---
    pacientes_base = Paciente.objects.filter(ativo=True)
    filtros_agendamento = Q(
        agendamento__data__month=mes_filtro,
        agendamento__data__year=ano_filtro,
        agendamento__deletado=False 
    )

    if is_terapeuta(request.user) and not is_admin(request.user):
        try:
            meu_perfil = request.user.terapeuta
            filtros_agendamento &= Q(agendamento__terapeuta=meu_perfil)
            pacientes_base = pacientes_base.filter(agendamento__terapeuta=meu_perfil).distinct()
        except:
            return redirect('dashboard')

    if tipo_filtro:
        pacientes_base = pacientes_base.filter(tipo_padrao=tipo_filtro)

    # --- ANOTAÇÃO (Cálculos no Banco) ---
    ranking_pacientes = pacientes_base.annotate(
        total_agendado=Count('agendamento', filter=filtros_agendamento),
        total_faltas=Count('agendamento', filter=filtros_agendamento & Q(agendamento__status='FALTA')),
        total_realizados=Count('agendamento', filter=filtros_agendamento & Q(agendamento__status='REALIZADO'))
    ).annotate(
        # Calcula a taxa de falta para ordenação (Faltas * 100.0 / Agendados)
        # Case/When evita divisão por zero
        taxa_falta=Case(
            When(total_agendado=0, then=0.0),
            default=100.0 * F('total_faltas') / F('total_agendado'),
            output_field=FloatField()
        )
    ).filter(
        total_agendado__gt=0 
    )

    # --- ORDENAÇÃO DINÂMICA ---
    if ordem_filtro == 'taxa_desc':
        ranking_pacientes = ranking_pacientes.order_by('-taxa_falta', '-total_faltas')
    elif ordem_filtro == 'taxa_asc':
        ranking_pacientes = ranking_pacientes.order_by('taxa_falta', 'total_faltas')
    elif ordem_filtro == 'faltas_desc':
        ranking_pacientes = ranking_pacientes.order_by('-total_faltas')
    elif ordem_filtro == 'atend_desc':
        ranking_pacientes = ranking_pacientes.order_by('-total_realizados')
    else:
        # Fallback padrão
        ranking_pacientes = ranking_pacientes.order_by('-taxa_falta')

    meses = [
        (1, 'Janeiro'), (2, 'Fevereiro'), (3, 'Março'), (4, 'Abril'),
        (5, 'Maio'), (6, 'Junho'), (7, 'Julho'), (8, 'Agosto'),
        (9, 'Setembro'), (10, 'Outubro'), (11, 'Novembro'), (12, 'Dezembro')
    ]

    return render(request, 'relatorio_pacientes.html', {
        'ranking_pacientes': ranking_pacientes,
        'mes_atual': mes_filtro,
        'ano_atual': ano_filtro,
        'tipo_atual': tipo_filtro,
        'ordem_atual': ordem_filtro, # Passa para o template manter selecionado
        'meses': meses,
        'anos_disponiveis': range(hoje.year - 2, hoje.year + 2),
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES,
        'is_admin': is_admin(request.user)
    })