from django.core.management.base import BaseCommand
from django.db.models import Count, Exists, OuterRef

from core.models import Agendamento, Consulta


class Command(BaseCommand):
    help = (
        "Lista, sem alterar dados, grupos de agendamentos ativos com o mesmo "
        "paciente, terapeuta, data e horário."
    )

    def handle(self, *args, **options):
        campos_grupo = (
            'paciente_id', 'terapeuta_id', 'data', 'hora_inicio', 'hora_fim',
        )
        grupos = (
            Agendamento.objects.ativos()
            .values(*campos_grupo)
            .annotate(total=Count('id'))
            .filter(total__gt=1)
            .order_by('data', 'hora_inicio', 'paciente_id', 'terapeuta_id')
        )

        total_grupos = 0
        total_registros = 0
        consulta_existente = Consulta.objects.filter(agendamento_id=OuterRef('pk'))

        for grupo in grupos.iterator():
            total_grupos += 1
            filtros = {campo: grupo[campo] for campo in campos_grupo}
            registros = (
                Agendamento.objects.filter(deletado=False, **filtros)
                .annotate(tem_consulta=Exists(consulta_existente))
                .order_by('id')
            )

            self.stdout.write(
                "\nGrupo "
                f"paciente={grupo['paciente_id']} "
                f"terapeuta={grupo['terapeuta_id']} "
                f"data={grupo['data']} "
                f"horário={grupo['hora_inicio']}-{grupo['hora_fim']} "
                f"ativos={grupo['total']}"
            )
            for registro in registros:
                total_registros += 1
                self.stdout.write(
                    "  "
                    f"id={registro.id} status={registro.status} "
                    f"deletado={registro.deletado} "
                    f"agenda_fixa_id={registro.agenda_fixa_id} "
                    f"consulta={'sim' if registro.tem_consulta else 'não'}"
                )

        if not total_grupos:
            self.stdout.write("Nenhum grupo duplicado ativo encontrado.")
            return

        self.stdout.write(
            f"\nResumo: {total_grupos} grupo(s), "
            f"{total_registros} agendamento(s) ativo(s)."
        )
