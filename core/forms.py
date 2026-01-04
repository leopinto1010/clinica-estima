from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Paciente, Terapeuta, Agendamento, Consulta

# --- CADASTRO DE EQUIPE (ADMIN) ---
class CadastroEquipeForm(UserCreationForm):
    nome_completo = forms.CharField(max_length=100, label="Nome Completo")
    registro = forms.CharField(max_length=50, required=False, label="CRP/CRM")
    especialidade = forms.CharField(max_length=50, required=False)

    class Meta:
        model = User
        fields = ['username', 'nome_completo', 'registro', 'especialidade']

# --- FORMULÁRIO DE PACIENTE ---
class PacienteForm(forms.ModelForm):
    class Meta:
        model = Paciente
        fields = ['nome', 'cpf', 'data_nascimento', 'telefone']
        
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome Completo'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apenas números'}),
            'data_nascimento': forms.DateInput(attrs={
                'class': 'form-control seletor-apenas-data', 
                'placeholder': 'Selecione a data'
            }),
            'telefone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'DDD + Número'}),
        }

# --- FORMULÁRIO DE AGENDAMENTO ---
class AgendamentoForm(forms.ModelForm):
    repeticoes = forms.IntegerField(
        required=False, 
        initial=0, 
        min_value=0, 
        max_value=48, 
        label="Repetir por quantas semanas?",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0 = Apenas hoje'})
    )

    class Meta:
        model = Agendamento
        fields = ['paciente', 'terapeuta', 'data', 'hora_inicio', 'hora_fim']
        
        widgets = {
            'paciente': forms.Select(attrs={'class': 'form-control campo-busca'}),
            'terapeuta': forms.Select(attrs={'class': 'form-control campo-busca'}),
            
            # WIDGETS ATUALIZADOS PARA O NOVO MODELO
            'data': forms.DateInput(attrs={
                'class': 'form-control', 
                'type': 'date' 
            }),
            'hora_inicio': forms.TimeInput(attrs={
                'class': 'form-control', 
                'type': 'time'
            }),
            'hora_fim': forms.TimeInput(attrs={
                'class': 'form-control', 
                'type': 'time'
            }),
        }

# --- FORMULÁRIO DE CONSULTA ---
class ConsultaForm(forms.ModelForm):
    class Meta:
        model = Consulta
        fields = ['evolucao']
        
        widgets = {
            'evolucao': forms.Textarea(attrs={'class': 'form-control', 'rows': 10, 'placeholder': 'Descreva a evolução clínica...'}),
        }