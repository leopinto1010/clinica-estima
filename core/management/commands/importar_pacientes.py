import csv
import re
from datetime import datetime
from django.core.management.base import BaseCommand
from core.models import Paciente

class Command(BaseCommand):
    help = 'Importa pacientes tratando CPF, DATA e TELEFONE nulos.'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Caminho para o arquivo CSV')

    def handle(self, *args, **kwargs):
        csv_file_path = kwargs['csv_file']
        self.stdout.write(self.style.WARNING(f'Lendo arquivo: {csv_file_path}'))

        # --- INDICES (Ajustados para o seu CSV) ---
        INDICE_ID = 0
        INDICE_NOME = 1
        INDICE_CPF = 3
        INDICE_NASCIMENTO = 5
        INDICE_TELEFONE = 6
        INDICE_TIPO = 16

        contador_sucesso = 0
        contador_erros = 0
        
        DE_PARA_TIPO = {
            'particular': 'PARTICULAR',
            'convênio': 'CONVENIO',
            'convenio': 'CONVENIO',
            'social': 'SOCIAL',
            'desconto': 'DESCONTO'
        }

        try:
            with open(csv_file_path, newline='', encoding='utf-8') as csvfile:
                leitor = csv.reader(csvfile, delimiter=',')
                next(leitor) 

                for i, linha in enumerate(leitor):
                    try:
                        if len(linha) < 7: continue

                        id_csv = linha[INDICE_ID]
                        nome_raw = linha[INDICE_NOME].strip().title()
                        if not nome_raw: continue

                        # --- TRATAMENTO CPF ---
                        cpf_raw = linha[INDICE_CPF].strip()
                        cpf_limpo = re.sub(r'[^0-9]', '', cpf_raw)
                        cpf_final = cpf_limpo if len(cpf_limpo) == 11 else None
                        
                        # --- TRATAMENTO DATA ---
                        nasc_raw = linha[INDICE_NASCIMENTO].strip()
                        data_nascimento = None
                        try:
                            # Tenta formato ISO (AAAA-MM-DD) que está no seu CSV
                            data_nascimento = datetime.strptime(nasc_raw, '%Y-%m-%d').date()
                        except ValueError:
                            try:
                                # Tenta formato BR (DD/MM/AAAA) por garantia
                                data_nascimento = datetime.strptime(nasc_raw, '%d/%m/%Y').date()
                            except ValueError:
                                pass # Fica como None (Vazio)
                        
                        # --- TRATAMENTO TELEFONE (A CORREÇÃO ESTÁ AQUI) ---
                        tel_raw = linha[INDICE_TELEFONE].strip()
                        tel_limpo = re.sub(r'[^0-9]', '', tel_raw)
                        
                        # Se não tiver 10 (Fixo) ou 11 (Celular) dígitos, salva como NULO
                        if len(tel_limpo) not in [10, 11]:
                            tel_final = None
                        else:
                            tel_final = tel_limpo

                        # --- TIPO ---
                        tipo_raw = linha[INDICE_TIPO].strip().lower() if len(linha) > INDICE_TIPO else 'particular'
                        tipo_banco = DE_PARA_TIPO.get(tipo_raw, 'PARTICULAR')

                        # --- SALVAR ---
                        defaults_data = {
                            'nome': nome_raw,
                            'data_nascimento': data_nascimento,
                            'telefone': tel_final, # Agora usamos o telefone tratado
                            'tipo_padrao': tipo_banco
                        }

                        if cpf_final:
                            obj, created = Paciente.objects.update_or_create(
                                cpf=cpf_final, defaults=defaults_data
                            )
                        else:
                            obj, created = Paciente.objects.get_or_create(
                                nome=nome_raw, cpf=None, defaults=defaults_data
                            )
                        
                        contador_sucesso += 1

                    except Exception as e:
                        # Loga o erro no terminal para sabermos exatamente quem falhou
                        self.stdout.write(self.style.ERROR(f'Erro ID {linha[0]} ({linha[1]}): {str(e)}'))
                        contador_erros += 1

            self.stdout.write(self.style.SUCCESS(f'--- FIM ---'))
            self.stdout.write(self.style.SUCCESS(f'Processados com sucesso: {contador_sucesso}'))
            if contador_erros > 0:
                self.stdout.write(self.style.ERROR(f'Falhas: {contador_erros} (Verifique as mensagens acima)'))

        except FileNotFoundError:
            self.stdout.write(self.style.ERROR('Arquivo não encontrado.'))