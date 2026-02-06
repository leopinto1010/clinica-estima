from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Paciente, Terapeuta, Agendamento, Consulta, ESPECIALIDADES_CHOICES, AgendaFixa, Sala, BloqueioFixo
from datetime import datetime, timedelta, time
from django.utils import timezone
from .utils import get_horarios_clinica

class CadastroEquipeForm(UserCreationForm):
    nome_completo = forms.CharField(max_length=100, label="Nome Completo")
    registro = forms.CharField(max_length=50, required=False, label="Registro Profissional")
    especialidade = forms.ChoiceField(
        choices=[('', 'Selecione a especialidade...')] + ESPECIALIDADES_CHOICES,
        required=False, label="Especialidade / Área",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    class Meta:
        model = User
        fields = ['username', 'nome_completo', 'registro', 'especialidade']

class PacienteForm(forms.ModelForm):
    class Meta:
        model = Paciente
        fields = ['nome', 'cpf', 'data_nascimento', 'telefone', 'tipo_padrao', 'convenio', 'carteirinha', 'ativo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome Completo'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apenas números'}),
            'data_nascimento': forms.DateInput(
                format='%Y-%m-%d', 
                attrs={'class': 'form-control seletor-apenas-data', 'type': 'date'}
            ),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo_padrao': forms.Select(attrs={'class': 'form-control'}),
            'convenio': forms.Select(attrs={'class': 'form-control'}),
            'carteirinha': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nº da Carteira'}),
        }

class AgendamentoForm(forms.ModelForm):
    repeticoes = forms.IntegerField(
        required=False, initial=0, min_value=0, max_value=48, 
        label="Repetir por quantas semanas?",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0 = Apenas hoje'})
    )
    
    hora_inicio = forms.TimeField(
        label="Horário de Início",
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'})
    )

    class Meta:
        model = Agendamento
        fields = ['paciente', 'terapeuta', 'modalidade', 'sala', 'data', 'hora_inicio', 'hora_fim']
        widgets = {
            'paciente': forms.Select(attrs={'class': 'form-control campo-busca'}),
            'terapeuta': forms.Select(attrs={'class': 'form-control campo-busca'}),
            'modalidade': forms.Select(attrs={'class': 'form-select'}),
            'sala': forms.Select(attrs={'class': 'form-select'}),
            'data': forms.DateInput(attrs={'class': 'form-control seletor-apenas-data'}),
            'hora_fim': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sala'].required = True
        self.fields['sala'].label = "Sala de Atendimento"
        self.fields['hora_fim'].required = False
        
        self.fields['modalidade'].empty_label = "Padrão do Terapeuta"
        
        self.fields['paciente'].queryset = Paciente.objects.filter(ativo=True).order_by('nome')

    def clean(self):
        cleaned_data = super().clean()
        terapeuta = cleaned_data.get('terapeuta')
        data = cleaned_data.get('data')
        hora_inicio = cleaned_data.get('hora_inicio')
        hora_fim = cleaned_data.get('hora_fim')
        
        if not (terapeuta and data and hora_inicio):
            return cleaned_data
        
        if not hora_fim:
            dt_inicio_naive = datetime.combine(data, hora_inicio)
            dt_inicio_aware = timezone.make_aware(dt_inicio_naive, timezone.get_current_timezone())
            dt_fim = dt_inicio_aware + timedelta(minutes=45)
            hora_fim = dt_fim.time()
            cleaned_data['hora_fim'] = hora_fim 
        
        dia_semana = data.weekday()
        bloqueado = BloqueioFixo.objects.filter(
            terapeuta=terapeuta,
            dia_semana=dia_semana,
            hora_inicio__lt=hora_fim,
            hora_fim__gt=hora_inicio
        ).exists()

        if bloqueado:
            raise forms.ValidationError(f"Bloqueado! Dr(a) {terapeuta.nome} possui um bloqueio fixo neste horário.")

        tem_conflito = Agendamento.verificar_conflito(
            terapeuta=terapeuta, data=data, hora_inicio=hora_inicio, hora_fim=hora_fim,
            ignorar_id=self.instance.pk if self.instance.pk else None
        )
        
        if tem_conflito:
            raise forms.ValidationError(f"Conflito! Dr(a) {terapeuta.nome} já possui atendimento neste horário.")
            
        return cleaned_data

class ConsultaForm(forms.ModelForm):
    class Meta:
        model = Consulta
        fields = ['evolucao']
        widgets = {
            'evolucao': forms.Textarea(attrs={'class': 'form-control', 'rows': 10}),
        }

class RegistrarFaltaForm(forms.ModelForm):
    class Meta:
        model = Agendamento
        fields = ['tipo_cancelamento', 'motivo_cancelamento']
        widgets = {
            'tipo_cancelamento': forms.Select(attrs={'class': 'form-select'}),
            'motivo_cancelamento': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Motivo da falta...'}),
        }
    def clean_tipo_cancelamento(self):
        tipo = self.cleaned_data.get('tipo_cancelamento')
        if not tipo: raise forms.ValidationError("Informe o tipo da falta.")
        return tipo

class AgendaFixaForm(forms.ModelForm):
    hora_inicio = forms.TimeField(
        label="Horário de Início",
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'})
    )

    class Meta:
        model = AgendaFixa
        fields = ['paciente', 'terapeuta', 'modalidade', 'sala', 'dia_semana', 'hora_inicio', 'hora_fim', 'data_inicio', 'data_fim', 'ativo']
        widgets = {
            'paciente': forms.Select(attrs={'class': 'form-control campo-busca'}),
            'terapeuta': forms.Select(attrs={'class': 'form-control campo-busca'}),
            'modalidade': forms.Select(attrs={'class': 'form-select'}),
            'sala': forms.Select(attrs={'class': 'form-select'}),
            'dia_semana': forms.Select(attrs={'class': 'form-select'}),
            'hora_fim': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'data_inicio': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control seletor-apenas-data', 'type': 'date'}),
            'data_fim': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control seletor-apenas-data', 'type': 'date'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sala'].required = True
        self.fields['sala'].label = "Sala de Atendimento"
        self.fields['hora_fim'].required = False 
        self.fields['modalidade'].empty_label = "Padrão do Terapeuta"
        self.fields['paciente'].queryset = Paciente.objects.filter(ativo=True).order_by('nome')

    def clean(self):
        cleaned_data = super().clean()
        terapeuta = cleaned_data.get('terapeuta')
        dia_semana = cleaned_data.get('dia_semana')
        hora_inicio = cleaned_data.get('hora_inicio')
        hora_fim = cleaned_data.get('hora_fim')
        
        if hora_inicio and not hora_fim:
            dummy_date = datetime.now().date()
            dt_inicio_naive = datetime.combine(dummy_date, hora_inicio)
            dt_inicio_aware = timezone.make_aware(dt_inicio_naive, timezone.get_current_timezone())
            dt_fim = dt_inicio_aware + timedelta(minutes=45)
            cleaned_data['hora_fim'] = dt_fim.time()
            hora_fim = cleaned_data['hora_fim']
            
        if terapeuta and dia_semana is not None and hora_inicio and hora_fim:
            bloqueado = BloqueioFixo.objects.filter(
                terapeuta=terapeuta,
                dia_semana=int(dia_semana),
                hora_inicio__lt=hora_fim,
                hora_fim__gt=hora_inicio
            ).exists()
            
            if bloqueado:
                raise forms.ValidationError("Este horário coincide com um BLOQUEIO FIXO deste terapeuta.")
            
        return cleaned_data

class BloqueioFixoForm(forms.ModelForm):
    class Meta:
        model = BloqueioFixo
        fields = ['terapeuta', 'dia_semana', 'hora_inicio', 'hora_fim']
        widgets = {
            'terapeuta': forms.Select(attrs={'class': 'form-select'}),
            'dia_semana': forms.Select(attrs={'class': 'form-select'}),
            'hora_inicio': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'hora_fim': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['hora_inicio'].required = False
        self.fields['hora_fim'].required = False

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('hora_inicio')
        end = cleaned_data.get('hora_fim')

        HORA_ABERTURA = time(7, 15)  
        HORA_FECHAMENTO = time(19, 30) 

        if not start and not end:
            cleaned_data['hora_inicio'] = HORA_ABERTURA
            cleaned_data['hora_fim'] = HORA_FECHAMENTO
        elif not start and end:
            cleaned_data['hora_inicio'] = HORA_ABERTURA
        elif start and not end:
            cleaned_data['hora_fim'] = HORA_FECHAMENTO

        final_start = cleaned_data.get('hora_inicio')
        final_end = cleaned_data.get('hora_fim')

        if final_start and final_end and final_start >= final_end:
            raise forms.ValidationError("O horário de início deve ser anterior ao horário de fim.")

        return cleaned_data