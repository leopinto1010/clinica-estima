from django.db import models
from django.core.validators import RegexValidator
from datetime import datetime

# --- LISTA DE OPÇÕES ---
TIPO_ATENDIMENTO_CHOICES = [
    ('PARTICULAR', 'Particular'),
    ('DESCONTO', 'Particular com Desconto'),
    ('CONVENIO', 'Convênio'),
    ('SOCIAL', 'Social'),
]

# --- 1. PACIENTE ---
class Paciente(models.Model):
    nome = models.CharField(max_length=100)
    cpf = models.CharField(
        max_length=11, 
        unique=True,
        validators=[
            RegexValidator(regex=r'^\d{11}$', message='CPF deve ter 11 dígitos.')
        ]
    )
    data_nascimento = models.DateField()
    telefone = models.CharField(
        max_length=11, blank=True, null=True,
        validators=[RegexValidator(regex=r'^\d{10,11}$', message='Telefone inválido.')]
    )
    
    tipo_padrao = models.CharField(
        max_length=20, 
        choices=TIPO_ATENDIMENTO_CHOICES, 
        default='PARTICULAR',
        verbose_name="Tipo de Atendimento Padrão"
    )
    
    def __str__(self):
        return self.nome

# --- 2. TERAPEUTA ---
class Terapeuta(models.Model):
    usuario = models.OneToOneField('auth.User', on_delete=models.CASCADE, null=True, blank=True)
    nome = models.CharField(max_length=100)
    registro_profissional = models.CharField(max_length=50, blank=True, null=True)
    especialidade = models.CharField(max_length=50, blank=True, null=True)
    
    def __str__(self):
        return self.nome

# --- 3. AGENDAMENTO ---
class Agendamento(models.Model):
    # [CORREÇÃO] Removido 'CONFIRMADO' desta lista. Isso remove do filtro automaticamente.
    STATUS_CHOICES = [
        ('AGUARDANDO', 'Aguardando'),
        ('REALIZADO', 'Realizado'),
        ('CANCELADO', 'Cancelado'),
        ('FALTA', 'Falta'),
    ]

    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE)
    terapeuta = models.ForeignKey(Terapeuta, on_delete=models.PROTECT)
    
    data = models.DateField(verbose_name="Data da Consulta")
    hora_inicio = models.TimeField(verbose_name="Horário de Início")
    hora_fim = models.TimeField(verbose_name="Horário de Término", blank=True, null=True)
    
    tipo_atendimento = models.CharField(
        max_length=20, 
        choices=TIPO_ATENDIMENTO_CHOICES, 
        default='PARTICULAR',
        verbose_name="Tipo (Nesta consulta)"
    )
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AGUARDANDO')
    
    # SOFT DELETE
    deletado = models.BooleanField(default=False, verbose_name="Excluído da Agenda")
    
    class Meta:
        ordering = ['data', 'hora_inicio'] 

    def __str__(self):
        return f"{self.data} - {self.paciente}"
    
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