from django.db import models
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from datetime import datetime, timedelta
from django.utils import timezone
import unicodedata

def remover_acentos(texto):
    if not texto: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def validar_tamanho_arquivo(file):
    limite_mb = 10
    if file.size > limite_mb * 1024 * 1024:
        raise ValidationError(f"O arquivo não pode exceder {limite_mb}MB.")

# --- LISTA REDUZIDA (Apenas as variações) ---
MODALIDADE_CHOICES = [
    ('BOBATH', 'Fisioterapia (Bobath)'),
    ('PEDIA', 'Fisioterapia (Pedia)'),
    ('AT', 'Assistente Terapêutico (AT)'),
]

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
    ('Assistente Terapêutico', 'Assistente Terapêutico'),
]

TIPO_ATENDIMENTO_CHOICES = [
    ('PARTICULAR', 'Particular'),
    ('DESCONTO', 'Particular com Desconto'),
    ('CONVENIO', 'Convênio'),
    ('SOCIAL', 'Social'),
]

# ... (Classes Sala, Convenio, Paciente e Terapeuta permanecem iguais) ...
class Sala(models.Model):
    nome = models.CharField(max_length=50, verbose_name="Nome da Sala")
    def __str__(self): return self.nome

class Convenio(models.Model):
    nome = models.CharField(max_length=100, unique=True, verbose_name="Nome do Convênio")
    ativo = models.BooleanField(default=True)
    class Meta:
        ordering = ['nome']
        verbose_name = "Convênio"
        verbose_name_plural = "Convênios"
    def __str__(self): return self.nome
    
class Paciente(models.Model):
    nome = models.CharField(max_length=100)
    nome_search = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    cpf = models.CharField(max_length=11, unique=True, null=True, blank=True, validators=[RegexValidator(regex=r'^\d{11}$')])
    data_nascimento = models.DateField(null=True, blank=True)
    telefone = models.CharField(max_length=11, blank=True, null=True, validators=[RegexValidator(regex=r'^\d{10,11}$')])
    tipo_padrao = models.CharField(max_length=20, choices=TIPO_ATENDIMENTO_CHOICES, default='PARTICULAR')
    convenio = models.ForeignKey(Convenio, on_delete=models.SET_NULL, null=True, blank=True)
    carteirinha = models.CharField(max_length=50, blank=True, null=True)
    ativo = models.BooleanField(default=True)
    class Meta:
        ordering = ['nome']
        verbose_name = 'Paciente'
    def __str__(self): return self.nome
    def save(self, *args, **kwargs):
        self.nome_search = remover_acentos(self.nome).lower()
        super().save(*args, **kwargs)

class Terapeuta(models.Model):
    usuario = models.OneToOneField('auth.User', on_delete=models.CASCADE, null=True, blank=True)
    nome = models.CharField(max_length=100)
    registro_profissional = models.CharField(max_length=50, blank=True, null=True)
    especialidade = models.CharField(max_length=50, choices=ESPECIALIDADES_CHOICES, blank=True, null=True)
    class Meta: ordering = ['nome']
    def __str__(self): return self.nome

class AgendaFixa(models.Model):
    DIAS_DA_SEMANA = [
        (0, 'Segunda-feira'), (1, 'Terça-feira'), (2, 'Quarta-feira'),
        (3, 'Quinta-feira'), (4, 'Sexta-feira'), (5, 'Sábado'), (6, 'Domingo'),
    ]

    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE)
    terapeuta = models.ForeignKey(Terapeuta, on_delete=models.PROTECT)
    
    # --- ALTERADO: Opcional e com choices restritos ---
    modalidade = models.CharField(
        max_length=50, 
        choices=MODALIDADE_CHOICES, 
        blank=True,  # Permite vazio no form
        null=True,   # Permite NULL no banco
        default=None,
        verbose_name="Modalidade (Vazio = Padrão)"
    )
    # --------------------------------------------------

    sala = models.ForeignKey(Sala, on_delete=models.PROTECT, null=True, blank=True)
    dia_semana = models.IntegerField(choices=DIAS_DA_SEMANA)
    hora_inicio = models.TimeField()
    hora_fim = models.TimeField()
    ativo = models.BooleanField(default=True)
    data_inicio = models.DateField(default=timezone.now)
    data_fim = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "Horário Fixo (Grade)"
        verbose_name_plural = "Agenda Fixa (Grade)"

    def __str__(self):
        return f"{self.get_dia_semana_display()} - {self.paciente.nome}"

    def save(self, *args, **kwargs):
        if not self.hora_fim and self.hora_inicio:
            dummy_date = datetime.now().date()
            dt_inicio = datetime.combine(dummy_date, self.hora_inicio)
            self.hora_fim = (dt_inicio + timedelta(minutes=45)).time()
        super().save(*args, **kwargs)

    # --- PROPRIEDADE INTELIGENTE DE EXIBIÇÃO ---
    @property
    def descricao_modalidade(self):
        if self.modalidade:
            return self.get_modalidade_display()
        return self.terapeuta.especialidade or "Padrão"

class AgendamentoManager(models.Manager):
    def ativos(self): return self.filter(deletado=False)

class Agendamento(models.Model):
    STATUS_CHOICES = [
        ('AGUARDANDO', 'Aguardando'), ('REALIZADO', 'Realizado'), ('FALTA', 'Falta'),
    ]
    TIPO_CANCELAMENTO_CHOICES = [
        ('JUSTIFICADA', 'Falta Justificada'), ('NAO_JUSTIFICADA', 'Falta Não Justificada'),
        ('NAO_LIBERACAO', 'Não Liberação (Convênio)'), ('TERAPEUTA', 'Falta do Terapeuta'),
    ]

    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE)
    terapeuta = models.ForeignKey(Terapeuta, on_delete=models.PROTECT)
    
    # --- ALTERADO: Opcional e com choices restritos ---
    modalidade = models.CharField(
        max_length=50, 
        choices=MODALIDADE_CHOICES, 
        blank=True, 
        null=True, 
        default=None,
        verbose_name="Modalidade (Consulta)"
    )
    # --------------------------------------------------

    agenda_fixa = models.ForeignKey(AgendaFixa, on_delete=models.SET_NULL, null=True, blank=True, related_name='agendamentos_gerados')
    sala = models.ForeignKey(Sala, on_delete=models.SET_NULL, null=True, blank=True)
    data = models.DateField()
    hora_inicio = models.TimeField()
    hora_fim = models.TimeField(blank=True, null=True)
    tipo_atendimento = models.CharField(max_length=20, choices=TIPO_ATENDIMENTO_CHOICES, default='PARTICULAR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AGUARDANDO')
    deletado = models.BooleanField(default=False)
    tipo_cancelamento = models.CharField(max_length=20, choices=TIPO_CANCELAMENTO_CHOICES, null=True, blank=True)
    motivo_cancelamento = models.TextField(null=True, blank=True)
    
    objects = AgendamentoManager()

    class Meta: ordering = ['data', 'hora_inicio'] 

    def save(self, *args, **kwargs):
        if not self.hora_fim and self.hora_inicio:
            dummy_date = datetime.now().date()
            dt_inicio = datetime.combine(dummy_date, self.hora_inicio)
            self.hora_fim = (dt_inicio + timedelta(minutes=45)).time()
        super().save(*args, **kwargs)
        
    @classmethod
    def verificar_conflito(cls, terapeuta, data, hora_inicio, hora_fim, ignorar_id=None):
        conflitos = cls.objects.ativos().filter(terapeuta=terapeuta, data=data).exclude(status='FALTA')
        conflitos = conflitos.filter(hora_inicio__lt=hora_fim, hora_fim__gt=hora_inicio)
        if ignorar_id: conflitos = conflitos.exclude(id=ignorar_id)
        return conflitos.exists()

    # --- PROPRIEDADE INTELIGENTE DE EXIBIÇÃO ---
    @property
    def descricao_modalidade(self):
        if self.modalidade:
            return self.get_modalidade_display()
        return self.terapeuta.especialidade or "Padrão"

# ... (Consulta e AnexoConsulta permanecem iguais) ...
class Consulta(models.Model):
    agendamento = models.OneToOneField(Agendamento, on_delete=models.CASCADE, primary_key=True)
    evolucao = models.TextField()
    data_registro = models.DateTimeField(auto_now_add=True)

class AnexoConsulta(models.Model):
    consulta = models.ForeignKey(Consulta, on_delete=models.CASCADE, related_name='anexos')
    arquivo = models.FileField(upload_to='prontuarios/%Y/%m/', validators=[validar_tamanho_arquivo])
    data_upload = models.DateTimeField(auto_now_add=True)
    def __str__(self): return f"Anexo {self.id}"
    @property
    def eh_imagem(self):
        nome = self.arquivo.name.lower()
        return nome.endswith(('.jpg', '.jpeg', '.png', '.webp'))