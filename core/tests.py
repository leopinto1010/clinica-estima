from django.test import TestCase
from django.utils import timezone
from datetime import timedelta, time
from .models import Paciente, Terapeuta, Agendamento
from django.contrib.auth.models import User, Group
from django.urls import reverse
from .views import formatar_nome_terapeuta

class AgendamentoModelTest(TestCase):
    def setUp(self):
        # Criação de dados básicos para os testes
        self.user = User.objects.create_user(username='terapeuta', password='123')
        self.terapeuta = Terapeuta.objects.create(nome='Dr. Teste', usuario=self.user)
        self.paciente = Paciente.objects.create(
            nome='Paciente Teste', 
            cpf='11122233344', 
            data_nascimento='1990-01-01'
        )
        self.hoje = timezone.now().date()

    def test_criacao_agendamento(self):
        """Testa se um agendamento simples é criado corretamente"""
        agendamento = Agendamento.objects.create(
            paciente=self.paciente,
            terapeuta=self.terapeuta,
            data=self.hoje,
            hora_inicio=time(14, 0) # 14:00
        )
        self.assertEqual(agendamento.hora_fim, time(15, 0)) # Deve calcular automático +1h
        self.assertFalse(agendamento.deletado)

    def test_soft_delete_manager(self):
        """Testa se o manager .ativos() esconde os deletados"""
        a1 = Agendamento.objects.create(
            paciente=self.paciente, terapeuta=self.terapeuta, 
            data=self.hoje, hora_inicio=time(8, 0)
        )
        a2 = Agendamento.objects.create(
            paciente=self.paciente, terapeuta=self.terapeuta, 
            data=self.hoje, hora_inicio=time(9, 0),
            deletado=True # Marcado como excluído
        )

        ativos = Agendamento.objects.ativos()
        self.assertIn(a1, ativos)
        self.assertNotIn(a2, ativos)

    def test_conflito_horario(self):
        """Testa a lógica de conflito de horários"""
        # Cria agendamento das 10:00 às 11:00
        Agendamento.objects.create(
            paciente=self.paciente, terapeuta=self.terapeuta,
            data=self.hoje, hora_inicio=time(10, 0), hora_fim=time(11, 0)
        )

        # Tenta agendar 10:30 (dentro do horário)
        tem_conflito = Agendamento.verificar_conflito(
            self.terapeuta, self.hoje, time(10, 30), time(11, 30)
        )
        self.assertTrue(tem_conflito)

    def test_lista_agendamentos_filtra_terapeuta_para_admin(self):
        """O filtro por terapeuta da agenda operacional deve aplicar para administradores."""
        grupo_admin = Group.objects.get_or_create(name='Administrativo')[0]
        admin = User.objects.create_user(username='admin_agenda', password='123')
        admin.groups.add(grupo_admin)

        outro_terapeuta = Terapeuta.objects.create(
            nome='Dr. Segundo',
            usuario=User.objects.create_user(username='segundo_terapeuta', password='123')
        )
        outro_paciente = Paciente.objects.create(
            nome='Paciente Dois',
            cpf='22233344455',
            data_nascimento='1993-02-02'
        )

        agendamento_1 = Agendamento.objects.create(
            paciente=self.paciente,
            terapeuta=self.terapeuta,
            data=self.hoje,
            hora_inicio=time(8, 0),
        )
        agendamento_2 = Agendamento.objects.create(
            paciente=outro_paciente,
            terapeuta=outro_terapeuta,
            data=self.hoje,
            hora_inicio=time(9, 0),
        )

        self.client.force_login(admin)
        response = self.client.get(reverse('lista_agendamentos'), {
            'data_inicio': self.hoje.isoformat(),
            'data_fim': self.hoje.isoformat(),
            'filtro_terapeuta': str(outro_terapeuta.id),
        })

        self.assertEqual(response.status_code, 200)
        agenda_map = response.context['agenda_map']
        agendamentos_visiveis = []
        for slot in agenda_map.values():
            for dia_map in slot.values():
                for item in dia_map:
                    if getattr(item, 'tipo_obj', None) == 'agendamento':
                        agendamentos_visiveis.append(item)

        self.assertIn(agendamento_2.id, [item.id for item in agendamentos_visiveis])
        self.assertNotIn(agendamento_1.id, [item.id for item in agendamentos_visiveis])

    def test_coordenador_terapeuta_pode_evoluir_paciente_do_seu_atendimento(self):
        """Coordenadores que também são terapeutas devem conseguir evoluir os pacientes de seu próprio atendimento."""
        grupo_coordenacao = Group.objects.get_or_create(name='Coordenação')[0]
        coordenadora = User.objects.create_user(username='coord_terapeuta', password='123')
        coordenadora.groups.add(grupo_coordenacao)

        terapeuta = Terapeuta.objects.create(
            nome='Dr. Coordenadora',
            usuario=coordenadora,
            coordenacao=True,
        )

        agendamento = Agendamento.objects.create(
            paciente=self.paciente,
            terapeuta=terapeuta,
            data=self.hoje,
            hora_inicio=time(10, 0),
        )

        self.client.force_login(coordenadora)
        response = self.client.get(reverse('realizar_consulta', args=[agendamento.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['agendamento'].id, agendamento.id)

    def test_formatar_nome_terapeuta_com_nome_completo(self):
        """Deve preservar o primeiro e o sobrenome quando houver nome completo."""
        self.assertEqual(formatar_nome_terapeuta('Maria Silva'), 'Maria Silva')
        self.assertEqual(formatar_nome_terapeuta('Ana Maria Souza'), 'Ana Maria')
        self.assertEqual(formatar_nome_terapeuta('Dr. João Pereira'), 'Dr. João')
        # Tenta agendar 11:00 (logo após, deve estar livre)
        tem_conflito = Agendamento.verificar_conflito(
            self.terapeuta, self.hoje, time(11, 0), time(12, 0)
        )
        self.assertFalse(tem_conflito)