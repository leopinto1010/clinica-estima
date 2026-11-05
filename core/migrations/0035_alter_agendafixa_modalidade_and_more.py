from django.db import migrations, models


MODALIDADE_CHOICES = [
    ('BOBATH', 'Fisioterapia (Bobath)'),
    ('PEDIASUIT', 'Fisioterapia (Pediasuit)'),
    ('RESPIRATORIA', 'Fisioterapia (Respiratória)'),
    ('AT', 'Assistente Terapêutico (AT)'),
    ('PSICOPEDAGOGIA', 'Psicopedagogia'),
    ('AVALIACAO_NEUROPSICOLOGICA', 'Avaliação neuropsicológica'),
    ('coordenacao', 'Coordenação'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0034_terapeuta_coordenacao_alter_terapeuta_especialidade'),
    ]

    operations = [
        migrations.AlterField(
            model_name='agendafixa',
            name='modalidade',
            field=models.CharField(
                blank=True,
                choices=MODALIDADE_CHOICES,
                default=None,
                max_length=50,
                null=True,
                verbose_name='Modalidade (Vazio = Padrão)',
            ),
        ),
        migrations.AlterField(
            model_name='agendamento',
            name='modalidade',
            field=models.CharField(
                blank=True,
                choices=MODALIDADE_CHOICES,
                default=None,
                max_length=50,
                null=True,
                verbose_name='Modalidade (Consulta)',
            ),
        ),
    ]
