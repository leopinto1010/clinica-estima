from django.db import models
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta
from django.utils import timezone

# --- VALIDATOR DE TAMANHO (AJUSTADO PARA 10MB) ---
def validar_tamanho_arquivo(file):
    limite_mb = 10  # Limite reduzido para vídeos curtos
    if file.size > limite_mb * 1024 * 1024:
        raise ValidationError(f"O arquivo não pode exceder {limite_mb}MB.")

# ... (Mantenha as listas de choices e os modelos abaixo sem alterações) ...

ESPECIALIDADES_CHOICES = [
    ('Fonoaudiólogo(a)', 'Fonoaudiólogo(a)'),
    ('Fisioterapeuta', 'Fisioterapeuta'),
    ('Terapeuta Ocupacional', 'Terapeuta Ocupacional'),
    ('Psicólogo(a)', 'Psicólogo(a)'),
    ('Psicomotricista', 'Psicomotricista'),
    ('Nutricionista', 'Nutricionista'),
    ('Psicopedagogo(a)', 'Psicopedagogo(a)'),
    ('Musicoterapeuta', 'Musicoterapeuta'),
    ('Arteterapeuta', 'Arteterapeuta'),
    ('Terapeuta Alimentar', 'Terapeuta Alimentar'),
]

TIPO_ATENDIMENTO_CHOICES = [
    ('PARTICULAR', 'Particular'),
    ('DESCONTO', 'Particular com Desconto'),
    ('CONVENIO', 'Convênio'),
    ('SOCIAL', 'Social'),
]

class Paciente(models.Model):
    nome = models.CharField(max_length=100)
    cpf = models.CharField(
        max_length=11, unique=True, null=True, blank=True,
        validators=[RegexValidator(regex=r'^\d{11}$', message='CPF deve ter 11 dígitos.')]
    )
    data_nascimento = models.DateField(null=True, blank=True)
    telefone = models.CharField(
        max_length=11, blank=True, null=True,
        validators=[RegexValidator(regex=r'^\d{10,11}$', message='Telefone inválido.')]
    )
    tipo_padrao = models.CharField(
        max_length=20, choices=TIPO_ATENDIMENTO_CHOICES, default='PARTICULAR',
        verbose_name="Tipo de Atendimento Padrão"
    )
    ativo = models.BooleanField(default=True, verbose_name="Cadastro Ativo")
    
    class Meta:
        ordering = ['nome']
        verbose_name = 'Paciente'
        verbose_name_plural = 'Pacientes'
    
    def __str__(self):
        return self.nome

class Terapeuta(models.Model):
    usuario = models.OneToOneField('auth.User', on_delete=models.CASCADE, null=True, blank=True)
    nome = models.CharField(max_length=100)
    registro_profissional = models.CharField(max_length=50, blank=True, null=True)
    especialidade = models.CharField(max_length=50, choices=ESPECIALIDADES_CHOICES, blank=True, null=True)
    
    def __str__(self):
        return self.nome

class AgendamentoManager(models.Manager):
    def ativos(self):
        return self.filter(deletado=False)

class Agendamento(models.Model):
    STATUS_CHOICES = [
        ('AGUARDANDO', 'Aguardando'),
        ('REALIZADO', 'Realizado'),
        ('FALTA', 'Falta'),
    ]
    TIPO_CANCELAMENTO_CHOICES = [
        ('JUSTIFICADA', 'Falta Justificada'),
        ('NAO_JUSTIFICADA', 'Falta Não Justificada'),
        ('NAO_LIBERACAO', 'Não Liberação (Convênio)'),
        ('TERAPEUTA', 'Falta do Terapeuta'),
    ]

    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE)
    terapeuta = models.ForeignKey(Terapeuta, on_delete=models.PROTECT)
    data = models.DateField(verbose_name="Data da Consulta")
    hora_inicio = models.TimeField(verbose_name="Horário de Início")
    hora_fim = models.TimeField(verbose_name="Horário de Término", blank=True, null=True)
    tipo_atendimento = models.CharField(max_length=20, choices=TIPO_ATENDIMENTO_CHOICES, default='PARTICULAR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AGUARDANDO')
    deletado = models.BooleanField(default=False)
    
    tipo_cancelamento = models.CharField(max_length=20, choices=TIPO_CANCELAMENTO_CHOICES, null=True, blank=True, verbose_name="Tipo de Falta")
    motivo_cancelamento = models.TextField(null=True, blank=True, verbose_name="Observação da Falta")
    
    objects = AgendamentoManager()

    class Meta:
        ordering = ['data', 'hora_inicio'] 

    def save(self, *args, **kwargs):
        if not self.hora_fim and self.hora_inicio:
            dummy_date = datetime.now().date()
            dt_inicio = datetime.combine(dummy_date, self.hora_inicio)
            self.hora_fim = (dt_inicio + timedelta(hours=1)).time()
        super().save(*args, **kwargs)

    @classmethod
    def verificar_conflito(cls, terapeuta, data, hora_inicio, hora_fim, ignorar_id=None):
        conflitos = cls.objects.ativos().filter(terapeuta=terapeuta, data=data).exclude(status='FALTA')
        conflitos = conflitos.filter(hora_inicio__lt=hora_fim, hora_fim__gt=hora_inicio)
        if ignorar_id: conflitos = conflitos.exclude(id=ignorar_id)
        return conflitos.exists()

class Consulta(models.Model):
    agendamento = models.OneToOneField(Agendamento, on_delete=models.CASCADE, primary_key=True)
    evolucao = models.TextField(verbose_name="Evolução do Paciente")
    data_registro = models.DateTimeField(auto_now_add=True)

class AnexoConsulta(models.Model):
    consulta = models.ForeignKey(Consulta, on_delete=models.CASCADE, related_name='anexos')
    arquivo = models.FileField(
        upload_to='prontuarios/%Y/%m/', 
        verbose_name="Arquivo",
        validators=[validar_tamanho_arquivo] # Usa o validador de 10MB
    )
    data_upload = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Anexo {self.id} - {self.consulta.agendamento.paciente.nome}"
        
    @property
    def eh_imagem(self):
        nome = self.arquivo.name.lower()
        return nome.endswith('.jpg') or nome.endswith('.jpeg') or nome.endswith('.png') or nome.endswith('.webp')