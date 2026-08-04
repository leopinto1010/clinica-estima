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
    AgendaFixa, Sala, BloqueioFixo, BloqueioSala
)

from .forms import (
    PacienteForm, AgendamentoForm, ConsultaForm, 
    CadastroEquipeForm, RegistrarFaltaForm, AgendaFixaForm, 
    BloqueioFixoForm, ReposicaoForm, BloqueioSalaForm
)

from .decorators import admin_required, terapeuta_required, dono_required, is_admin, is_terapeuta, is_dono, is_coordenadora
from .utils import setup_grupos, criar_agendamentos_em_lote, gerar_agenda_futura, get_horarios_clinica
from django.urls import reverse

def remover_acentos(texto):
    if not texto: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def encontrar_slot_visual(hora_real, horarios_grade):
    if not horarios_grade: return hora_real.strftime('%H:%M')
    for h in horarios_grade:
        if h == hora_real:
            return h.strftime('%H:%M')
            
    slot_candidato = horarios_grade[0]
    for h in horarios_grade:
        if h > hora_real:
            break
        slot_candidato = h
    return slot_candidato.strftime('%H:%M')

def formatar_nome_terapeuta(nome_completo):
    """Retorna o primeiro nome + primeiro sobrenome para exibição em relatórios."""
    if not nome_completo:
        return ""
    partes = nome_completo.strip().split()
    if len(partes) >= 2:
        return f"{partes[0]} {partes[1]}"
    return partes[0]


def formatar_nome_curto(nome_completo):
    return formatar_nome_terapeuta(nome_completo)


def especialidade_visivel(user):
    if not user.is_authenticated:
        return None
    if not is_coordenadora(user):
        return None
    try:
        return user.terapeuta.especialidade
    except Exception:
        return None


@login_required
def dashboard(request):
    hoje = timezone.localtime(timezone.now()).date()
    qs = Agendamento.objects.ativos().filter(data=hoje).select_related('paciente', 'terapeuta', 'sala').order_by('hora_inicio')

    if not is_admin(request.user):
        if is_terapeuta(request.user):
            qs = qs.filter(terapeuta=request.user.terapeuta)
        elif is_coordenadora(request.user):
            especialidade = especialidade_visivel(request.user)
            if especialidade:
                qs = qs.filter(terapeuta__especialidade=especialidade)
            else:
                qs = Agendamento.objects.none()
        else:
            qs = Agendamento.objects.none()

    agendamentos_lista = list(qs)
    if agendamentos_lista:
        pacientes_ids = [a.paciente_id for a in agendamentos_lista]
        outros_agendamentos = Agendamento.objects.ativos().filter(
            data=hoje,
            paciente_id__in=pacientes_ids
        ).select_related('terapeuta')
        
        joint_map = defaultdict(list)
        for outro in outros_agendamentos:
            chave = (outro.paciente_id, outro.hora_inicio, outro.sala_id)
            joint_map[chave].append(outro.terapeuta.nome)
            
        for a in agendamentos_lista:
            chave = (a.paciente_id, a.hora_inicio, a.sala_id)
            co_ters = [formatar_nome_curto(nome) for nome in joint_map[chave] if nome != a.terapeuta.nome]
            a.co_terapeutas_str = " + ".join(co_ters) if co_ters else ""

    total_pacientes = Paciente.objects.filter(ativo=True).count()
    total_agendamentos_hoje = qs.count()
    
    return render(request, 'dashboard.html', {
        'agendamentos_hoje': agendamentos_lista, 
        'total_pacientes': total_pacientes,
        'total_agendamentos_hoje': total_agendamentos_hoje,
        'is_admin': is_admin(request.user),
        'agora': hoje
    })

@login_required
def lista_pacientes(request):
    # Trava de segurança no código: auto-preenche qualquer falha de salvamento do nome_search
    pacientes_sem_search = Paciente.objects.filter(Q(nome_search__isnull=True) | Q(nome_search__exact=''))
    for p in pacientes_sem_search:
        p.save()

    busca = request.GET.get('q')
    filtro_status = request.GET.get('status')
    filtro_tipo = request.GET.get('tipo')
    filtro_imagem = request.GET.get('imagem') # <-- NOVO FILTRO AQUI

    if is_admin(request.user):
        pacientes = Paciente.objects.all()
        if filtro_status == 'ativos':
            pacientes = pacientes.filter(ativo=True)
        elif filtro_status == 'inativos':
            pacientes = pacientes.filter(ativo=False)
    elif is_coordenadora(request.user):
        especialidade = especialidade_visivel(request.user)
        if especialidade:
            pacientes = Paciente.objects.filter(
                ativo=True,
                agendamento__terapeuta__especialidade=especialidade
            ).distinct()
        else:
            pacientes = Paciente.objects.none()
    else:
        pacientes = Paciente.objects.filter(
            ativo=True, 
            agendamento__terapeuta=request.user.terapeuta
        ).distinct()

    if busca:
        busca = busca.strip() # Remove espaços invisíveis
        busca_limpa = remover_acentos(busca).lower()
        pacientes = pacientes.filter(
            Q(nome_search__icontains=busca_limpa) | 
            Q(nome__icontains=busca) | 
            Q(cpf__icontains=busca)
        )
    
    if filtro_tipo:
        pacientes = pacientes.filter(tipo_padrao=filtro_tipo)
        
    # --- APLICA O FILTRO DE IMAGEM ---
    if filtro_imagem:
        pacientes = pacientes.filter(autorizacao_imagem=filtro_imagem)
    # ---------------------------------
    
    pacientes = pacientes.order_by('nome')

    return render(request, 'lista_pacientes.html', {
        'pacientes': pacientes,
        'is_admin': is_admin(request.user),
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES,
        'filtro_status_selecionado': filtro_status,
        'filtro_tipo_selecionado': filtro_tipo,
        'filtro_imagem_selecionado': filtro_imagem, # <-- PASSANDO PRO TEMPLATE
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
    
    if is_admin(request.user):
        tem_permissao = True
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
    terapeutas_filtros = Terapeuta.objects.filter(id__in=terapeutas_ids).order_by('nome')
    
    ocultar_evolucao = (is_admin(request.user) and not is_dono(request.user)) and not (is_terapeuta(request.user) or is_coordenadora(request.user))
    
    return render(request, 'detalhe_paciente.html', {
        'paciente': paciente,
        'historico': historico,
        'terapeutas_filtros': terapeutas_filtros,
        'ocultar_evolucao': ocultar_evolucao,
        'is_admin': is_admin(request.user)
    })

@login_required
def lista_agendamentos(request):
    data_inicio_get = request.GET.get('data_inicio')
    data_fim_get = request.GET.get('data_fim')
    filtro_hoje = request.GET.get('filtro_hoje')
    filtro_semana = request.GET.get('filtro_semana')
    
    agora = timezone.localtime(timezone.now())
    hoje = agora.date()
    
    if filtro_hoje:
        data_inicio, data_fim = hoje, hoje
    elif data_inicio_get and data_fim_get:
        data_inicio = datetime.strptime(data_inicio_get, '%Y-%m-%d').date()
        data_fim = datetime.strptime(data_fim_get, '%Y-%m-%d').date()
    else:
        start_week = hoje - timedelta(days=hoje.weekday())
        data_inicio, data_fim = start_week, start_week + timedelta(days=6)
        filtro_semana = '1'

    filtro_paciente = request.GET.get('filtro_paciente')
    filtro_tipo = request.GET.get('filtro_tipo')
    filtro_terapeuta = request.GET.get('filtro_terapeuta')
    filtro_status = request.GET.get('filtro_status')
    filtro_sala = request.GET.get('filtro_sala')

    agendamentos = Agendamento.objects.ativos().select_related('paciente', 'terapeuta', 'sala', 'agenda_fixa').filter(
        data__range=[data_inicio, data_fim]
    ).order_by('data', 'hora_inicio')

    bloqueios_fixos = BloqueioFixo.objects.select_related('terapeuta').all()

    if not is_admin(request.user):
        if is_terapeuta(request.user):
            agendamentos = agendamentos.filter(terapeuta=request.user.terapeuta)
            bloqueios_fixos = bloqueios_fixos.filter(terapeuta=request.user.terapeuta)
        elif is_coordenadora(request.user):
            especialidade = especialidade_visivel(request.user)
            if especialidade:
                agendamentos = agendamentos.filter(terapeuta__especialidade=especialidade)
                bloqueios_fixos = bloqueios_fixos.filter(terapeuta__especialidade=especialidade)
            else:
                agendamentos = Agendamento.objects.none()
                bloqueios_fixos = bloqueios_fixos.none()
        if filtro_terapeuta and filtro_terapeuta != 'todos': 
            agendamentos = agendamentos.filter(terapeuta_id=filtro_terapeuta)
            bloqueios_fixos = bloqueios_fixos.filter(terapeuta_id=filtro_terapeuta)
    
    if filtro_paciente:
        agendamentos = agendamentos.filter(paciente_id=filtro_paciente)
        bloqueios_fixos = bloqueios_fixos.none()

    if filtro_tipo: 
        agendamentos = agendamentos.filter(tipo_atendimento=filtro_tipo)
        bloqueios_fixos = bloqueios_fixos.none()

    if filtro_status: 
        agendamentos = agendamentos.filter(status=filtro_status)
        bloqueios_fixos = bloqueios_fixos.none()

    if filtro_sala: 
        agendamentos = agendamentos.filter(sala_id=filtro_sala)
        bloqueios_fixos = bloqueios_fixos.none()

    horarios_existentes = list(agendamentos.values_list('hora_inicio', flat=True))
    horarios_bloqueios = list(bloqueios_fixos.values_list('hora_inicio', flat=True))
    horarios_grade = get_horarios_clinica(horarios_existentes + horarios_bloqueios)

    delta = data_fim - data_inicio
    dates_in_range = []
    for i in range(delta.days + 1):
        dates_in_range.append(data_inicio + timedelta(days=i))

    agenda_map = {t.strftime('%H:%M'): {d.strftime('%Y-%m-%d'): [] for d in dates_in_range} for t in horarios_grade}

    agendamentos_lista = list(agendamentos)
    if agendamentos_lista:
        pacientes_ids = set(a.paciente_id for a in agendamentos_lista)
        
        outros_agendamentos = Agendamento.objects.ativos().filter(
            data__range=[data_inicio, data_fim],
            paciente_id__in=pacientes_ids
        ).select_related('terapeuta')
        
        joint_map = defaultdict(list)
        for o in outros_agendamentos:
            chave = (o.data, o.hora_inicio, o.paciente_id, o.sala_id)
            joint_map[chave].append(o.terapeuta.nome)
            
        for a in agendamentos_lista:
            chave = (a.data, a.hora_inicio, a.paciente_id, a.sala_id)
            co_ters = [formatar_nome_curto(nome) for nome in joint_map[chave] if nome != a.terapeuta.nome]
            a.co_terapeutas_str = " + ".join(co_ters) if co_ters else ""

    for item in agendamentos_lista:
        h_str = encontrar_slot_visual(item.hora_inicio, horarios_grade)
        d_str = item.data.strftime('%Y-%m-%d')
        
        if h_str in agenda_map and d_str in agenda_map[h_str]:
            item.tipo_obj = 'agendamento'
            agenda_map[h_str][d_str].append(item)

    for data_loop in dates_in_range:
        dia_semana_loop = data_loop.weekday()
        d_str = data_loop.strftime('%Y-%m-%d')
        bloqueios_do_dia = [b for b in bloqueios_fixos if b.dia_semana == dia_semana_loop]
        
        for b in bloqueios_do_dia:
            curr_time = datetime.combine(datetime.today(), b.hora_inicio)
            end_time = datetime.combine(datetime.today(), b.hora_fim)
            
            while curr_time < end_time:
                h_str = encontrar_slot_visual(curr_time.time(), horarios_grade)
                
                if h_str in agenda_map and d_str in agenda_map[h_str]:
                    ja_existe = any(
                        isinstance(x, dict) and x.get('id') == b.id and x.get('tipo_obj') == 'bloqueio' 
                        for x in agenda_map[h_str][d_str]
                    )
                    
                    if not ja_existe:
                        bloqueio_visual = {
                            'tipo_obj': 'bloqueio',
                            'id': b.id,
                            'terapeuta': b.terapeuta,
                            'hora_real_inicio': b.hora_inicio,
                            'hora_real_fim': b.hora_fim,
                            'status': 'BLOQUEADO'
                        }
                        agenda_map[h_str][d_str].append(bloqueio_visual)
                
                curr_time += timedelta(minutes=15) 

    return render(request, 'lista_agendamentos.html', {
        'agenda_map': agenda_map,
        'horarios_grade': horarios_grade,
        'dates_in_range': dates_in_range,
        'agora': agora,
        'data_inicio': str(data_inicio), 'data_fim': str(data_fim),
        'filtro_hoje': filtro_hoje, 'filtro_semana': filtro_semana,
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES,
        'pacientes': Paciente.objects.filter(ativo=True).order_by('nome'),
        'terapeutas': Terapeuta.objects.exclude(usuario__is_active=False).order_by('nome') if (is_admin(request.user) or is_coordenadora(request.user)) else None,
        'salas': Sala.objects.all(),
        'filtro_tipo_selecionado': filtro_tipo,
        'filtro_terapeuta_selecionado': filtro_terapeuta, 
        'filtro_sala_selecionado': filtro_sala,
        'status_choices': Agendamento.STATUS_CHOICES,
        'filtro_status_selecionado': filtro_status,
        'is_admin': is_admin(request.user),
        'is_coordenadora': is_coordenadora(request.user),
    })

@login_required
def novo_agendamento(request):
    if not is_admin(request.user) or is_coordenadora(request.user):
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
    eh_admin = is_admin(request.user)
    eh_terapeuta = is_terapeuta(request.user)
    eh_coordenadora = is_coordenadora(request.user)

    if not (eh_admin or eh_terapeuta or eh_coordenadora):
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')
        
    agendas = AgendaFixa.objects.filter(ativo=True).select_related('paciente', 'terapeuta', 'sala')
    bloqueios = BloqueioFixo.objects.select_related('terapeuta').all()
    
    terapeuta_id = request.GET.get('terapeuta')

    if eh_coordenadora:
        especialidade = especialidade_visivel(request.user)
        if especialidade:
            agendas = agendas.filter(terapeuta__especialidade=especialidade)
            bloqueios = bloqueios.filter(terapeuta__especialidade=especialidade)
        else:
            agendas = agendas.none()
            bloqueios = bloqueios.none()
    elif not eh_admin and eh_terapeuta:
        meu_perfil = request.user.terapeuta
        agendas = agendas.filter(terapeuta=meu_perfil)
        bloqueios = bloqueios.filter(terapeuta=meu_perfil)
        terapeuta_id = meu_perfil.id 
    else:
        if terapeuta_id:
            agendas = agendas.filter(terapeuta_id=terapeuta_id)
            bloqueios = bloqueios.filter(terapeuta_id=terapeuta_id)
    
    horarios_fixos = list(agendas.values_list('hora_inicio', flat=True))
    horarios_bloq = list(bloqueios.values_list('hora_inicio', flat=True))
    horarios_grade = get_horarios_clinica(horarios_fixos + horarios_bloq)
    
    range_dias = range(6) 
    
    agenda_map = {t.strftime('%H:%M'): {d: [] for d in range_dias} for t in horarios_grade}
    
    for item in agendas:
        h_str = encontrar_slot_visual(item.hora_inicio, horarios_grade)
        d = item.dia_semana
        if h_str in agenda_map and d in range_dias:
            item.tipo_obj = 'fixo' 
            agenda_map[h_str][d].append(item)

    for b in bloqueios:
        if b.dia_semana in range_dias:
            curr_time = datetime.combine(datetime.today(), b.hora_inicio)
            end_time = datetime.combine(datetime.today(), b.hora_fim)
            
            while curr_time < end_time:
                h_str = encontrar_slot_visual(curr_time.time(), horarios_grade)
                if h_str in agenda_map:
                    ja_existe = any(x.id == b.id and getattr(x, 'tipo_obj', '') == 'bloqueio' for x in agenda_map[h_str][b.dia_semana])
                    if not ja_existe:
                        b.tipo_obj = 'bloqueio'
                        agenda_map[h_str][b.dia_semana].append(b)
                
                curr_time += timedelta(minutes=15)
            
    nomes_dias = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado']

    return render(request, 'lista_agendas_fixas.html', {
        'agenda_map': agenda_map,
        'horarios_grade': horarios_grade,
        'nomes_dias': nomes_dias,
        'terapeutas': Terapeuta.objects.exclude(usuario__is_active=False).order_by('nome') if (eh_admin or eh_coordenadora) else None,
        'is_admin': eh_admin,
        'is_coordenadora': eh_coordenadora,
        'filtro_terapeuta': int(terapeuta_id) if terapeuta_id else None,
        'bloqueio_form': BloqueioFixoForm() if eh_admin else None 
    })

@login_required
def adicionar_bloqueio(request):
    filtro_terapeuta = request.GET.get('terapeuta')
    
    if request.method == 'POST':
        if not is_admin(request.user):
            messages.error(request, "Permissão negada.")
            url_destino = reverse('lista_agendas_fixas')
            if filtro_terapeuta: url_destino += f"?terapeuta={filtro_terapeuta}"
            return redirect(url_destino)
            
        form = BloqueioFixoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Bloqueio fixo criado com sucesso.")
        else:
            messages.error(request, "Erro ao criar bloqueio. Verifique os dados.")
            
    url_destino = reverse('lista_agendas_fixas')
    if filtro_terapeuta:
        url_destino += f"?terapeuta={filtro_terapeuta}"
    return redirect(url_destino) 

@login_required
def excluir_bloqueio(request, bloqueio_id):
    filtro_terapeuta = request.GET.get('terapeuta')

    if not is_admin(request.user):
        messages.error(request, "Permissão negada.")
    else:
        bloqueio = get_object_or_404(BloqueioFixo, id=bloqueio_id)
        bloqueio.delete()
        messages.success(request, "Bloqueio removido.")
    
    url_destino = reverse('lista_agendas_fixas')
    if filtro_terapeuta:
        url_destino += f"?terapeuta={filtro_terapeuta}"
    return redirect(url_destino)

@login_required
def nova_agenda_fixa(request):
    if not is_admin(request.user) or is_coordenadora(request.user):
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
    
    if not is_admin(request.user) or is_coordenadora(request.user):
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
            
            return redirect(f"{reverse('lista_agendas_fixas')}?terapeuta={nova_agenda.terapeuta.id}")
            
    else:
        form = AgendaFixaForm(instance=agenda)

    return render(request, 'form_agenda_fixa.html', {'form': form, 'titulo': 'Editar Agenda Fixa'})

@login_required
def excluir_agenda_fixa(request, id):
    agenda = get_object_or_404(AgendaFixa, id=id)
    
    if not is_admin(request.user) or is_coordenadora(request.user):
        messages.error(request, "Permissão negada.")
        return redirect('dashboard')

    if request.method == 'POST':
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
        
        url_destino = reverse('lista_agendas_fixas')
        if filtros_origem:
            url_destino += f"?{filtros_origem}"
            
        return redirect(url_destino)
    
    filtros_origem = request.GET.urlencode()
    
    return render(request, 'confirmar_exclusao_fixa.html', {
        'agenda': agenda,
        'filtros_origem': filtros_origem
    })

@login_required
def reposicao_agendamento(request, agendamento_id):
    agendamento_antigo = get_object_or_404(Agendamento, id=agendamento_id)
    
    if not is_admin(request.user):
         if agendamento_antigo.terapeuta.usuario != request.user:
             messages.error(request, "Acesso negado. Contate a administração.")
             return redirect('dashboard')

    precisa_justificar = (agendamento_antigo.status != 'FALTA')

    if request.method == 'POST':
        form_reposicao = ReposicaoForm(request.POST)
        form_falta = None
        dados_falta_validos = True

        if precisa_justificar:
            form_falta = RegistrarFaltaForm(request.POST, prefix='falta', instance=agendamento_antigo)
            if not form_falta.is_valid():
                dados_falta_validos = False
        
        if form_reposicao.is_valid() and dados_falta_validos:
            paciente_selecionado = form_reposicao.cleaned_data['paciente']
            sala_selecionada = form_reposicao.cleaned_data['sala']

            try:
                if precisa_justificar:
                    agendamento_antigo = form_falta.save(commit=False)
                    agendamento_antigo.status = 'FALTA'
                
                agendamento_antigo.deletado = True
                agendamento_antigo.save()

                Agendamento.objects.create(
                    paciente=paciente_selecionado,
                    terapeuta=agendamento_antigo.terapeuta,
                    sala=sala_selecionada, 
                    data=agendamento_antigo.data,
                    hora_inicio=agendamento_antigo.hora_inicio,
                    hora_fim=agendamento_antigo.hora_fim,
                    status='AGUARDANDO',
                    tipo_atendimento=paciente_selecionado.tipo_padrao
                )
                
                messages.success(request, "Reposição realizada com sucesso! Vaga preenchida.")
                return redirect('lista_agendamentos')
            
            except Exception as e:
                messages.error(request, f"Erro ao realizar reposição: {e}")

    else:
        form_reposicao = ReposicaoForm(initial={
            'sala': agendamento_antigo.sala
        })
        
        form_falta = RegistrarFaltaForm(prefix='falta', instance=agendamento_antigo) if precisa_justificar else None

    return render(request, 'form_reposicao.html', {
        'form_reposicao': form_reposicao,
        'form_falta': form_falta,
        'agendamento_antigo': agendamento_antigo,
        'precisa_justificar': precisa_justificar
    })

@login_required
def confirmar_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento.objects.ativos(), id=agendamento_id)
    filtros = request.GET.urlencode()

    if is_coordenadora(request.user):
        messages.error(request, "Acesso restrito a esta ação.")
        return redirect('lista_agendamentos')

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

    if is_coordenadora(request.user):
        messages.error(request, "Acesso restrito a esta ação.")
        return redirect('lista_agendamentos')

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

    if not is_admin(request.user) or is_coordenadora(request.user):
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

    if is_coordenadora(request.user):
        messages.error(request, "Perfil de visualização apenas. Não é possível evoluir ou alterar registros.")
        return redirect('lista_agendamentos')

    if is_admin(request.user) and not is_dono(request.user) and not is_terapeuta(request.user):
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
        if not is_admin(request.user) or is_coordenadora(request.user):
            messages.error(request, "Permissão negada.")
            return redirect('lista_agendamentos')

        data = request.POST.get('data_para_limpar')
        terapeuta_id = request.POST.get('terapeuta_id')

        if data: 
            qs = Agendamento.objects.ativos().filter(data=data).exclude(status='REALIZADO')
            
            if terapeuta_id and terapeuta_id != 'todos':
                qs = qs.filter(terapeuta_id=terapeuta_id)

            total = qs.update(deletado=True)
            messages.info(request, f"Agenda limpa. {total} agendamentos removidos.")
            
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
        if is_terapeuta(request.user):
            agendamentos = agendamentos.filter(terapeuta=request.user.terapeuta)
        elif is_coordenadora(request.user):
            especialidade = especialidade_visivel(request.user)
            if especialidade:
                agendamentos = agendamentos.filter(terapeuta__especialidade=especialidade)
            else:
                agendamentos = Agendamento.objects.none()
        else:
            agendamentos = Agendamento.objects.none()

    if data_inicio and data_fim: agendamentos = agendamentos.filter(data__range=[data_inicio, data_fim])
    
    if busca_nome:
        busca_nome = busca_nome.strip()
        busca_limpa = remover_acentos(busca_nome).lower()
        agendamentos = agendamentos.filter(
            Q(paciente__nome_search__icontains=busca_limpa) | 
            Q(paciente__nome__icontains=busca_nome)
        )

    if filtro_tipo: agendamentos = agendamentos.filter(tipo_atendimento=filtro_tipo)
    
    if filtro_status == 'FALTA_REPOSTA': agendamentos = agendamentos.filter(status='FALTA', deletado=True)
    elif filtro_status == 'FALTA': agendamentos = agendamentos.filter(status='FALTA', deletado=False)
    elif filtro_status: agendamentos = agendamentos.filter(status=filtro_status)

    if is_admin(request.user):
        if filtro_terapeuta:
            agendamentos = agendamentos.filter(terapeuta_id=filtro_terapeuta)

    return render(request, 'lista_consultas.html', {
        'agendamentos': agendamentos, 
        'terapeutas': Terapeuta.objects.exclude(usuario__is_active=False).order_by('nome') if (is_admin(request.user) or is_coordenadora(request.user)) else None,
        'tipos_atendimento': TIPO_ATENDIMENTO_CHOICES,
        'busca_nome': busca_nome or '',
        'filtro_tipo_selecionado': filtro_tipo,
        'filtro_status_selecionado': filtro_status, 
        'filtro_terapeuta_selecionado': int(filtro_terapeuta) if filtro_terapeuta else None,
        'data_inicio': str(data_inicio) if data_inicio else '',
        'data_fim': str(data_fim) if data_fim else '',
        'filtro_hoje': filtro_hoje,
        'filtro_semana': filtro_semana,
        'is_admin': is_admin(request.user),
        'is_coordenadora': is_coordenadora(request.user),
    })

@admin_required
def cadastrar_equipe(request):
    setup_grupos()
    if request.method == 'POST':
        form = CadastroEquipeForm(request.POST)
        papel = request.POST.get('papel_sistema')

        if papel == 'dono' and not is_dono(request.user):
            messages.error(request, "Apenas Donos podem cadastrar outro Dono.")
            return redirect('cadastrar_equipe')

        form.fields['especialidade'].required = False

        if form.is_valid():
            user = form.save(commit=False)
            user.is_staff = False
            user.save()

            if papel == 'admin':
                grupo = Group.objects.get(name='Administrativo')
            elif papel == 'dono':
                grupo = Group.objects.get(name='Donos')
            elif papel == 'coordenacao':
                grupo = Group.objects.get(name='Coordenação')
            else:
                grupo = Group.objects.get(name='Terapeutas')

            if papel in ['terapeuta', 'coordenacao']:
                especialidade = form.cleaned_data.get('especialidade')
                if papel == 'coordenacao' and not especialidade:
                    especialidade = 'Coordenação'
                Terapeuta.objects.update_or_create(
                    usuario=user,
                    defaults={
                        'nome': form.cleaned_data['nome_completo'],
                        'registro_profissional': form.cleaned_data['registro'],
                        'especialidade': especialidade,
                        'coordenacao': papel == 'coordenacao',
                    }
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
    import re

    if not is_admin(request.user):
        messages.error(request, "Acesso restrito à administração.")
        return redirect('dashboard')

    data_get = request.GET.get('data')
    if data_get:
        data_atual = datetime.strptime(data_get, '%Y-%m-%d').date()
    else:
        data_atual = timezone.now().date()
    
    data_anterior = (data_atual - timedelta(days=1)).strftime('%Y-%m-%d')
    data_proxima = (data_atual + timedelta(days=1)).strftime('%Y-%m-%d')

    todas_salas = Sala.objects.all()
    
    def sort_key(sala):
        nome = remover_acentos(sala.nome).lower()
        if '1a' in nome: return 1.5
        if 'reuniao' in nome: return 8.5
        numeros = re.findall(r'\d+', nome)
        if numeros: return float(numeros[0])
        return 999.0
    
    salas = sorted(todas_salas, key=sort_key)
    agendamentos = Agendamento.objects.ativos().filter(data=data_atual).select_related('paciente', 'terapeuta', 'sala', 'agenda_fixa')
    
    dia_semana_atual = data_atual.weekday()
    bloqueios_sala = BloqueioSala.objects.filter(dia_semana=dia_semana_atual)

    horarios_reais_hoje = list(agendamentos.values_list('hora_inicio', flat=True))
    horarios_bloq = list(bloqueios_sala.values_list('hora_inicio', flat=True))
    
    horarios_grade = get_horarios_clinica(horarios_reais_hoje + horarios_bloq)

    agrupados = {}

    for item in agendamentos:
        if not item.sala: continue 
        h_str = item.hora_inicio.strftime('%H:%M')
        s_id = item.sala.id
        p_id = item.paciente.id
        chave = (h_str, s_id, p_id)
        
        nome_terapeuta = formatar_nome_curto(item.terapeuta.nome)
        nome_paciente = item.paciente.nome.strip()
        
        if chave in agrupados:
            agrupados[chave]['terapeutas'].append(nome_terapeuta)
            if item.agenda_fixa: agrupados[chave]['agenda_fixa'] = True
        else:
            agrupados[chave] = {
                'paciente_nome': nome_paciente,
                'terapeutas': [nome_terapeuta],
                'agenda_fixa': True if item.agenda_fixa else False,
                'hora_real': item.hora_inicio 
            }

    agenda_map = {t.strftime('%H:%M'): {s.id: [] for s in salas} for t in horarios_grade}

    for (h_str, s_id, p_id), dados in agrupados.items():
        h_visual = encontrar_slot_visual(dados['hora_real'], horarios_grade)
        if h_visual in agenda_map and s_id in agenda_map[h_visual]:
            texto_terapeutas = " + ".join(sorted(list(set(dados['terapeutas']))))
            
            item_display = {
                'tipo': 'agendamento',
                'paciente_nome': dados['paciente_nome'], 
                'terapeuta_nome': texto_terapeutas,
                'agenda_fixa': dados['agenda_fixa']
            }
            agenda_map[h_visual][s_id].append(item_display)

    for b in bloqueios_sala:
        curr_time = datetime.combine(datetime.today(), b.hora_inicio)
        end_time = datetime.combine(datetime.today(), b.hora_fim)
        
        while curr_time < end_time:
            h_visual = encontrar_slot_visual(curr_time.time(), horarios_grade)
            if h_visual in agenda_map and b.sala.id in agenda_map[h_visual]:
                ja_existe = any(x.get('tipo') == 'bloqueio' and x.get('id') == b.id for x in agenda_map[h_visual][b.sala.id])
                if not ja_existe:
                    item_display = {
                        'tipo': 'bloqueio',
                        'id': b.id,
                        'titulo': 'Bloqueado'
                    }
                    agenda_map[h_visual][b.sala.id].append(item_display)
            curr_time += timedelta(minutes=15)

    return render(request, 'ocupacao_salas.html', {
        'agenda_map': agenda_map,
        'horarios_grade': horarios_grade,
        'salas': salas,
        'data_atual': data_atual,
        'data_input': data_atual.strftime('%Y-%m-%d'),
        'data_anterior': data_anterior,
        'data_proxima': data_proxima,
        'is_admin': is_admin(request.user),
        'bloqueio_form': BloqueioSalaForm() if is_admin(request.user) else None,
    })

@login_required
def adicionar_bloqueio_sala(request):
    if request.method == 'POST':
        if not is_admin(request.user):
            messages.error(request, "Permissão negada.")
            return redirect('ocupacao_salas')
        
        form = BloqueioSalaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Sala bloqueada com sucesso.")
        else:
            messages.error(request, "Erro ao bloquear sala. Verifique os dados inseridos.")
            
    return redirect('ocupacao_salas')

@login_required
def excluir_bloqueio_sala(request, bloqueio_id):
    if not is_admin(request.user):
        messages.error(request, "Permissão negada.")
    else:
        bloqueio = get_object_or_404(BloqueioSala, id=bloqueio_id)
        bloqueio.delete()
        messages.success(request, "Bloqueio de sala removido.")
    
    data_get = request.GET.get('data')
    url = reverse('ocupacao_salas')
    if data_get:
        url += f"?data={data_get}"
    return redirect(url)

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
        terapeutas_para_analise = Terapeuta.objects.exclude(usuario__is_active=False).order_by('nome')
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
def relatorio_faltas(request):
    if not (is_admin(request.user) or is_coordenadora(request.user)):
        messages.error(request, "Acesso restrito para a Coordenação.")
        return redirect('dashboard')

    data_inicio_get = request.GET.get('data_inicio')
    data_fim_get = request.GET.get('data_fim')

    hoje = timezone.localtime(timezone.now()).date()
    if data_inicio_get and data_fim_get:
        data_inicio = datetime.strptime(data_inicio_get, '%Y-%m-%d').date()
        data_fim = datetime.strptime(data_fim_get, '%Y-%m-%d').date()
    else:
        data_fim = hoje
        data_inicio = hoje - timedelta(days=89)

    filtros_agendamento = Q(
        agendamento__data__range=[data_inicio, data_fim],
        agendamento__deletado=False,
    ) & Q(agendamento__status__in=['REALIZADO', 'FALTA'])

    pacientes = Paciente.objects.filter(ativo=True).annotate(
        total_atendimentos=Count('agendamento', filter=filtros_agendamento),
        total_realizados=Count('agendamento', filter=filtros_agendamento & Q(agendamento__status='REALIZADO')),
        total_faltas=Count('agendamento', filter=filtros_agendamento & Q(agendamento__status='FALTA')),
    ).filter(total_atendimentos__gt=0).order_by('nome')

    relatorio = []
    for paciente in pacientes:
        total = paciente.total_atendimentos or 0
        realizados = paciente.total_realizados or 0
        faltas = paciente.total_faltas or 0
        percentual_realizado = round((realizados / total) * 100, 2) if total else 0
        percentual_falta = round((faltas / total) * 100, 2) if total else 0
        relatorio.append({
            'paciente': paciente,
            'telefone': paciente.telefone or 'Não informado',
            'percentual_realizado': percentual_realizado,
            'percentual_falta': percentual_falta,
            'total_realizados': realizados,
            'total_faltas': faltas,
            'total_atendimentos': total,
        })

    return render(request, 'relatorio_faltas.html', {
        'relatorio': relatorio,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'is_admin': is_admin(request.user),
        'is_coordenadora': is_coordenadora(request.user),
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
                modalidade = item.modalidade
                if modalidade == 'FISIOTERAPIA': modalidade = None
                if modalidade:
                    if modalidade == 'BOBATH': area_atuacao = "Bobath"
                    elif modalidade == 'PEDIASUIT': area_atuacao = "Pediasuit"
                    elif modalidade == 'RESPIRATORIA': area_atuacao = "Resp"
                    elif modalidade == 'AT': area_atuacao = "AT"
                    elif modalidade == 'PSICOPEDAGOGIA': area_atuacao = "Psicoped"
                    else: area_atuacao = item.get_modalidade_display().split('(')[0].strip()
                else:
                    area_atuacao = item.terapeuta.especialidade if item.terapeuta.especialidade else "Terapeuta"
                    if area_atuacao == 'Terapeuta Ocupacional': area_atuacao = 'TO'
                    elif area_atuacao == 'Fonoaudiólogo(a)': area_atuacao = 'Fono'
                    elif area_atuacao == 'Psicólogo(a)': area_atuacao = 'Psico'
                    elif area_atuacao == 'Psicopedagogo(a)': area_atuacao = 'Psicoped'
                    elif area_atuacao == 'Fisioterapeuta': area_atuacao = 'Fisio'
                    elif area_atuacao == 'Assistente Terapêutico': area_atuacao = 'AT'
                    elif area_atuacao == 'Musicoterapeuta': area_atuacao = 'Music'
                    elif area_atuacao == 'Arteterapeuta': area_atuacao = 'Arte'
                    elif area_atuacao == 'Terapeuta Alimentar': area_atuacao = 'Alim'
                    elif area_atuacao == 'Psicomotricista': area_atuacao = 'Psicomot'
                    elif area_atuacao == 'Nutricionista': area_atuacao = 'Nutri'
                
                primeiro_nome = item.terapeuta.nome.split()[0]
                texto = f"{area_atuacao} ({primeiro_nome})"
                grade_map[hora][dia].append(texto)

        horarios_ordenados = sorted(list(horarios_unicos))
        linhas_tabela = []
        for hora in horarios_ordenados:
            colunas = []
            for dia in range(5): 
                lista_atendimentos = grade_map[hora][dia]
                conteudo = " + ".join(lista_atendimentos) if lista_atendimentos else ""
                colunas.append(conteudo)
            linhas_tabela.append({'hora': hora, 'colunas': colunas})

        if linhas_tabela: relatorio.append({'paciente': paciente, 'linhas': linhas_tabela})

    return render(request, 'relatorio_grade_pacientes.html', {
        'relatorio': relatorio,
        'dias_semana': ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira']
    })

@login_required
def relatorio_atrasos(request):
    eh_admin = is_admin(request.user)
    eh_terapeuta = is_terapeuta(request.user)

    if not (eh_admin or eh_terapeuta):
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    agora = timezone.localtime(timezone.now())
    limite_corte = agora - timedelta(hours=24)

    candidatos = Agendamento.objects.ativos().filter(
        status='AGUARDANDO',
        data__lte=limite_corte.date()
    ).select_related('terapeuta', 'paciente', 'sala').order_by('terapeuta__nome', 'data')

    if not eh_admin and eh_terapeuta:
        candidatos = candidatos.filter(terapeuta=request.user.terapeuta)

    mapa_atrasos = defaultdict(list)
    total_geral = 0
    
    for item in candidatos:
        hora_ref = item.hora_fim if item.hora_fim else item.hora_inicio
        dt_termino_naive = datetime.combine(item.data, hora_ref)
        dt_termino_aware = timezone.make_aware(dt_termino_naive, timezone.get_current_timezone())
        
        if dt_termino_aware <= limite_corte:
            delta = agora - dt_termino_aware
            item.atraso_dias = delta.days 
            mapa_atrasos[item.terapeuta].append(item)
            total_geral += 1

    relatorio = []
    for terapeuta, lista in mapa_atrasos.items():
        relatorio.append({'terapeuta': terapeuta, 'quantidade': len(lista), 'agendamentos': lista})

    relatorio.sort(key=lambda x: x['quantidade'], reverse=True)

    return render(request, 'relatorio_atrasos.html', {
        'relatorio': relatorio,
        'total_geral': total_geral,
        'data_corte': limite_corte,
        'is_admin': eh_admin 
    })

@login_required
def reverter_agendamento(request, agendamento_id):
    agendamento = get_object_or_404(Agendamento.objects.ativos(), id=agendamento_id)
    eh_dono = (is_terapeuta(request.user) and agendamento.terapeuta.usuario == request.user)
    pode_mexer = is_admin(request.user) or eh_dono
    
    if not pode_mexer:
        messages.error(request, "Apenas a recepção ou o terapeuta responsável podem desfazer este status.")
        return redirect('lista_agendamentos')

    if agendamento.status in ['REALIZADO', 'FALTA']:
        if hasattr(agendamento, 'consulta'):
            agendamento.consulta.delete()
        agendamento.status = 'AGUARDANDO'
        agendamento.tipo_cancelamento = None
        agendamento.motivo_cancelamento = None
        agendamento.save()
        messages.success(request, "Correção realizada: Agendamento voltou para 'Aguardando'.")
    
    return redirect('lista_agendamentos')

@login_required
def editar_terapeuta(request, terapeuta_id):
    terapeuta = get_object_or_404(Terapeuta, id=terapeuta_id)
    usuario = terapeuta.usuario
    pode_alterar_papel = request.user.is_superuser or is_dono(request.user)

    if not (pode_alterar_papel or request.user.is_staff):
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    if request.method == 'POST':
        terapeuta.nome = request.POST.get('nome')
        terapeuta.registro_profissional = request.POST.get('registro')
        terapeuta.especialidade = request.POST.get('especialidade')
        terapeuta.save()
        if usuario:
            usuario.is_active = request.POST.get('ativo') == 'on'
            usuario.save()

            if pode_alterar_papel:
                papel = request.POST.get('papel_sistema')
                grupos_esperados = {
                    'terapeuta': 'Terapeutas',
                    'coordenacao': 'Coordenação',
                }
                grupo_nome = grupos_esperados.get(papel, 'Terapeutas')
                grupo, _ = Group.objects.get_or_create(name=grupo_nome)
                usuario.groups.clear()
                usuario.groups.add(grupo)
                terapeuta.coordenacao = papel == 'coordenacao'
                terapeuta.save()

        messages.success(request, f"Dados de {terapeuta.nome} atualizados!")
        return redirect('lista_terapeutas')

    grupos_disponiveis = [
        ('terapeuta', 'Terapeuta'),
        ('coordenacao', 'Coordenação'),
    ]
    papel_atual = 'coordenacao' if terapeuta.coordenacao else 'terapeuta'

    return render(request, 'editar_terapeuta.html', {
        'terapeuta': terapeuta,
        'especialidades': ESPECIALIDADES_CHOICES,
        'grupos_disponiveis': grupos_disponiveis,
        'papel_atual': papel_atual,
        'pode_alterar_papel': pode_alterar_papel,
    })

@dono_required
def excluir_terapeuta(request, terapeuta_id):
    terapeuta = get_object_or_404(Terapeuta, id=terapeuta_id)
    if Agendamento.objects.filter(terapeuta=terapeuta).exists():
        messages.error(request, "Não é possível excluir: este terapeuta possui agendamentos vinculados.")
    else:
        nome = terapeuta.nome
        if terapeuta.usuario: terapeuta.usuario.delete()
        terapeuta.delete()
        messages.success(request, f"Terapeuta {nome} removido com sucesso.")
    return redirect('lista_terapeutas')

@login_required
def controle_atendimentos(request):
    if not (is_admin(request.user) or is_terapeuta(request.user) or is_coordenadora(request.user)):
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    terapeutas = Terapeuta.objects.exclude(usuario__is_active=False).order_by('nome')
    if is_coordenadora(request.user):
        especialidade = especialidade_visivel(request.user)
        if especialidade:
            terapeutas = terapeutas.filter(especialidade=especialidade)
        else:
            terapeutas = Terapeuta.objects.none()

    hoje = timezone.localtime(timezone.now())
    mes_atual = int(request.GET.get('mes', hoje.month))
    ano_atual = int(request.GET.get('ano', hoje.year))
    terapeuta_id = request.GET.get('terapeuta')

    filtro_terapeuta_obj = None
    if is_terapeuta(request.user) and not is_admin(request.user):
        terapeuta_id = request.user.terapeuta.id
    
    if terapeuta_id:
        filtro_terapeuta_obj = get_object_or_404(Terapeuta, id=terapeuta_id)

    cal = calendar.Calendar(firstweekday=0) 
    dias_semana_nomes = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira']
    relatorio_semanal = []

    for dia_idx in range(5): 
        datas_do_mes = [
            d for d in cal.itermonthdates(ano_atual, mes_atual) 
            if d.month == mes_atual and d.weekday() == dia_idx
        ]
        
        agendamentos = Agendamento.objects.filter(
            data__in=datas_do_mes,
            agenda_fixa__isnull=False
        ).filter(
            Q(deletado=False) | Q(status='FALTA')
        ).select_related('paciente', 'terapeuta', 'agenda_fixa').order_by('paciente__nome', 'hora_inicio')

        if filtro_terapeuta_obj:
            agendamentos = agendamentos.filter(terapeuta=filtro_terapeuta_obj)

        linhas_map = {}
        totais_por_data = {data: {'P': 0, 'F': 0} for data in datas_do_mes}
        for ag in agendamentos:
            chave = (ag.paciente.id, ag.agenda_fixa.id)
            if chave not in linhas_map:
                linhas_map[chave] = {
                    'paciente_nome': ag.paciente.nome,
                    'hora': ag.agenda_fixa.hora_inicio,
                    'terapeuta_nome': formatar_nome_terapeuta(ag.terapeuta.nome),
                    'status_por_data': {},
                    'total_p': 0,
                    'total_f': 0
                }
            
            sigla = ''
            if ag.status == 'REALIZADO':
                sigla = 'P'
                linhas_map[chave]['total_p'] += 1
                totais_por_data[ag.data]['P'] += 1
            elif ag.status == 'FALTA':
                sigla = 'F'
                linhas_map[chave]['total_f'] += 1
                totais_por_data[ag.data]['F'] += 1
            
            linhas_map[chave]['status_por_data'][ag.data] = sigla

        linhas_ordenadas = sorted(linhas_map.values(), key=lambda x: (x['paciente_nome'], x['hora']))
        total_dia_p = sum(linha['total_p'] for linha in linhas_ordenadas)
        total_dia_f = sum(linha['total_f'] for linha in linhas_ordenadas)
        
        relatorio_semanal.append({
            'nome_dia': dias_semana_nomes[dia_idx],
            'datas': datas_do_mes,
            'linhas': linhas_ordenadas,
            'totais_por_data': totais_por_data,
            'total_dia_p': total_dia_p,
            'total_dia_f': total_dia_f,
        })

    qs_reposicoes = Agendamento.objects.filter(
        data__month=mes_atual,
        data__year=ano_atual,
        agenda_fixa__isnull=True,
        status='REALIZADO'
    ).select_related('paciente', 'terapeuta').order_by('data', 'paciente__nome')

    if filtro_terapeuta_obj:
        qs_reposicoes = qs_reposicoes.filter(terapeuta=filtro_terapeuta_obj)

    mapa_reposicoes = {} 
    total_reposicoes_mes = 0

    for rep in qs_reposicoes:
        # Adicionado o rep.terapeuta.id na chave
        chave_rep = (rep.data, rep.paciente.id, rep.hora_inicio, rep.terapeuta.id) 
        
        if chave_rep not in mapa_reposicoes:
            mapa_reposicoes[chave_rep] = {
                'paciente_nome': rep.paciente.nome,
                'data': rep.data,
                'hora': rep.hora_inicio, 
                'terapeuta_nome': formatar_nome_terapeuta(rep.terapeuta.nome),
                'qtd_sessoes': 0
            }
        mapa_reposicoes[chave_rep]['qtd_sessoes'] += 1
        total_reposicoes_mes += 1

    lista_reposicoes = sorted(mapa_reposicoes.values(), key=lambda x: (x['data'], x['paciente_nome'], x['hora'], x['terapeuta_nome']))

    meses_pt = [
        (1, 'Janeiro'), (2, 'Fevereiro'), (3, 'Março'), (4, 'Abril'),
        (5, 'Maio'), (6, 'Junho'), (7, 'Julho'), (8, 'Agosto'),
        (9, 'Setembro'), (10, 'Outubro'), (11, 'Novembro'), (12, 'Dezembro')
    ]

    return render(request, 'controle_atendimentos.html', {
        'relatorio_semanal': relatorio_semanal,
        'lista_reposicoes': lista_reposicoes,
        'total_reposicoes_mes': total_reposicoes_mes,
        'meses': meses_pt,
        'anos': range(hoje.year - 2, hoje.year + 2),
        'mes_atual': mes_atual,
        'ano_atual': ano_atual,
        'terapeutas': terapeutas,
        'filtro_terapeuta_selecionado': int(terapeuta_id) if terapeuta_id else None,
        'is_admin': is_admin(request.user),
        'is_coordenadora': is_coordenadora(request.user),
    })

@login_required
def agenda_semanal_sala(request):
    if not is_admin(request.user):
        messages.error(request, "Acesso restrito.")
        return redirect('dashboard')

    sala_id = request.GET.get('sala')
    data_inicio_str = request.GET.get('data_inicio')
    
    if data_inicio_str:
        data_ref = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
    else:
        data_ref = timezone.now().date()
    
    segunda = data_ref - timedelta(days=data_ref.weekday())
    datas_semana = [segunda + timedelta(days=i) for i in range(6)]
    
    sala_selecionada = None
    horarios_extras = []
    
    if sala_id:
        sala_selecionada = get_object_or_404(Sala, id=sala_id)
        
        agendamentos = Agendamento.objects.ativos().filter(
            sala=sala_selecionada,
            data__range=[datas_semana[0], datas_semana[-1]]
        ).select_related('paciente', 'terapeuta')

        horarios_extras = list(agendamentos.values_list('hora_inicio', flat=True))
    
    horarios_grade = get_horarios_clinica(horarios_extras)
    
    agenda_map = {t.strftime('%H:%M'): {d.strftime('%Y-%m-%d'): [] for d in datas_semana} for t in horarios_grade}

    if sala_id:
        temp_map = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'paciente': '', 'terapeutas': set(), 'is_fixa': False})))

        for ag in agendamentos:
            h_visual = encontrar_slot_visual(ag.hora_inicio, horarios_grade)
            d_str = ag.data.strftime('%Y-%m-%d')
            
            if h_visual in agenda_map and d_str in agenda_map[h_visual]:
                grupo = temp_map[h_visual][d_str][ag.paciente.id]
                
                grupo['paciente'] = ag.paciente.nome.strip()
                grupo['terapeutas'].add(formatar_nome_curto(ag.terapeuta.nome))
                
                if ag.agenda_fixa:
                    grupo['is_fixa'] = True

        for h_str, dias in temp_map.items():
            for d_str, pacientes_dict in dias.items():
                lista_final = []
                for pid, dados in pacientes_dict.items():
                    nomes_terapeutas = sorted(list(dados['terapeutas']))
                    str_terapeutas = " + ".join(nomes_terapeutas)
                    
                    lista_final.append({
                        'paciente_nome': dados['paciente'],
                        'terapeuta_nome': str_terapeutas,
                        'is_fixa': dados['is_fixa']
                    })
                
                agenda_map[h_str][d_str] = lista_final

    return render(request, 'relatorio_sala_semanal.html', {
        'sala_selecionada': sala_selecionada,
        'salas': Sala.objects.all(),
        'datas_semana': datas_semana,
        'agenda_map': agenda_map,
        'horarios_grade': horarios_grade,
        'data_inicio_input': segunda.strftime('%Y-%m-%d'),
        'is_admin': True
    })