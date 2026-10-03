# Auditoria completa do sistema

Auditoria concluída em modo estritamente somente leitura. Nenhum arquivo foi criado, editado ou apagado durante a etapa de investigação; banco, migrações e testes não foram executados; o Git permaneceu limpo em `main`.

A conclusão central é: o sistema tem funcionalidades reais e relevantes, mas hoje depende de regras espalhadas, permissões inconsistentes e integridade mantida principalmente pela interface. Há riscos críticos de acesso indevido a prontuários, exposição de mídia clínica e credenciais antigas no histórico Git.

## 1. Resumo executivo

O repositório contém:

- Django 5.2.9, Python, SQLite e Jazzmin.
- Um único app Django, `core`.
- 10 models de domínio.
- 35 views próprias e 38 rotas totais.
- 26 templates, somando aproximadamente 4.000 linhas.
- `views.py` com 1.721 linhas.
- 34 migrações.
- 6 testes automatizados.
- Um comando de importação CSV.
- Um vídeo de prontuário versionado no Git.
- Nenhum README, documentação operacional, CI, configuração de backup ou manifesto de implantação.

Principais conclusões:

1. **Crítico — autorização de prontuário:** qualquer usuário autenticado sem perfil reconhecido consegue potencialmente abrir e editar um atendimento conhecendo seu ID. O fluxo ainda cria uma `Consulta` vazia durante um simples GET.
2. **Crítico — dados clínicos:** há um vídeo de prontuário dentro do repositório e `/media/` não está no `.gitignore`.
3. **Crítico — segredo histórico:** um `.env` foi versionado e removido depois, mas seu conteúdo permanece recuperável no histórico Git.
4. **Alto — Django desatualizado:** a série 5.2 é LTS, mas o projeto está fixado em 5.2.9, anterior a diversas correções de segurança da própria série.
5. **Alto — mutações por GET:** exclusões, reversões e mudanças de status podem ocorrer ao visitar um link.
6. **Alto — agenda sem integridade suficiente:** não há proteção de conflito de sala, bloqueio de sala não impede agendamento e várias regras não existem no banco.
7. **Alto — agenda fixa:** alterações de paciente/modalidade/vigência não são propagadas corretamente aos agendamentos materializados.
8. **Alto — escopos de coordenação e administração são inconsistentes entre páginas.**
9. **Não existe um módulo financeiro real:** o item “Financeiro & Equipe” é um relatório de contagens de realizados e faltas, sem valores, pagamentos ou faturamento.
10. **A V2 não foi projetada nesta auditoria**, conforme solicitado.

## 2. Arquitetura atual

### Tecnologias

- Django 5.2.9.
- Banco SQLite configurado diretamente em `config/settings.py`.
- Autenticação, grupos, sessões e admin nativos do Django.
- Jazzmin para o Django Admin.
- `python-decouple` para `SECRET_KEY`, `DEBUG` e `ALLOWED_HOSTS`.
- Templates Django renderizados no servidor.
- Bootstrap 5.3.0, Bootstrap Icons, jQuery 3.6.0, Flatpickr, Select2 e Google Fonts carregados por CDN em `base.html`.
- Arquivos enviados armazenados localmente em `media/prontuarios/AAAA/MM/`.
- WSGI e ASGI padrão, sem configuração PythonAnywhere versionada.

Dependências Python: `requirements.txt`.

### Organização

```text
SISTEMA
├── config
│   ├── settings.py          configuração global
│   ├── urls.py              todas as rotas do sistema
│   ├── wsgi.py
│   └── asgi.py
├── core
│   ├── models.py            todos os models e escolhas de domínio
│   ├── views.py             todas as views e boa parte da regra de negócio
│   ├── forms.py             forms e validações de agenda
│   ├── utils.py             geração/materialização de agenda
│   ├── decorators.py        papéis e decorators de autorização
│   ├── context_processors.py
│   ├── admin.py
│   ├── tests.py
│   ├── migrations/
│   ├── management/commands/importar_pacientes.py
│   ├── templatetags/custom_tags.py
│   └── templates/
├── static
│   └── img/logo_estima.png
└── media
    └── prontuarios/...mp4
```

Todas as rotas estão no arquivo raiz `config/urls.py`; não existe `core/urls.py`. Não há camada de serviços, selectors, casos de uso, API ou tarefas agendadas.

## 3. Mapa completo de funcionalidades

### Autenticação e visão inicial

| URL | Fluxo | Banco/template/JS |
|---|---|---|
| `/admin/` | Django Admin com Jazzmin | CRUD de usuários, pacientes, terapeutas, agendamentos, consultas, convênios, salas e agenda fixa; ação de materializar agenda |
| `/login/` | `LoginView` | `login.html`; cria sessão |
| `/logout/` | `LogoutView` por POST | Form oculto em `base.html`; encerra sessão |
| `/` | `dashboard` | Lê `Agendamento` e `Paciente`; mostra agenda do dia conforme perfil |

### Pacientes e prontuário

| URL | View → form → template | Models e efeitos |
|---|---|---|
| `/pacientes/` | `lista_pacientes` → `lista_pacientes.html` | Lista/busca/filtros. Inesperadamente chama `save()` em GET para preencher `nome_search` ausente |
| `/pacientes/novo/` | `cadastro_paciente` → `PacienteForm` → `cadastro_paciente.html` | Cria `Paciente`; apenas admin |
| `/pacientes/editar/<id>/` | `editar_paciente` → `PacienteForm` | Atualiza cadastro e estado ativo |
| `/paciente/<id>/` | `detalhe_paciente` → `detalhe_paciente.html` | Lê paciente, consultas e terapeutas; JS filtra evoluções localmente |

A lista e a autorização estão concentradas em `core/views.py`, a partir de `lista_pacientes`. O histórico clínico começa em `detalhe_paciente`.

### Agenda operacional

| URL | View/form/template | Efeito |
|---|---|---|
| `/agendamentos/` | `lista_agendamentos` → `lista_agendamentos.html` | Grade semanal, filtros, bloqueios, modal JS de ações |
| `/agendamentos/novo/` | `novo_agendamento` → `AgendamentoForm` | Cria de 1 a 49 agendamentos semanais avulsos |
| `/agendamentos/reposicao/<id>/` | `reposicao_agendamento` → `ReposicaoForm` + `RegistrarFaltaForm` | Marca o antigo como falta/deletado e cria novo atendimento no mesmo horário |
| `/agendamentos/confirmar/<id>/` | `confirmar_agendamento` | Grava `CONFIRMADO` por GET, embora esse status não exista mais nas choices |
| `/agendamentos/atender/<id>/` | `realizar_consulta` → `ConsultaForm` → `realizar_consulta.html` | GET cria `Consulta`; POST salva evolução, anexos e marca realizado |
| `/agendamentos/falta/<id>/` | `marcar_falta` → `RegistrarFaltaForm` | Registra tipo e observação da falta |
| `/agendamentos/excluir/<id>/` | `excluir_agendamento` | Exclusão física por GET para atendimento avulso |
| `/agendamentos/limpar-dia/` | `limpar_dia` | POST faz soft delete em massa, exceto realizados |
| `/agendamentos/reverter/<id>/` | `reverter_agendamento` | Por GET apaga a consulta e volta o agendamento para aguardando |
| `/consultas/historico/` | `lista_consultas_geral` | Histórico de realizados e faltas |

O núcleo deste domínio está entre `lista_agendamentos` e `realizar_consulta` em `core/views.py`.

### Agenda fixa e bloqueios

| URL | Fluxo | Efeito |
|---|---|---|
| `/agenda-fixa/` | Grade semanal de regras fixas | Leitura de `AgendaFixa` e `BloqueioFixo` |
| `/agenda-fixa/nova/` | `AgendaFixaForm` | Cria regra e materializa atendimentos até 31/12 |
| `/agenda-fixa/editar/<id>/` | `AgendaFixaForm` | Atualiza ou remove atendimentos futuros e rematerializa |
| `/agenda-fixa/excluir/<id>/` | Confirmação por GET, execução por POST | Desativa a regra; opcionalmente faz soft delete dos futuros aguardando |
| `/agendamentos/bloqueio/novo/` | `BloqueioFixoForm` | Cria indisponibilidade semanal do terapeuta |
| `/agendamentos/bloqueio/excluir/<id>/` | Exclusão direta | Apaga bloqueio por GET |

A materialização está em `core/utils.py`, na função `gerar_agenda_futura`.

### Equipe

| URL | Fluxo | Efeito |
|---|---|---|
| `/equipe/novo/` | `CadastroEquipeForm` | Cria `User`, grupo e, para perfis clínicos, `Terapeuta` |
| `/equipe/lista/` | Lista e filtros | Lê terapeutas e usuários |
| `/equipe/editar/<id>/` | Form manual, sem ModelForm | Altera terapeuta, ativa/desativa usuário e, para dono, troca grupo |
| `/equipe/excluir/<id>/` | Exclusão direta | Por GET apaga usuário e terapeuta se não houver agendamentos |

Perfis implementados: `Administrativo`, `Terapeutas`, `Coordenação` e `Donos`, definidos em `core/decorators.py`.

### Salas e relatórios

| URL | Funcionalidade | Observações |
|---|---|---|
| `/relatorios/salas/` | Ocupação diária por sala | Agrupa atendimentos conjuntos e exibe bloqueios |
| `/relatorios/salas/semanal/` | Grade semanal de uma sala | Mostra atendimentos; impressão esconde avulsos |
| `/relatorios/salas/bloqueio/novo/` | Criar bloqueio semanal de sala | Não impede agendamentos; afeta apenas visualização |
| `/relatorios/salas/bloqueio/excluir/<id>/` | Excluir bloqueio | Mutação por GET |
| `/relatorios/` | Realizados, faltas e taxa | Não possui valores financeiros |
| `/relatorios/faltas/` | Engajamento por paciente | Percentuais e telefone |
| `/relatorios/pacientes/` | Ranking de frequência/faltas | Pode ordenar e filtrar |
| `/relatorios/grade-pacientes/` | Grade fixa consolidada | Células editáveis; rascunhos ficam somente em `localStorage` |
| `/relatorios/atrasos/` | Evoluções atrasadas >24h | Agrupa atendimentos aguardando por terapeuta |
| `/relatorios/controle-atendimentos/` | Presenças, faltas e “reposições” | “Reposição” é inferida, não registrada explicitamente |

## 4. Models e banco

As definições estão em `core/models.py`.

### Relações

```text
auth.User ── 0..1 Terapeuta

Convenio ──< Paciente
Paciente ──< AgendaFixa >── Terapeuta
Sala ──< AgendaFixa

AgendaFixa ──< Agendamento
Paciente ──< Agendamento >── Terapeuta
Sala ──< Agendamento

Agendamento ── 0..1 Consulta ──< AnexoConsulta

Terapeuta ──< BloqueioFixo
Sala ──< BloqueioSala
```

### Análise por model

| Model | Finalidade e uso | Problemas estruturais |
|---|---|---|
| `Sala` | Sala usada por agenda fixa, atendimentos e bloqueios | Nome não é único; sem status ativo; sem validação de conflito |
| `Convenio` | Convênio opcional do paciente | Só possui nome/ativo; não está integrado a autorização, faturamento ou agendamento |
| `Paciente` | Dados cadastrais, contato, convênio e autorização de imagem | CPF valida apenas 11 dígitos, sem checksum; deleção em cascata pode apagar agenda e histórico; não possui auditoria |
| `Terapeuta` | Profissional e vínculo opcional com `User` | Perfil pode existir sem usuário; “ativo” depende indiretamente de `User.is_active`; coordenação duplicada em grupo e booleano |
| `AgendaFixa` | Regra semanal materializada em agendamentos | Sem constraints de sobreposição, unicidade, vigência ou horário válido |
| `Agendamento` | Unidade central da agenda, presença/falta e tipo de atendimento | Sem constraints no banco; soft e hard delete coexistem; status inconsistente; não há vínculo de reposição |
| `Consulta` | Evolução clínica 1:1 com agendamento | Não registra autor, data de alteração, versões ou assinatura; pode ser criada vazia em GET |
| `AnexoConsulta` | Arquivo clínico anexado | Só valida tamanho; não valida conteúdo/MIME; não registra autor; URL direta |
| `BloqueioFixo` | Bloqueio semanal do terapeuta | Sem vigência, unicidade ou prevenção de sobreposição |
| `BloqueioSala` | Bloqueio semanal da sala | Só afeta a visualização; não participa da validação de agendamento |

Comportamentos de `on_delete` relevantes:

- Excluir paciente pode apagar suas agendas, agendamentos, consultas e referências clínicas em cascata.
- Excluir usuário apaga seu `Terapeuta`.
- Terapeuta com agenda/agendamento é protegido em alguns relacionamentos.
- Excluir agendamento apaga a `Consulta` e registros de anexos, mas o arquivo físico pode permanecer órfão.

## 5. Views, fluxos e manutenção

### Concentração de responsabilidades

`core/views.py` contém:

- autorização;
- consultas ORM;
- transições de estado;
- materialização de agenda;
- cálculos de relatórios;
- preparação de grades visuais;
- upload e exclusão de arquivos;
- criação de usuários e grupos;
- mensagens e navegação.

Views especialmente complexas:

- `lista_agendamentos`: cerca de 155 linhas.
- `lista_agendas_fixas`: montagem manual da grade e expansão de bloqueios.
- `ocupacao_salas`: ordenação específica, agrupamento e bloqueios.
- `controle_atendimentos`: cerca de 130 linhas e consultas separadas por dia.
- `agenda_semanal_sala`: nova implementação paralela das grades anteriores.

### Duplicação e queries

- Remoção de acentos existe em `models.py` e `views.py`.
- A lógica de atendimento conjunto é repetida no dashboard, agenda e salas.
- As verificações de papel são repetidas várias vezes por request e também pelo context processor.
- Listas de meses, especialidades abreviadas e estados são codificadas manualmente em diferentes locais.
- `relatorio_grade_pacientes` executa uma consulta de agendas para cada paciente: padrão N+1.
- `lista_pacientes` corrige `nome_search` fazendo vários `save()` durante GET.
- Os três tipos de grade — agenda, agenda fixa e ocupação — possuem estruturas semelhantes, mas implementações independentes.
- A action do admin chamada para os “selecionados” ignora o queryset selecionado e materializa todas as agendas ativas em `core/admin.py`.

## 6. Templates, CSS e JavaScript

Dos 26 templates:

- 24 herdam de `base.html`.
- `base.html` e `login.html` são páginas completas.
- Não existe nenhum componente `{% include %}`.
- Dez templates contêm blocos `<style>`.
- Oito páginas possuem JavaScript inline próprio.
- Não existe arquivo CSS ou JS local; `static/` contém apenas o logo.
- Há muitos estilos e handlers inline.

Duplicações principais:

- `novo_agendamento.html` e `form_agenda_fixa.html`.
- Modais/formulários de bloqueio de terapeuta e sala.
- Cabeçalhos e filtros de mês/ano dos relatórios.
- Tabelas de grade semanal.
- Cards, badges, mensagens vazias e barras de ações.
- Filtros de pacientes e terapeutas.

Funcionalidades JavaScript:

- Navegação semanal e modal de ações em `lista_agendamentos.html`.
- Pré-visualização acumulativa de upload em `realizar_consulta.html`.
- Filtro local do histórico por terapeuta.
- Persistência de posição de rolagem em `sessionStorage`.
- Simulação de grade em `localStorage`; não altera o banco, mas persiste apenas naquele navegador em `relatorio_grade_pacientes.html`.

## 7. Regras de negócio identificadas

### Confirmadas pelo código

1. Papéis:

   - `Administrativo` e `Donos` são tratados como admin.
   - `Donos` e superusuários possuem privilégios adicionais.
   - `Terapeutas` e `Coordenação` são considerados clínicos.
   - Coordenação pode ser reconhecida pelo grupo ou pelo booleano do terapeuta.

2. Pacientes:

   - Pacientes inativos não aparecem nos formulários de novos atendimentos.
   - CPF é opcional, único quando preenchido e limitado a 11 dígitos.
   - `nome_search` guarda nome sem acentos para pesquisa.
   - Autorização de imagem é apenas uma classificação; não existe enforcement sobre anexos.

3. Agenda:

   - Duração padrão automática: 60 minutos.
   - Grade visual padrão: intervalos de 45 minutos, manhã desde 07:15 e tarde desde 13:30.
   - Conflito é verificado por terapeuta e sobreposição de horário.
   - Faltas não bloqueiam o horário.
   - Não há verificação de conflito por paciente ou sala.
   - Não há validação de bloqueio de sala.
   - Agendamentos avulsos podem repetir semanalmente até 48 vezes.

4. Agenda fixa:

   - É materializada do dia atual até 31 de dezembro do ano corrente.
   - Respeita data final quando preenchida.
   - Se já houver um agendamento aguardando do mesmo paciente, ele pode ser “absorvido” pela agenda fixa.
   - Se o conflito for de outro paciente, a ocorrência simplesmente não é criada, sem erro persistente.
   - Não existe rotina agendada no repositório para abrir automaticamente o próximo ano.

5. Status:

   - Modelo atual: `AGUARDANDO`, `REALIZADO`, `FALTA`.
   - Finalizar prontuário marca `REALIZADO`.
   - Registrar falta exige tipo.
   - Reverter realizado apaga a consulta e volta para `AGUARDANDO`.
   - Ainda existe código que grava `CONFIRMADO`.

6. Reposição:

   - O registro antigo recebe `deletado=True`.
   - Se ainda não era falta, passa a ser falta e exige justificativa.
   - Um novo agendamento avulso é criado para o paciente escolhido no mesmo horário.
   - Não há relacionamento explícito entre falta e reposição.

7. Relatórios:

   - Atraso de evolução significa atendimento ainda aguardando, terminado há pelo menos 24 horas.
   - Taxa de faltas por paciente exclui falta do terapeuta em um relatório, mas não em todos.
   - O controle chama todo atendimento avulso realizado de “reposição”.

### Comportamentos prováveis

- Atendimentos do mesmo paciente, horário e sala com profissionais diferentes representam atendimento conjunto.
- `BloqueioSala` foi concebido como indisponibilidade real, mas atualmente é apenas visual.
- O relatório “Financeiro & Equipe” provavelmente começou como indicador operacional; não há dados financeiros suficientes para ser financeiro.
- A edição livre da grade de pacientes é uma ferramenta de simulação/impressão, não um editor da agenda oficial.

### Hipóteses que precisam de confirmação

- Se terapeutas devem visualizar a evolução completa de todos os profissionais que atenderam o mesmo paciente.
- Se coordenadores devem ver apenas a própria agenda, toda a especialidade ou toda a clínica.
- Se um dono deve ter acesso irrestrito a prontuários.
- Se a sala pode receber simultaneamente vários terapeutas somente quando é o mesmo paciente.
- Se 45 ou 60 minutos é a duração clínica padrão.
- Se bloqueios devem ter vigência e impedir efetivamente novos atendimentos.

## 8. Código suspeito, morto ou parcialmente implementado

- `confirmar_agendamento` possui URL, mas não há link nos templates e o status que grava foi removido do model.
- `terapeuta_required` está definido, importado, mas não é usado.
- `make_datetime_aware` não é usado.
- Import de `django.forms` em `views.py` não é usado.
- Import de `Q` em `utils.py` não é usado.
- Import de `get_horarios_clinica` em `forms.py` não é usado.
- Parâmetro `user_request` de `criar_agendamentos_em_lote` não é usado.
- O carregamento de `custom_tags` em alguns formulários não é necessário.
- `formatar_nome_curto` é apenas um wrapper de `formatar_nome_terapeuta`.
- Não encontrei template aparentemente órfão: todos são renderizados ou usados como base.
- Não encontrei model atual totalmente sem uso.
- `BloqueioAgenda` aparece apenas no histórico de migrações e foi substituído por `BloqueioFixo`; isso parece uma remoção histórica normal.
- O teste de formatação de nome contém também uma asserção de conflito de agenda aparentemente deslocada por copy/paste em `core/tests.py`.

## 9. Segurança e produção

### Críticos

1. **Bypass de autorização em prontuários**

   Em `realizar_consulta`, as negações cobrem coordenador, administrativo comum e terapeuta de outro atendimento. Um usuário apenas autenticado, sem esses papéis, não cai em nenhuma negação e chega ao prontuário. A view aceita um ID arbitrário, cria a consulta e permite POST de evolução/anexos.

2. **Mídia clínica versionada**

   Existe um vídeo de aproximadamente 7,8 MB em `media/prontuarios/...`, rastreado pelo Git. `media/` também não está ignorado em `.gitignore`.

3. **Mídia acessada por URL direta**

   O template usa diretamente `anexo.arquivo.url`. Não há endpoint autenticado para download. Se o PythonAnywhere estiver expondo `/media/`, quem obtiver a URL pode contornar as permissões da aplicação.

4. **`.env` recuperável pelo histórico Git**

   O arquivo não está na versão atual, mas existe como blob no histórico. O commit `f827c2b` o removeu; a remoção não elimina o conteúdo de commits anteriores. Nenhum valor foi aberto ou reproduzido nesta auditoria.

### Altos

- `excluir_agendamento`, `excluir_bloqueio`, `excluir_bloqueio_sala`, `excluir_terapeuta`, `reverter_agendamento` e `confirmar_agendamento` alteram dados por GET.
- Abrir `realizar_consulta` por GET cria uma `Consulta` vazia.
- Upload valida apenas tamanho. O `accept` do HTML não é segurança; não há validação real de extensão, MIME, malware, quantidade total ou conteúdo.
- Não existem `AUTH_PASSWORD_VALIDATORS`; o sistema aceita política de senha muito fraca.
- Não há rate limit, bloqueio de tentativas ou MFA no código.
- Não há configurações explícitas de `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, HSTS ou `SECURE_SSL_REDIRECT`.
- Não há trilha de auditoria para leitura/alteração de prontuário, exclusão de anexo, mudança de status ou alteração de permissões.
- Usuários sem papel podem visualizar a agenda geral por uma omissão no `else` de `lista_agendamentos`.
- Coordenadores podem ver o relatório de faltas e telefones de todos os pacientes, sem filtro por especialidade.
- O comando CSV imprime nome/identificador do paciente em erros, o que pode levar dados pessoais aos logs.
- Bibliotecas de frontend são carregadas por CDNs sem Subresource Integrity; algumas URLs do Flatpickr não fixam versão.

### Dependência Django

O projeto fixa Django 5.2.9. Django 5.2 continua sendo uma série LTS, mas o índice oficial registra várias versões 5.2.x posteriores e correções de segurança após 5.2.9. Portanto, a versão fixada deve ser considerada desatualizada para produção. Isso não significa que todas as CVEs sejam exploráveis nesta aplicação, mas uploads e admin tornam algumas classes de correção especialmente relevantes.

- Série 5.2 e suporte oficial: <https://www.djangoproject.com/download/>
- Arquivo oficial de correções de segurança: <https://docs.djangoproject.com/en/5.2/releases/security/>

### Aspectos positivos

- `SECRET_KEY`, `DEBUG` e `ALLOWED_HOSTS` não estão hardcoded na versão atual.
- CSRF middleware está ativo.
- Forms POST possuem token CSRF.
- `DEBUG` assume `False` por padrão.
- O logout usa POST.
- Há separação parcial entre dados administrativos e evolução clínica.

## 10. Integridade e bugs funcionais relevantes

- `CONFIRMADO` pode ser gravado, mas não é uma choice válida e não aparece nos filtros.
- Horário final pode ser anterior ao inicial em agendamento e agenda fixa; apenas os forms de bloqueio verificam a ordem.
- Bloqueio de sala e dupla ocupação de sala não impedem criação.
- Duas agendas fixas sobrepostas do mesmo terapeuta podem ser salvas.
- Ao editar agenda fixa, paciente, modalidade, tipo e vigência inicial não são propagados corretamente.
- Uma agenda fixa marcada inativa pelo formulário ainda pode ser materializada quando passada diretamente para `gerar_agenda_futura`.
- Reposição não é atômica: o registro antigo pode ser alterado antes de uma falha ao criar o novo.
- Reposição pode ser aplicada até a um atendimento realizado; não existe bloqueio por estado.
- Exclusão/reversão de consulta pode deixar arquivos físicos órfãos.
- O filtro semanal de `relatorio_mensal` afeta os totais gerais, mas não as anotações por terapeuta.
- O filtro de tipo em frequência usa o tipo padrão do paciente, não necessariamente o tipo efetivo dos atendimentos.
- Relatórios usam definições diferentes para faltas repostas e faltas do terapeuta.
- Datas e inteiros vindos da query string são convertidos sem tratamento consistente; valores inválidos podem produzir erro 500.
- SQLite em produção aumenta risco de bloqueio concorrente, limita evolução operacional e concentra banco e arquivos no filesystem do servidor.

## 11. Dívida técnica priorizada

| Problema | Onde | Impacto | Prioridade |
|---|---|---|---|
| Bypass de prontuário | `realizar_consulta` | Leitura/escrita clínica indevida | Crítica |
| Mídia clínica no Git e URL direta | `media/`, template e settings | Vazamento de dados sensíveis | Crítica |
| `.env` no histórico | Histórico Git | Credenciais antigas recuperáveis | Crítica |
| Django 5.2.9 atrasado | `requirements.txt` | Correções de segurança ausentes | Alta |
| Mutações por GET | Diversas views | CSRF, robôs e cliques acidentais | Alta |
| Integridade apenas na aplicação | Models/forms/utils | Conflitos e estados inválidos | Alta |
| Recorrência materializada frágil | `AgendaFixa` e `gerar_agenda_futura` | Agenda divergente das regras | Alta |
| Modelo de permissões duplicado | Grupos + flags + `is_staff` | Acessos inconsistentes | Alta |
| SQLite e mídia local | `settings.py` | Concorrência, backup e recuperação | Alta |
| `views.py` monolítico | 1.721 linhas | Alto risco ao alterar qualquer domínio | Alta |
| Falta de auditoria clínica | Models/views | Sem autoria, versão ou rastreabilidade | Alta |
| Cobertura de testes pequena | `tests.py` | Regressões não detectadas | Alta |
| Relatórios semanticamente inconsistentes | Views de relatório | Decisões baseadas em números divergentes | Alta |
| HTML/CSS/JS inline e duplicado | Templates | Manutenção visual custosa | Média |
| N+1 e lógica em Python | Relatórios/grades | Escalabilidade e lentidão | Média |
| Código residual e imports mortos | Views/utils/forms | Confusão e risco de reativação acidental | Baixa/média |
| Ausência de README e documentação | Raiz | Dependência de conhecimento informal | Alta |

## 12. Mapa final do sistema

```text
SISTEMA
├── Autenticação e papéis
│   ├── login/logout
│   ├── grupos Administrativo, Terapeutas, Coordenação e Donos
│   └── Django Admin/Jazzmin
├── Pacientes
│   ├── cadastro e edição
│   ├── ativação/inativação
│   ├── convênio/carteirinha
│   ├── autorização de imagem
│   └── histórico clínico
├── Agenda operacional
│   ├── agenda semanal
│   ├── agendamento avulso e repetição
│   ├── presença/realização
│   ├── falta
│   ├── reposição
│   ├── limpeza em massa
│   └── reversão
├── Planejamento recorrente
│   ├── agenda fixa
│   ├── materialização até o fim do ano
│   └── bloqueio semanal de terapeuta
├── Prontuário
│   ├── evolução
│   ├── anexos
│   └── histórico multidisciplinar
├── Equipe
│   ├── criação de usuário
│   ├── vínculo com terapeuta
│   ├── especialidade/coordenação
│   └── ativação/exclusão
├── Salas
│   ├── ocupação diária
│   ├── visão semanal
│   └── bloqueio semanal
├── Relatórios
│   ├── realizados e faltas
│   ├── frequência de pacientes
│   ├── atrasos de evolução
│   ├── controle de atendimentos
│   └── grade consolidada/simulação
└── Operações auxiliares
    ├── importação CSV
    └── materialização manual pelo admin
```

| Funcionalidade | Arquivos principais | Models | Complexidade | Observações |
|---|---|---|---|---|
| Autenticação e papéis | `decorators.py`, `context_processors.py`, `base.html` | `User`, `Group`, `Terapeuta` | Alta | Regras duplicadas e inconsistentes |
| Pacientes | `views.py`, `forms.py`, templates de paciente | `Paciente`, `Convenio` | Média | GET da lista pode escrever no banco |
| Agenda operacional | `views.py`, `forms.py`, `utils.py`, `lista_agendamentos.html` | `Agendamento` | Muito alta | Centro do sistema e maior concentração de regras |
| Agenda fixa | `utils.py`, views e templates de grade | `AgendaFixa`, `Agendamento` | Muito alta | Materialização pode divergir da regra |
| Prontuário | `realizar_consulta`, templates clínicos | `Consulta`, `AnexoConsulta` | Alta/crítica | Dados sensíveis e falha de autorização |
| Reposição/faltas | Views e forms correspondentes | `Agendamento` | Alta | Sem relação explícita entre origem e reposição |
| Equipe | Views, form de cadastro, decorators | `User`, `Group`, `Terapeuta` | Alta | Grupo, booleano e `is_staff` podem divergir |
| Salas | Views/templates de ocupação | `Sala`, `BloqueioSala`, `Agendamento` | Alta | Bloqueio é apenas visual |
| Relatórios | Seis views e templates | Principalmente `Agendamento` | Alta | Conceitos e filtros não uniformes |
| Importação/admin | `admin.py`, comando CSV | Vários | Média | Operações em massa pouco protegidas |

## 13. Pontos que preciso que você esclareça

1. Um terapeuta deve ver todo o histórico multidisciplinar do paciente ou somente suas próprias evoluções?
2. O dono deve acessar prontuários de toda a clínica?
3. Coordenação deve atuar por especialidade, por equipe inteira ou somente sobre os próprios atendimentos?
4. O status `CONFIRMADO` foi realmente abolido?
5. Qual é a duração padrão correta: 45 ou 60 minutos?
6. Uma sala admite vários terapeutas apenas quando atendem conjuntamente o mesmo paciente?
7. Bloqueios de sala e terapeuta devem impedir o salvamento ou apenas sinalizar visualmente?
8. Todo atendimento avulso realizado é uma reposição, ou reposição precisa ser um conceito próprio?
9. “Financeiro” deverá representar só produção/quantidade ou também valores, pagamentos, convênios e repasses?
10. Ao alterar paciente, modalidade ou vigência de uma agenda fixa, quais ocorrências futuras devem ser reescritas?
11. O vídeo versionado é dado clínico real e deve permanecer no histórico?
12. As credenciais existentes no antigo `.env` foram rotacionadas após sua remoção?
13. Como estão configurados no PythonAnywhere: `/media/`, HTTPS, backups, logs e restauração?
14. A simulação editável da grade em `localStorage` ainda é necessária?

Esta auditoria documenta o estado atual; não contém proposta de arquitetura definitiva nem plano de V2.
