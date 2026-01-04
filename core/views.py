from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta, datetime
from django.db.models import Q
from .models import Paciente, Terapeuta, Agendamento, Consulta
from .forms import PacienteForm, AgendamentoForm, ConsultaForm, CadastroEquipeForm

# --- DASHBOARD ---
@login_required
def dashboard(request):
    hoje = timezone.now().date()
    
    # Lógica de Filtro por Perfil
    if request.user.is_superuser:
        # Admin vê tudo de hoje
        agendamentos_lista = Agendamento.objects.filter(data=hoje).order_by('hora_inicio')
    else:
        # Terapeuta vê apenas os seus de hoje
        try:
            terapeuta_logado = request.user.terapeuta 
            agendamentos_lista = Agendamento.objects.filter(data=hoje, terapeuta=terapeuta_logado).order_by('hora_inicio')
        except:
            agendamentos_lista = Agendamento.objects.none()

    total_pacientes = Paciente.objects.count()
    total_agendamentos_hoje = agendamentos_lista.count()
    
    return render(request, 'dashboard.html', {
        'agendamentos_hoje': agendamentos_lista,
        'total_pacientes': total_pacientes,
        'total_agendamentos_hoje': total_agendamentos_hoje,
    })

# --- PACIENTES ---
@login_required
def lista_pacientes(request):
    query = request.GET.get('q')
    if query:
        pacientes = Paciente.objects.filter(nome__icontains=query).order_by('nome')
    else:
        pacientes = Paciente.objects.all().order_by('nome')
    return render(request, 'lista_pacientes.html', {'pacientes': pacientes})

@login_required
def cadastro_paciente(request):
    # SEGURANÇA: Apenas Admins podem cadastrar
    if not request.user.is_superuser:
        messages.error(request, "Apenas administradores podem cadastrar novos pacientes.")
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
    # SEGURANÇA: Apenas Admins podem editar
    if not request.user.is_superuser:
        messages.error(request, "Apenas administradores podem alterar dados de pacientes.")
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
    
    # Busca todo o histórico desse paciente (Ordenação ajustada para novos campos)
    historico = Consulta.objects.filter(agendamento__paciente=paciente).order_by('-agendamento__data', '-agendamento__hora_inicio')

    terapeutas_ids = historico.values_list('agendamento__terapeuta', flat=True).distinct()
    terapeutas_filtros = Terapeuta.objects.filter(id__in=terapeutas_ids)
    
    return render(request, 'detalhe_paciente.html', {
        'paciente': paciente,
        'historico': historico,
        'terapeutas_filtros': terapeutas_filtros
    })

# --- AGENDAMENTOS ---
@login_required
def lista_agendamentos(request):
    # Pega os parâmetros da URL
    data_inicio_get = request.GET.get('data_inicio')
    data_fim_get = request.GET.get('data_fim')
    filtro_hoje = request.GET.get('filtro_hoje')     # Nova caixinha
    filtro_semana = request.GET.get('filtro_semana') # Nova caixinha
    
    agora = timezone.now()
    hoje = agora.date()
    
    # --- 1. DEFINE O INTERVALO DE DATAS ---
    
    # Cenário A: Usuário marcou "Apenas Hoje"
    if filtro_hoje:
        data_inicio = hoje
        data_fim = hoje
        
    # Cenário B: Usuário marcou "Esta Semana"
    elif filtro_semana:
        # Calcula segunda-feira (0) até domingo (6) da semana atual
        start_week = hoje - timedelta(days=hoje.weekday())
        end_week = start_week + timedelta(days=6)
        data_inicio = start_week
        data_fim = end_week
        
    # Cenário C: Usuário preencheu datas manualmente nos campos
    elif data_inicio_get and data_fim_get:
        data_inicio = data_inicio_get
        data_fim = data_fim_get
        
    # Cenário D: Nenhum filtro (Padrão automático)
    else:
        if request.user.is_superuser:
            # Regra Admin: Mês Anterior, Atual e Próximo
            primeiro_dia_mes_atual = hoje.replace(day=1)
            inicio_padrao = (primeiro_dia_mes_atual - timedelta(days=1)).replace(day=1)
            data_futura = primeiro_dia_mes_atual + timedelta(days=65)
            fim_padrao = data_futura.replace(day=1) - timedelta(days=1)
        else:
            # Regra Terapeuta: Ano Corrente Inteiro
            inicio_padrao = hoje.replace(month=1, day=1)
            fim_padrao = hoje.replace(month=12, day=31)
        
        data_inicio = inicio_padrao
        data_fim = fim_padrao

    # --- 2. BUSCA NO BANCO (QUERYSET) ---
    
    if request.user.is_superuser:
        agendamentos = Agendamento.objects.all().order_by('data', 'hora_inicio')
    else:
        try:
            terapeuta_logado = request.user.terapeuta
            agendamentos = Agendamento.objects.filter(terapeuta=terapeuta_logado).order_by('data', 'hora_inicio')
        except:
            agendamentos = Agendamento.objects.none()
    
    # Aplica o filtro de data calculado acima
    agendamentos = agendamentos.filter(data__range=[data_inicio, data_fim])
        
    return render(request, 'lista_agendamentos.html', {
        'agendamentos': agendamentos, 
        'agora': agora,
        # Passamos as datas para preencher os inputs
        'data_inicio': str(data_inicio),
        'data_fim': str(data_fim),
        # Passamos o estado dos checkboxes para mantê-los marcados se necessário
        'filtro_hoje': filtro_hoje,
        'filtro_semana': filtro_semana
    })

@login_required
def novo_agendamento(request):
    if request.method == 'POST':
        form = AgendamentoForm(request.POST)
    else:
        form = AgendamentoForm()

    # Se não for admin, remove o campo de escolha do terapeuta
    if not request.user.is_superuser:
        if 'terapeuta' in form.fields:
            del form.fields['terapeuta']

    if request.method == 'POST':
        if form.is_valid():
            agendamento_principal = form.save(commit=False)
            
            # Se não preencheu hora fim, sugere 1h depois automaticamente
            if not agendamento_principal.hora_fim and agendamento_principal.hora_inicio:
                 dt_inicio = datetime.combine(datetime.today(), agendamento_principal.hora_inicio)
                 dt_fim = dt_inicio + timedelta(hours=1)
                 agendamento_principal.hora_fim = dt_fim.time()

            # Vincula o terapeuta automaticamente se não for admin
            if not request.user.is_superuser:
                try:
                    agendamento_principal.terapeuta = request.user.terapeuta
                except Exception:
                    messages.error(request, "ERRO: O usuário logado não está vinculado a nenhum cadastro de Terapeuta.")
                    return redirect('dashboard')
            
            agendamento_principal.save()

            # Lógica de Repetição Semanal
            repeticoes = form.cleaned_data.get('repeticoes', 0)
            if repeticoes > 0:
                for i in range(1, repeticoes + 1):
                    # Soma semanas apenas na DATA
                    nova_data = agendamento_principal.data + timedelta(weeks=i)
                    
                    Agendamento.objects.create(
                        paciente=agendamento_principal.paciente,
                        terapeuta=agendamento_principal.terapeuta,
                        data=nova_data,
                        hora_inicio=agendamento_principal.hora_inicio, # Mantém a hora
                        hora_fim=agendamento_principal.hora_fim,       # Mantém a hora
                        status='AGUARDANDO'
                    )
            
            messages.success(request, "Agendamento realizado!")
            return redirect('lista_agendamentos')

    return render(request, 'novo_agendamento.html', {'form': form})

@login_required
def reposicao_agendamento(request, agendamento_id):
    agendamento_antigo = get_object_or_404(Agendamento, id=agendamento_id)
    filtros = request.GET.urlencode()
    
    if request.method == 'POST':
        form = AgendamentoForm(request.POST)
        if form.is_valid():
            novo = form.save(commit=False)
            # Copia os dados exatos da vaga (Data e Horários)
            novo.data = agendamento_antigo.data
            novo.hora_inicio = agendamento_antigo.hora_inicio
            novo.hora_fim = agendamento_antigo.hora_fim
            novo.terapeuta = agendamento_antigo.terapeuta
            novo.status = 'AGUARDANDO'
            novo.save()
            
            url_retorno = redirect('lista_agendamentos').url
            if filtros:
                url_retorno += f'?{filtros}'
            return redirect(url_retorno)
    else:
        # Preenche o form com os campos separados
        form = AgendamentoForm(initial={
            'terapeuta': agendamento_antigo.terapeuta, 
            'data': agendamento_antigo.data,
            'hora_inicio': agendamento_antigo.hora_inicio,
            'hora_fim': agendamento_antigo.hora_fim
        })
    
    return render(request, 'form_reposicao.html', {
        'form': form, 
        'agendamento_antigo': agendamento_antigo,
        'filtros': filtros
    })

# --- AÇÕES COM MEMÓRIA DE FILTRO ---
@login_required
def confirmar_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)
    agendamento.status = 'CONFIRMADO'
    agendamento.save()
    
    filtros = request.GET.urlencode()
    response = redirect('lista_agendamentos')
    if filtros:
        response['Location'] += f'?{filtros}'
    return response

@login_required
def marcar_falta(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)
    agendamento.status = 'FALTA'
    agendamento.save()
    
    filtros = request.GET.urlencode()
    response = redirect('lista_agendamentos')
    if filtros:
        response['Location'] += f'?{filtros}'
    return response

@login_required
def cancelar_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)
    agendamento.status = 'CANCELADO'
    agendamento.save()
    
    filtros = request.GET.urlencode()
    response = redirect('lista_agendamentos')
    if filtros:
        response['Location'] += f'?{filtros}'
    return response

@login_required
def realizar_consulta(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)
    consulta, _ = Consulta.objects.get_or_create(agendamento=agendamento)
    filtros = request.GET.urlencode()
    
    if request.method == 'POST':
        form = ConsultaForm(request.POST, instance=consulta)
        if form.is_valid():
            form.save()
            agendamento.status = 'REALIZADO'
            agendamento.save()
            
            url_retorno = redirect('lista_agendamentos').url
            if filtros:
                url_retorno += f'?{filtros}'
            messages.success(request, "Atendimento finalizado!")
            return redirect(url_retorno)
    else:
        form = ConsultaForm(instance=consulta)
    
    return render(request, 'realizar_consulta.html', {
        'form': form, 
        'agendamento': agendamento,
        'filtros': filtros
    })

@login_required
def excluir_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento, id=agendamento_id)
    status_protegidos = ['REALIZADO', 'FALTA', 'CANCELADO']
    
    if agendamento.status in status_protegidos:
        messages.error(request, f"Não é possível excluir registros com status '{agendamento.get_status_display()}'.")
    else:
        agendamento.delete()
        messages.success(request, "Agendamento removido.")
        
    filtros = request.GET.urlencode()
    response = redirect('lista_agendamentos')
    if filtros:
        response['Location'] += f'?{filtros}'
    return response

@login_required
def limpar_dia(request):
    if request.method == 'POST':
        data = request.POST.get('data_para_limpar')
        if data: 
            # Atualizado para filtrar apenas pelo campo 'data'
            Agendamento.objects.filter(data=data).exclude(status='REALIZADO').delete()
            messages.info(request, "Dia limpo (exceto realizados).")
    return redirect('lista_agendamentos')

@login_required
def lista_consultas_geral(request):
    paciente_id = request.GET.get('paciente')
    data_unica = request.GET.get('data_unica')
    data_inicio = request.GET.get('data_inicio')
    data_fim = request.GET.get('data_fim')
    
    # Ordena por data e hora decrescente
    agendamentos = Agendamento.objects.all().order_by('-data', '-hora_inicio')
    
    if not request.user.is_superuser:
        try:
             agendamentos = agendamentos.filter(terapeuta=request.user.terapeuta)
        except:
             agendamentos = Agendamento.objects.none()

    if paciente_id: agendamentos = agendamentos.filter(paciente_id=paciente_id)
    
    # Atualizado para filtros diretos em 'data'
    if data_unica: 
        agendamentos = agendamentos.filter(data=data_unica)
    elif data_inicio and data_fim: 
        agendamentos = agendamentos.filter(data__range=[data_inicio, data_fim])
        
    return render(request, 'lista_consultas.html', {
        'agendamentos': agendamentos, 
        'pacientes': Paciente.objects.all().order_by('nome'),
        'paciente_selecionado': int(paciente_id) if paciente_id else None,
        'data_unica': data_unica,
        'data_inicio': data_inicio,
        'data_fim': data_fim
    })

@login_required
def cadastrar_equipe(request):
    if not request.user.is_superuser:
        messages.error(request, "Apenas administradores podem cadastrar equipe.")
        return redirect('dashboard')

    if request.method == 'POST':
        form = CadastroEquipeForm(request.POST)
        if form.is_valid():
            novo_usuario = form.save(commit=False)
            novo_usuario.is_staff = False 
            novo_usuario.is_superuser = False
            novo_usuario.save()

            Terapeuta.objects.create(
                usuario=novo_usuario, 
                nome=form.cleaned_data['nome_completo'],
                registro_profissional=form.cleaned_data['registro'],
                especialidade=form.cleaned_data['especialidade']
            )

            messages.success(request, f"Terapeuta {novo_usuario.username} cadastrado com sucesso!")
            return redirect('lista_pacientes') 
    else:
        form = CadastroEquipeForm()

    return render(request, 'cadastrar_equipe.html', {'form': form})

@login_required
def excluir_agendamentos_futuros(request, paciente_id):
    paciente = get_object_or_404(Paciente, id=paciente_id)
    hoje = timezone.now().date()
    agora_time = timezone.now().time()
    
    # Lógica "Futuro": Datas maiores que hoje OU (Data é hoje E Hora maior que agora)
    # Filtro para datas futuras puras
    filtro_futuro = Q(data__gt=hoje)
    # Filtro para hoje, mas horário futuro
    filtro_hoje_futuro = Q(data=hoje, hora_inicio__gt=agora_time)
    
    agendamentos = Agendamento.objects.filter(
        filtro_futuro | filtro_hoje_futuro,
        paciente=paciente
    ).exclude(status='REALIZADO')

    if not request.user.is_superuser:
        try:
            terapeuta_logado = request.user.terapeuta
            agendamentos = agendamentos.filter(terapeuta=terapeuta_logado)
        except:
            messages.error(request, "Você não tem permissão para realizar essa ação.")
            return redirect('detalhe_paciente', paciente_id=paciente_id)
            
    if request.method == 'POST':
        total = agendamentos.count()
        if total > 0:
            agendamentos.delete()
            messages.success(request, f"{total} agendamentos futuros de {paciente.nome} foram removidos.")
        else:
            messages.warning(request, "Não havia agendamentos futuros para excluir.")
            
    return redirect('detalhe_paciente', paciente_id=paciente_id)