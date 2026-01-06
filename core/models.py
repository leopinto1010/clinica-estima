from django.db import models
from django.core.validators import RegexValidator
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Q

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
    
    class Meta:
        ordering = ['nome']
        verbose_name = 'Paciente'
        verbose_name_plural = 'Pacientes'
    
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

# --- MANAGER PERSONALIZADO ---
class AgendamentoManager(models.Manager):
    def ativos(self):
        """Retorna apenas agendamentos que NÃO foram deletados."""
        return self.filter(deletado=False)

    def do_paciente(self, paciente_id):
        return self.ativos().filter(paciente_id=paciente_id)
    
    def do_terapeuta(self, terapeuta_user):
        """Filtra para o terapeuta logado, se ele for terapeuta."""
        if hasattr(terapeuta_user, 'terapeuta'):
            return self.ativos().filter(terapeuta=terapeuta_user.terapeuta)
        return self.none()

# --- 3. AGENDAMENTO ---
class Agendamento(models.Model):
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
    deletado = models.BooleanField(default=False, verbose_name="Excluído da Agenda")
    
    # Conecta o Manager
    objects = AgendamentoManager()

    class Meta:
        ordering = ['data', 'hora_inicio'] 

    def __str__(self):
        return f"{self.data} - {self.paciente}"
    
    @property
    def data_hora_inicio(self):
        return datetime.combine(self.data, self.hora_inicio)

    def save(self, *args, **kwargs):
        # Garante o cálculo da hora fim se não vier preenchido
        if not self.hora_fim and self.hora_inicio:
            # Lógica simples: +1 hora por padrão
            dummy_date = datetime.now().date()
            dt_inicio = datetime.combine(dummy_date, self.hora_inicio)
            self.hora_fim = (dt_inicio + timedelta(hours=1)).time()
        super().save(*args, **kwargs)

    @classmethod
    def verificar_conflito(cls, terapeuta, data, hora_inicio, hora_fim, ignorar_id=None):
        """
        Retorna True se houver conflito, False se estiver livre.
        Ignora agendamentos cancelados, faltas ou deletados.
        """
        conflitos = cls.objects.ativos().filter(
            terapeuta=terapeuta,
            data=data
        ).exclude(
            status__in=['CANCELADO', 'FALTA']
        )

        # Lógica de sobreposição de horários
        # (StartA < EndB) and (EndA > StartB)
        conflitos = conflitos.filter(
            hora_inicio__lt=hora_fim,
            hora_fim__gt=hora_inicio
        )

        if ignorar_id:
            conflitos = conflitos.exclude(id=ignorar_id)
            
        return conflitos.exists()

# --- 4. CONSULTA ---
class Consulta(models.Model):
    agendamento = models.OneToOneField(Agendamento, on_delete=models.CASCADE, primary_key=True)
    evolucao = models.TextField(verbose_name="Evolução do Paciente")
    data_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Consulta de {self.agendamento.paciente}"