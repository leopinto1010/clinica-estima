from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from datetime import timedelta, time
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from .models import (
    Paciente, Terapeuta, AgendaFixa, Agendamento, AnexoConsulta, Consulta, Sala,
    MODALIDADE_CHOICES,
)
from django.contrib.auth.models import User, Group
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from .views import formatar_nome_terapeuta
from .utils import sincronizar_agenda_fixa

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

    def test_grade_paciente_exibe_sexta_e_sabado_sem_adicionar_domingo(self):
        """A grade do paciente deve renderizar segunda a sábado e manter domingo fora."""
        grupo_admin = Group.objects.get_or_create(name='Administrativo')[0]
        self.user.groups.add(grupo_admin)
        self.client.force_login(self.user)

        for dia_semana in (4, 5, 6):
            AgendaFixa.objects.create(
                paciente=self.paciente,
                terapeuta=self.terapeuta,
                dia_semana=dia_semana,
                hora_inicio=time(8, 0),
                hora_fim=time(9, 0),
            )

        response = self.client.get(reverse('relatorio_grade_pacientes'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['dias_semana'], [
            'Segunda-feira', 'Terça-feira', 'Quarta-feira',
            'Quinta-feira', 'Sexta-feira', 'Sábado',
        ])

        linhas = response.context['relatorio'][0]['linhas']
        self.assertEqual(len(linhas), 1)
        self.assertEqual(len(linhas[0]['colunas']), 6)
        self.assertTrue(linhas[0]['colunas'][4])
        self.assertTrue(linhas[0]['colunas'][5])
        self.assertContains(response, 'Sábado')
        self.assertNotContains(response, 'Domingo')

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


class AgendaFixaSincronizacaoTest(TestCase):
    def setUp(self):
        self.hoje = timezone.localdate()
        self.admin = User.objects.create_user(username='admin_hotfix', password='123')
        self.admin.groups.add(Group.objects.get_or_create(name='Administrativo')[0])

        self.usuario_1 = User.objects.create_user(username='terapeuta_hotfix_1', password='123')
        self.usuario_1.groups.add(Group.objects.get_or_create(name='Terapeutas')[0])
        self.terapeuta_1 = Terapeuta.objects.create(nome='Juliana Teste', usuario=self.usuario_1)

        self.usuario_2 = User.objects.create_user(username='terapeuta_hotfix_2', password='123')
        self.usuario_2.groups.add(Group.objects.get_or_create(name='Terapeutas')[0])
        self.terapeuta_2 = Terapeuta.objects.create(nome='Outra Terapeuta', usuario=self.usuario_2)

        self.paciente = Paciente.objects.create(nome='Paciente Hotfix', cpf='33344455566')
        self.outro_paciente = Paciente.objects.create(nome='Paciente Controle', cpf='44455566677')
        self.sala_1 = Sala.objects.create(nome='Sala Hotfix 1')
        self.sala_2 = Sala.objects.create(nome='Sala Hotfix 2')

    def proxima_data(self, dia_semana, base=None):
        base = base or self.hoje
        return base + timedelta(days=(dia_semana - base.weekday()) % 7)

    def criar_agenda(self, dia_semana=None):
        dia_semana = self.hoje.weekday() if dia_semana is None else dia_semana
        return AgendaFixa.objects.create(
            paciente=self.paciente,
            terapeuta=self.terapeuta_1,
            sala=self.sala_1,
            dia_semana=dia_semana,
            hora_inicio=time(8, 0),
            hora_fim=time(9, 0),
            data_inicio=self.hoje - timedelta(days=30),
        )

    def test_edicao_sincroniza_confirmado_sala_terapeuta_modalidade_e_preserva_passado(self):
        agenda = self.criar_agenda()
        data_futura = self.proxima_data(agenda.dia_semana)
        futuro = Agendamento.objects.create(
            agenda_fixa=agenda,
            paciente=self.paciente,
            terapeuta=self.terapeuta_1,
            sala=self.sala_1,
            data=data_futura,
            hora_inicio=time(8, 0),
            hora_fim=time(9, 0),
            status='CONFIRMADO',
        )
        data_passada = data_futura - timedelta(days=7)
        while data_passada >= self.hoje:
            data_passada -= timedelta(days=7)
        passado = Agendamento.objects.create(
            agenda_fixa=agenda,
            paciente=self.paciente,
            terapeuta=self.terapeuta_1,
            sala=self.sala_1,
            data=data_passada,
            hora_inicio=time(8, 0),
            hora_fim=time(9, 0),
            status='REALIZADO',
        )

        self.client.force_login(self.admin)
        response = self.client.post(reverse('editar_agenda_fixa', args=[agenda.id]), {
            'paciente': self.paciente.id,
            'terapeuta': self.terapeuta_2.id,
            'modalidade': 'AVALIACAO_NEUROPSICOLOGICA',
            'sala': self.sala_2.id,
            'dia_semana': agenda.dia_semana,
            'hora_inicio': '10:00',
            'hora_fim': '11:00',
            'data_inicio': agenda.data_inicio.isoformat(),
            'data_fim': '',
            'ativo': 'on',
        })

        self.assertEqual(response.status_code, 302)
        futuro.refresh_from_db()
        self.assertEqual(futuro.terapeuta, self.terapeuta_2)
        self.assertEqual(futuro.sala, self.sala_2)
        self.assertEqual(futuro.hora_inicio, time(10, 0))
        self.assertEqual(futuro.hora_fim, time(11, 0))
        self.assertEqual(futuro.modalidade, 'AVALIACAO_NEUROPSICOLOGICA')
        self.assertFalse(futuro.deletado)
        self.assertEqual(
            Agendamento.objects.ativos().filter(agenda_fixa=agenda, data=data_futura).count(),
            1,
        )

        passado.refresh_from_db()
        self.assertEqual(passado.terapeuta, self.terapeuta_1)
        self.assertEqual(passado.sala, self.sala_1)
        self.assertEqual(passado.hora_inicio, time(8, 0))

    def test_troca_para_sabado_remove_dia_antigo_sem_afetar_outro_profissional(self):
        dia_original = 4 if self.hoje.weekday() != 4 else 3
        agenda = self.criar_agenda(dia_original)
        data_original = self.proxima_data(dia_original)
        sincronizar_agenda_fixa(agenda, dias_a_frente=14)
        copia_original = Agendamento.objects.get(agenda_fixa=agenda, data=data_original)

        data_controle = self.proxima_data(5)
        controle = Agendamento.objects.create(
            paciente=self.outro_paciente,
            terapeuta=self.terapeuta_2,
            sala=self.sala_2,
            data=data_controle,
            hora_inicio=time(14, 0),
            hora_fim=time(15, 0),
        )

        agenda.dia_semana = 5
        agenda.save()
        sincronizar_agenda_fixa(agenda, dias_a_frente=14)

        copia_original.refresh_from_db()
        self.assertTrue(copia_original.deletado)
        sabados = Agendamento.objects.ativos().filter(
            agenda_fixa=agenda,
            data__gte=self.hoje,
        )
        self.assertTrue(sabados.exists())
        self.assertTrue(all(item.data.weekday() == 5 for item in sabados))
        controle.refresh_from_db()
        self.assertFalse(controle.deletado)
        self.assertEqual(controle.terapeuta, self.terapeuta_2)

    def test_vigencia_e_desativacao_removem_so_copias_futuras_mutaveis(self):
        agenda = self.criar_agenda()
        sincronizar_agenda_fixa(agenda, dias_a_frente=21)
        futuros = list(Agendamento.objects.ativos().filter(agenda_fixa=agenda).order_by('data'))
        self.assertGreaterEqual(len(futuros), 3)

        agenda.data_inicio = futuros[1].data
        agenda.save()
        sincronizar_agenda_fixa(agenda, dias_a_frente=21)
        futuros[0].refresh_from_db()
        self.assertTrue(futuros[0].deletado)

        preservado = futuros[1]
        preservado.status = 'FALTA'
        preservado.save()
        agenda.ativo = False
        agenda.save()
        sincronizar_agenda_fixa(agenda, dias_a_frente=21)

        preservado.refresh_from_db()
        self.assertFalse(preservado.deletado)
        self.assertEqual(preservado.status, 'FALTA')
        self.assertFalse(
            Agendamento.objects.ativos()
            .filter(agenda_fixa=agenda)
            .exclude(status__in=('REALIZADO', 'FALTA'))
            .exists()
        )

    def test_visoes_diaria_terapeuta_e_sala_usam_a_mesma_copia_sincronizada(self):
        agenda = self.criar_agenda()
        data_futura = self.proxima_data(agenda.dia_semana)
        sincronizar_agenda_fixa(agenda, dias_a_frente=7)
        copia = Agendamento.objects.ativos().get(agenda_fixa=agenda, data=data_futura)

        self.client.force_login(self.admin)
        diaria = self.client.get(reverse('lista_agendamentos'), {
            'data_inicio': data_futura.isoformat(),
            'data_fim': data_futura.isoformat(),
        })
        ocupacao = self.client.get(reverse('ocupacao_salas'), {'data': data_futura.isoformat()})

        self.assertEqual(diaria.status_code, 200)
        self.assertEqual(ocupacao.status_code, 200)
        self.assertContains(diaria, self.paciente.nome)
        self.assertContains(ocupacao, self.paciente.nome)

        self.client.force_login(self.usuario_1)
        terapeuta = self.client.get(reverse('lista_agendamentos'), {
            'data_inicio': data_futura.isoformat(),
            'data_fim': data_futura.isoformat(),
        })
        self.assertEqual(terapeuta.status_code, 200)
        self.assertContains(terapeuta, self.paciente.nome)
        self.assertEqual(copia.terapeuta, self.terapeuta_1)

    def test_modalidade_neuropsicologica_vem_da_lista_central(self):
        self.assertIn(
            ('AVALIACAO_NEUROPSICOLOGICA', 'Avaliação neuropsicológica'),
            MODALIDADE_CHOICES,
        )


class AgendamentoDuplicidadeRegressaoTest(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username='terapeuta_duplicidade')
        self.terapeuta = Terapeuta.objects.create(
            nome='Terapeuta Duplicidade',
            usuario=self.usuario,
        )
        self.paciente = Paciente.objects.create(nome='Paciente Duplicidade')
        self.outro_paciente = Paciente.objects.create(nome='Paciente Estrutural')
        self.data = timezone.localdate()

    def dados(self, **alteracoes):
        dados = {
            'paciente': self.paciente,
            'terapeuta': self.terapeuta,
            'data': self.data,
            'hora_inicio': time(8, 0),
            'hora_fim': time(9, 0),
        }
        dados.update(alteracoes)
        return dados

    def criar_duplicados_legados(self):
        Agendamento.objects.bulk_create([
            Agendamento(**self.dados()),
            Agendamento(**self.dados()),
        ])
        return list(Agendamento.objects.order_by('id'))

    def test_criacao_de_duplicado_ativo_continua_rejeitada(self):
        Agendamento.objects.create(**self.dados())

        with self.assertRaisesRegex(ValueError, 'Já existe um atendimento idêntico'):
            Agendamento.objects.create(**self.dados())

    def test_alteracao_estrutural_para_horario_ocupado_e_rejeitada(self):
        Agendamento.objects.create(**self.dados())
        alterado = Agendamento.objects.create(**self.dados(
            paciente=self.outro_paciente,
            hora_inicio=time(10, 0),
            hora_fim=time(11, 0),
        ))

        alterado.paciente = self.paciente
        alterado.hora_inicio = time(8, 0)
        alterado.hora_fim = time(9, 0)

        with self.assertRaisesRegex(ValueError, 'Já existe um atendimento idêntico'):
            alterado.save()

    def test_alteracao_somente_de_status_ignora_duplicado_legado(self):
        alvo, _ = self.criar_duplicados_legados()

        alvo.status = 'REALIZADO'
        alvo.save()

        alvo.refresh_from_db()
        self.assertEqual(alvo.status, 'REALIZADO')

    def test_alteracao_somente_de_tipo_ignora_duplicado_legado(self):
        alvo, _ = self.criar_duplicados_legados()

        alvo.tipo_atendimento = 'SOCIAL'
        alvo.save()

        alvo.refresh_from_db()
        self.assertEqual(alvo.tipo_atendimento, 'SOCIAL')

    def test_comando_de_auditoria_lista_detalhes_sem_alterar_dados(self):
        alvo, _ = self.criar_duplicados_legados()
        Consulta.objects.create(agendamento=alvo, evolucao='Evolução existente')
        saida = StringIO()

        call_command('auditar_agendamentos_duplicados', stdout=saida)

        texto = saida.getvalue()
        self.assertIn('ativos=2', texto)
        self.assertIn(f'id={alvo.id}', texto)
        self.assertIn('agenda_fixa_id=None', texto)
        self.assertIn('consulta=sim', texto)
        self.assertEqual(Agendamento.objects.ativos().count(), 2)


class EvolucaoRegressaoTest(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username='terapeuta_evolucao')
        self.usuario.groups.add(Group.objects.get_or_create(name='Terapeutas')[0])
        self.terapeuta = Terapeuta.objects.create(
            nome='Terapeuta Evolução',
            usuario=self.usuario,
        )
        self.paciente = Paciente.objects.create(nome='Paciente Evolução')
        self.data = timezone.localdate()
        self.client.force_login(self.usuario)

    def criar_agendamento(self):
        return Agendamento.objects.create(
            paciente=self.paciente,
            terapeuta=self.terapeuta,
            data=self.data,
            hora_inicio=time(8, 0),
            hora_fim=time(9, 0),
        )

    def test_atendimento_normal_salva_evolucao_e_marca_realizado(self):
        agendamento = self.criar_agendamento()

        response = self.client.post(
            reverse('realizar_consulta', args=[agendamento.id]),
            {'evolucao': 'Evolução normal'},
        )

        self.assertEqual(response.status_code, 302)
        agendamento.refresh_from_db()
        self.assertEqual(agendamento.status, 'REALIZADO')
        self.assertEqual(agendamento.consulta.evolucao, 'Evolução normal')

    def test_evolucao_de_duplicado_legado_salva_sem_value_error(self):
        alvo = self.criar_agendamento()
        Agendamento.objects.bulk_create([
            Agendamento(
                paciente=self.paciente,
                terapeuta=self.terapeuta,
                data=self.data,
                hora_inicio=time(8, 0),
                hora_fim=time(9, 0),
            ),
        ])

        response = self.client.post(
            reverse('realizar_consulta', args=[alvo.id]),
            {'evolucao': 'Evolução do legado'},
        )

        self.assertEqual(response.status_code, 302)
        alvo.refresh_from_db()
        self.assertEqual(alvo.status, 'REALIZADO')
        self.assertEqual(alvo.consulta.evolucao, 'Evolução do legado')
        self.assertEqual(Agendamento.objects.ativos().count(), 2)

    def test_falha_apos_salvar_formulario_desfaz_evolucao_e_status(self):
        agendamento = self.criar_agendamento()
        consulta = Consulta.objects.create(agendamento=agendamento, evolucao='Texto anterior')

        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            arquivo = SimpleUploadedFile('anexo.txt', b'conteudo de teste')
            with patch.object(Agendamento, 'save', side_effect=RuntimeError('falha simulada')):
                response = self.client.post(
                    reverse('realizar_consulta', args=[agendamento.id]),
                    {
                        'evolucao': 'Texto que deve sofrer rollback',
                        'arquivos_anexos': arquivo,
                    },
                )

            self.assertFalse(any(item.is_file() for item in Path(media_root).rglob('*')))

        self.assertEqual(response.status_code, 200)
        agendamento.refresh_from_db()
        self.assertEqual(agendamento.status, 'AGUARDANDO')
        self.assertEqual(
            Consulta.objects.get(agendamento=agendamento).evolucao,
            'Texto anterior',
        )
        self.assertFalse(AnexoConsulta.objects.filter(consulta=consulta).exists())
        self.assertContains(response, 'Não foi possível salvar o prontuário')
        self.assertContains(response, 'Texto que deve sofrer rollback')


class ReposicaoRegressaoTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_reposicao')
        self.admin.groups.add(Group.objects.get_or_create(name='Administrativo')[0])
        self.terapeuta = Terapeuta.objects.create(nome='Terapeuta Reposição')
        self.paciente_original = Paciente.objects.create(nome='Paciente Original')
        self.paciente_reposicao = Paciente.objects.create(nome='Paciente Reposição')
        self.sala = Sala.objects.create(nome='Sala Reposição')
        self.data = timezone.localdate()
        self.client.force_login(self.admin)

    def criar_original(self):
        return Agendamento.objects.create(
            paciente=self.paciente_original,
            terapeuta=self.terapeuta,
            sala=self.sala,
            data=self.data,
            hora_inicio=time(8, 0),
            hora_fim=time(9, 0),
        )

    def dados_post(self):
        return {
            'paciente': self.paciente_reposicao.id,
            'sala': self.sala.id,
            'falta-tipo_cancelamento': 'JUSTIFICADA',
            'falta-motivo_cancelamento': 'Reposição de teste',
        }

    def test_reposicao_cria_um_unico_novo_agendamento(self):
        original = self.criar_original()

        response = self.client.post(
            reverse('reposicao_agendamento', args=[original.id]),
            self.dados_post(),
        )

        self.assertEqual(response.status_code, 302)
        original.refresh_from_db()
        self.assertTrue(original.deletado)
        self.assertEqual(original.status, 'FALTA')
        self.assertEqual(
            Agendamento.objects.ativos().filter(
                paciente=self.paciente_reposicao,
                terapeuta=self.terapeuta,
                data=self.data,
                hora_inicio=time(8, 0),
                hora_fim=time(9, 0),
            ).count(),
            1,
        )

    def test_falha_na_criacao_da_reposicao_desfaz_soft_delete_do_original(self):
        original = self.criar_original()
        existente = Agendamento.objects.create(
            paciente=self.paciente_reposicao,
            terapeuta=self.terapeuta,
            sala=self.sala,
            data=self.data,
            hora_inicio=time(8, 0),
            hora_fim=time(9, 0),
        )

        response = self.client.post(
            reverse('reposicao_agendamento', args=[original.id]),
            self.dados_post(),
        )

        self.assertEqual(response.status_code, 200)
        original.refresh_from_db()
        self.assertFalse(original.deletado)
        self.assertEqual(original.status, 'AGUARDANDO')
        self.assertEqual(
            Agendamento.objects.ativos().filter(
                paciente=self.paciente_reposicao,
                terapeuta=self.terapeuta,
                data=self.data,
                hora_inicio=time(8, 0),
                hora_fim=time(9, 0),
            ).get(),
            existente,
        )
        self.assertContains(response, 'Nenhuma alteração foi salva')


class AgendaFixaReposicaoRegressaoTest(TestCase):
    def test_sincronizacao_nao_reativa_copia_substituida_por_reposicao(self):
        data = timezone.localdate()
        usuario = User.objects.create_user(username='terapeuta_grade_reposicao')
        terapeuta = Terapeuta.objects.create(nome='Terapeuta Grade', usuario=usuario)
        paciente = Paciente.objects.create(nome='Paciente Grade')
        sala = Sala.objects.create(nome='Sala Grade')
        agenda = AgendaFixa.objects.create(
            paciente=paciente,
            terapeuta=terapeuta,
            sala=sala,
            dia_semana=data.weekday(),
            hora_inicio=time(8, 0),
            hora_fim=time(9, 0),
            data_inicio=data,
        )
        copia_substituida = Agendamento.objects.create(
            agenda_fixa=agenda,
            paciente=paciente,
            terapeuta=terapeuta,
            sala=sala,
            data=data,
            hora_inicio=time(8, 0),
            hora_fim=time(9, 0),
            deletado=True,
        )
        reposicao = Agendamento.objects.create(
            paciente=paciente,
            terapeuta=terapeuta,
            sala=sala,
            data=data,
            hora_inicio=time(8, 0),
            hora_fim=time(9, 0),
        )

        sincronizar_agenda_fixa(agenda, dias_a_frente=0, data_referencia=data)

        copia_substituida.refresh_from_db()
        reposicao.refresh_from_db()
        self.assertTrue(copia_substituida.deletado)
        self.assertEqual(reposicao.agenda_fixa, agenda)
        self.assertEqual(
            Agendamento.objects.ativos().filter(
                paciente=paciente,
                terapeuta=terapeuta,
                data=data,
                hora_inicio=time(8, 0),
                hora_fim=time(9, 0),
            ).count(),
            1,
        )
