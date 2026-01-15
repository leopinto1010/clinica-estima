from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Paciente, Terapeuta, Agendamento, Consulta, ESPECIALIDADES_CHOICES
from datetime import datetime, timedelta
from django.utils import timezone

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
        fields = ['nome', 'cpf', 'data_nascimento', 'telefone', 'tipo_padrao', 'ativo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome Completo'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apenas números'}),
            'data_nascimento': forms.DateInput(attrs={'class': 'form-control seletor-apenas-data'}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo_padrao': forms.Select(attrs={'class': 'form-control'}),
        }

class AgendamentoForm(forms.ModelForm):
    repeticoes = forms.IntegerField(
        required=False, initial=0, min_value=0, max_value=48, 
        label="Repetir por quantas semanas?",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0 = Apenas hoje'})
    )
    class Meta:
        model = Agendamento
        fields = ['paciente', 'terapeuta', 'data', 'hora_inicio', 'hora_fim']
        widgets = {
            'paciente': forms.Select(attrs={'class': 'form-control campo-busca'}),
            'terapeuta': forms.Select(attrs={'class': 'form-control campo-busca'}),
            'data': forms.DateInput(attrs={'class': 'form-control seletor-apenas-data'}),
            'hora_inicio': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'hora_fim': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        }
    def clean(self):
        cleaned_data = super().clean()
        terapeuta = cleaned_data.get('terapeuta')
        data = cleaned_data.get('data')
        hora_inicio = cleaned_data.get('hora_inicio')
        hora_fim = cleaned_data.get('hora_fim')
        if not (terapeuta and data and hora_inicio): return cleaned_data
        if not hora_fim:
            dt_inicio_naive = datetime.combine(data, hora_inicio)
            dt_inicio_aware = timezone.make_aware(dt_inicio_naive, timezone.get_current_timezone())
            dt_fim = dt_inicio_aware + timedelta(hours=1)
            hora_fim = dt_fim.time()
            cleaned_data['hora_fim'] = hora_fim 
        
        tem_conflito = Agendamento.verificar_conflito(
            terapeuta=terapeuta, data=data, hora_inicio=hora_inicio, hora_fim=hora_fim,
            ignorar_id=self.instance.pk if self.instance.pk else None
        )
        if tem_conflito:
            raise forms.ValidationError(f"Conflito! Dr(a) {terapeuta.nome} já possui atendimento válido neste horário.")
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