from django.test import TestCase
from django.utils import timezone
from datetime import timedelta, time
from .models import Paciente, Terapeuta, Agendamento
from django.contrib.auth.models import User

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

        # Tenta agendar 11:00 (logo após, deve estar livre)
        tem_conflito = Agendamento.verificar_conflito(
            self.terapeuta, self.hoje, time(11, 0), time(12, 0)
        )
        self.assertFalse(tem_conflito)