from django.db import models
from django.core.validators import RegexValidator
from datetime import datetime

# --- 1. PACIENTE ---
class Paciente(models.Model):
    nome = models.CharField(max_length=100)
    cpf = models.CharField(
        max_length=11, 
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^\d{11}$', 
                message='O CPF deve ter exatamente 11 dígitos (apenas números).'
            )
        ]
    )
    data_nascimento = models.DateField()
    telefone = models.CharField(
        max_length=11, 
        blank=True, 
        null=True,
        validators=[
            RegexValidator(
                regex=r'^\d{10,11}$', 
                message='O telefone deve ter 10 ou 11 dígitos (DDD + Número, sem traços).'
            )
        ]
    )
    
    def __str__(self):
        return self.nome

# --- 2. TERAPEUTA ---
class Terapeuta(models.Model):
    usuario = models.OneToOneField('auth.User', on_delete=models.CASCADE, null=True, blank=True, verbose_name="Usuário de Login")
    nome = models.CharField(max_length=100)
    registro_profissional = models.CharField(max_length=50, blank=True, null=True, verbose_name="CRP/CRM")
    especialidade = models.CharField(max_length=50, blank=True, null=True)
    
    def __str__(self):
        return self.nome

# --- 3. AGENDAMENTO ---
class Agendamento(models.Model):
    STATUS_CHOICES = [
        ('AGUARDANDO', 'Aguardando'),
        ('CONFIRMADO', 'Confirmado'),
        ('REALIZADO', 'Realizado'),
        ('CANCELADO', 'Cancelado'),
        ('FALTA', 'Falta'),
    ]

    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE)
    terapeuta = models.ForeignKey(Terapeuta, on_delete=models.PROTECT, verbose_name="Terapeuta Responsável")
    
    # NOVOS CAMPOS SEPARADOS
    data = models.DateField(verbose_name="Data da Consulta")
    hora_inicio = models.TimeField(verbose_name="Horário de Início")
    hora_fim = models.TimeField(verbose_name="Horário de Término", blank=True, null=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AGUARDANDO')
    
    class Meta:
        ordering = ['data', 'hora_inicio'] 

    def __str__(self):
        fim_str = self.hora_fim.strftime('%H:%M') if self.hora_fim else '??:??'
        return f"{self.data.strftime('%d/%m')} - {self.hora_inicio} às {fim_str} | {self.paciente}"
    
    # Helper para facilitar o uso onde o código espera um datetime completo
    @property
    def data_hora_inicio(self):
        return datetime.combine(self.data, self.hora_inicio)

# --- 4. CONSULTA ---
class Consulta(models.Model):
    agendamento = models.OneToOneField(Agendamento, on_delete=models.CASCADE, primary_key=True)
    evolucao = models.TextField(verbose_name="Evolução do Paciente")
    data_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Consulta de {self.agendamento.paciente}"