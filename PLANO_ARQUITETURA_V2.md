# Plano de Arquitetura Técnica — Sistema V2

## 0. Estado consolidado da implementação

| Etapa | Estado | Entregas consolidadas |
|---|---|---|
| 0 — Fundação | **Concluída** | Projeto/repositório e banco MySQL independentes, settings por ambiente, segredos externos, testes, Ruff, CI, templates/static e armazenamento privado preparado |
| 1 — Identidade, autorização e auditoria | **Concluída** | `User` próprio, quatro papéis, grupos Django, provisionamento idempotente, `Policy`/`PolicyContext`, deny-by-default, `AuditEvent` e matriz-base |
| 2 — Equipe e pacientes | **Concluída** | 2.1 `Specialty`, `Professional`, `ProfessionalSpecialty`; 2.2 `Patient`; 2.3 `PatientProfessionalLink`; 2.4 selectors e policy cadastral de paciente |
| 3 — Núcleo da agenda | **Próxima** | Ainda não implementada |
| 4 a 10 | **Pendentes** | Permanecem planejadas conforme a ordem deste documento |

Na consolidação ao fim da Etapa 2, existem 133 testes aprovados e migrations aplicadas até `patients.0002_patientprofessionallink`. Concluir uma etapa não apaga requisitos adiados: cobertura, consentimento, escopo de Coordenação e outras pendências continuam registrados nas seções correspondentes e devem ser implementados antes de seus consumidores.

## 1. Diretriz arquitetural e estratégia de reconstrução

### 1.1. Decisão recomendada

A recomendação é reconstruir a V2 como um **novo projeto Django separado**, em um repositório e banco de dados próprios, mantendo o sistema atual em produção até a migração final.

A V2 deve ser um **monólito modular**: uma única aplicação implantável, organizada em aplicativos Django com limites de domínio explícitos. Essa abordagem preserva a simplicidade operacional necessária ao tamanho atual da equipe e da instalação, sem repetir o acoplamento do sistema legado.

O sistema atual não deve ser transformado gradualmente na V2. Ele deve permanecer estável, receber apenas correções críticas independentes e servir como fonte de dados para ensaios de migração.

### 1.2. Comparação das alternativas

| Alternativa | Vantagens | Desvantagens e riscos | Avaliação |
|---|---|---|---|
| **A. Novo projeto Django separado** | Permite modelagem coerente desde o início; novo modelo de usuário; MySQL desde a fundação; regras de acesso seguras; migração ensaiável; rollback simples; nenhuma interferência no legado durante a construção | Exige migração de dados e operação temporária de dois ambientes; funcionalidades precisam ser reconstruídas | **Recomendada** |
| **B. Evolução gradual do projeto atual** | Reaproveita telas e modelos existentes; aparenta reduzir o esforço inicial | Mantém dívida estrutural, permissões dispersas, modelo de agenda inadequado, histórico de migrações complexo e risco de regressão em produção; dificulta trocar o usuário e o banco | **Não recomendada** |
| **C. Novos aplicativos V2 dentro do projeto atual** | Permite algum isolamento e reaproveita a implantação existente | V1 e V2 continuam compartilhando configurações, usuário, banco, URLs, mídia e riscos operacionais; fronteiras tendem a se degradar; o corte final fica ambíguo | **Não recomendada** |

### 1.3. Princípios da reconstrução

- A especificação da V2 é a fonte de verdade; comportamentos legados só são preservados quando não a contradizem.
- O legado permanece operacional durante o desenvolvimento.
- Não haverá gravação simultânea automática nos dois sistemas.
- A importação será feita por processo ETL idempotente e repetível.
- O corte definitivo ocorrerá em janela controlada, com o legado temporariamente bloqueado para escrita.
- Após o corte, o legado ficará disponível em modo somente leitura pelo período necessário para conferência e contingência.
- Correções críticas de segurança no legado formam uma frente separada e não alteram a arquitetura da V2.

## 2. Organização por aplicativos e domínios

### 2.1. Aplicativos Django propostos

| Aplicativo | Responsabilidade principal |
|---|---|
| `accounts` | Usuários, autenticação, grupos, papéis, políticas globais e eventos de acesso |
| `staff` | Profissionais, especialidades, vínculos profissionais e atribuições de coordenação |
| `patients` | Cadastro do paciente, situação, convênios, autorizações, consentimentos e vínculos assistenciais |
| `scheduling` | Agenda, salas, participantes, recorrências, bloqueios, estados, faltas, cancelamentos, substituições e sugestões |
| `medical_records` | Prontuário, evoluções, revisões e anexos clínicos protegidos |
| `reports` | Relatórios operacionais, aniversariantes, indicadores e simulações não oficiais |
| `audit` | Trilha de auditoria imutável para ações sensíveis e decisões operacionais |

Além deles:

- `common`: tipos, validadores e utilidades realmente compartilhados, sem regras de domínio.
- `legacy_import`: comandos e adaptadores de importação do banco e dos arquivos legados; não participa das requisições normais da aplicação.
- `config`: configurações Django, URLs de projeto, ASGI/WSGI e composição de ambientes.

### 2.2. Estrutura interna dos aplicativos

Cada domínio deve manter uma organização previsível:

- `models.py` ou pacote `models/`: persistência e invariantes locais.
- `forms.py`: validação e apresentação de entrada.
- `services.py` ou pacote `services/`: casos de uso que alteram estado.
- `selectors.py`: consultas reutilizáveis e escopadas.
- `policies.py`: autorização por objeto e por operação.
- `views.py` e `urls.py`: camada HTTP fina.
- `tests/`: testes unitários, de política, integração e interface.

As views não devem concentrar regras de negócio. Formulários não devem executar fluxos inteiros. Signals não devem ser usados para esconder efeitos centrais de negócio; são aceitáveis apenas para efeitos técnicos simples e desacoplados.

## 3. Modelo conceitual de dados

### 3.1. Identidade, papéis e auditoria

#### `User`

Um modelo próprio baseado em `AbstractUser` existe desde a primeira migração da V2. Isso evita a limitação estrutural de trocar o modelo de usuário após o sistema entrar em produção.

Campos conceituais adicionais continuam sujeitos à necessidade concreta antes de ampliar o modelo:

- nome de exibição;
- situação ativa/inativa;
- marcadores de segurança relevantes;
- datas de criação e atualização.

Os quatro papéis implementados são `OWNER`, `ADMINISTRATIVE`, `COORDINATION` e `THERAPIST`. Eles usam `Group` e `Permission` nativos do Django, com nomes centralizados e provisionamento idempotente. Um usuário pode pertencer a vários grupos, acumulando as capacidades dos respectivos papéis. O papel fornece autorização ampla; o acesso a objetos depende também do escopo de dados e das restrições da operação.

`Policy` e `PolicyContext` estão implementados com deny-by-default. Não existe bypass global de `OWNER` ou superusuário nessa camada: cada domínio concede operações explicitamente. O acúmulo de papéis nunca poderá autorizar editar evolução criada por outro profissional.

#### `AuditEvent`

A infraestrutura append-oriented está implementada com:

- data/hora de ocorrência;
- ator opcional e identificador preservado do ator;
- ação;
- tipo e identificador do recurso;
- `metadata` explícita, sem inclusão automática de dados sensíveis.

O service de registro valida entradas e insere novos eventos; as permissões padrão do modelo não incluem alteração ou exclusão. Contexto de requisição, valores anteriores/posteriores e justificativa devem ser adicionados conscientemente pelos futuros casos de uso quando necessários, sem duplicar conteúdo clínico. Selectors e checks de policy não produzem auditoria por serem operações de leitura.

Eventos de auditoria devem cobrir ao menos acesso/download de arquivo clínico, alterações de agenda, transições excepcionais, sobreposição autorizada, alterações de vínculo, evoluções, consentimentos, importações e ações administrativas sensíveis.

### 3.2. Equipe, especialidades e coordenação

#### `Specialty`

Implementado. Representa a área ou especialidade assistencial, com código estável e único, nome único e situação ativa/inativa.

#### `Professional`

Implementado com nome, registro profissional opcional, situação ativa/inativa e relação opcional 0..1 com `User`. Um usuário sem perfil profissional continua válido, e nenhum `Professional` é criado automaticamente. Forma de contratação/pagamento e atributos operacionais adicionais continuam pendentes de requisito específico.

A regra operacional de `Professional.is_active` ainda não foi definida e não deve ser inferida silenciosamente por selectors ou services futuros.

#### `ProfessionalSpecialty`

Implementado. Relação muitos-para-muitos entre profissional e especialidade, permitindo várias especialidades por profissional e preservando vigência com `starts_on` e `ends_on`. O mesmo par pode possuir períodos históricos distintos, mas não duplica a mesma data inicial.

#### `CoordinationAssignment`

Ainda não implementado. Deverá associar um usuário coordenador a uma especialidade/área por período de vigência e servir como fonte do escopo da Coordenação, não apenas como rótulo de interface. Enquanto essa modelagem não existir, operações de paciente que dependam desse escopo permanecem deny-by-default para `COORDINATION`.

### 3.3. Pacientes, convênios e vínculos assistenciais

#### `Patient`

Implementado como entidade cadastral central, com:

- chave primária interna estável (`BigAutoField`);
- `name` obrigatório;
- `cpf` opcional e não único, com validação de forma de 11 dígitos;
- `birth_date` opcional;
- `phone` opcional e não único;
- `default_service_type`, preservando `PARTICULAR`, `DESCONTO`, `CONVENIO` e `SOCIAL`;
- `is_active`;
- `created_at` e `updated_at`.

Paciente não deve ser apagado durante a operação normal; a inativação preserva dados e referências históricas. Responsáveis ainda não foram especificados. O campo derivado `nome_search` da V1 não foi copiado; a estratégia de busca sem acentos permanece pendente.

`Patient` não possui `biometric_status`. A ideia anterior de um estado permanente do paciente foi substituída pela regra de biometria por atendimento descrita na seção de agenda.

#### `InsuranceProvider` e `PatientCoverage`

Ainda não implementados. O convênio deve ser uma entidade própria. O vínculo do paciente com o convênio deve permitir número da carteira, vigência, situação e dados usados para autorizações. Os campos legados de convênio e carteirinha não foram achatados em `Patient` e deverão ser preservados por essa modelagem durante a migração.

#### `PatientProfessionalLink`

Implementado no app `patients` com `patient`, `professional` e `established_at`. Uma constraint garante um único vínculo por par paciente/profissional. Ambos os relacionamentos usam `PROTECT`, evitando que exclusões físicas destruam silenciosamente o histórico. O service `ensure_patient_professional_link` é idempotente e retorna o vínculo com a indicação de criação ou reutilização.

O gatilho de agenda ainda não está implementado. Quando um atendimento passar para `COMPLETED`, deverá garantir o vínculo para cada profissional que realmente participou, inclusive em atendimento conjunto. `WAITING`, `MISSED`, `CANCELLED` e o simples agendamento não criam vínculo. A Administração não precisa cadastrá-lo manualmente no fluxo normal.

O vínculo permanece operacional enquanto o paciente estiver ativo. Fim de agenda fixa, troca de agenda ou tempo sem atendimento não o encerram. Quando o paciente se torna inativo, sai das telas operacionais normais do terapeuta, mas o vínculo e todo o histórico permanecem preservados para os acessos históricos autorizados.

Origem/auditoria da criação, eventual encerramento ou revogação e a necessidade de registrar especialidade no contexto do atendimento ou do vínculo permanecem em aberto.

#### `PatientConsent`

Ainda não implementado. Deverá representar consentimento/negação versionado e escopado, com:

- finalidade ou categoria;
- status;
- data da decisão;
- responsável pela decisão;
- vigência ou revogação;
- documento comprobatório, quando aplicável.

A autorização de imagem não deve ser apenas texto informativo: as operações abrangidas devem consultar o consentimento vigente.

Consentimento para uso externo de imagem não equivale à autorização interna de acesso a anexos clínicos. O segundo continuará sujeito à policy do prontuário e do arquivo protegido.

### 3.4. Agenda, salas e atendimento conjunto

#### `Room`

Ainda não implementado. Será o cadastro de salas com nome/código estável, situação e atributos operacionais. A Sala 8A deve ser cadastrada na V2 como dado de referência.

#### `Appointment`

Ainda não implementado. Representará um atendimento único, com:

- paciente;
- sala;
- início e fim;
- duração prevista;
- estado;
- origem de criação (`FIXED`, `AD_HOC`, `IMPORT` ou equivalente), sem usar reposição como estado ou tipo substitutivo do atendimento;
- regra recorrente de origem, quando houver;
- observações operacionais restritas;
- autor e datas de criação/alteração.

Um atendimento conjunto é **um único `Appointment`**, com um paciente, uma sala e vários profissionais. Não deve ser representado por consultas duplicadas que apenas coincidem em horário.

Para cobertura Unimed aplicável, a biometria deverá ser exigida na entrada e na saída de cada atendimento. A cobertura vigente determinará a obrigatoriedade, e o atendimento registrará separadamente os dois momentos. Isso não é estado permanente de `Patient`, e nenhum molde facial ou outro dado biométrico foi modelado. O desenho exato dos registros, exceções e auditoria será fechado com `PatientCoverage` e `Appointment`.

#### `AppointmentParticipant`

Ainda não implementado. Relacionará profissionais ao atendimento. Pode registrar papel no atendimento, especialidade aplicada e presença, se necessário. A combinação atendimento/profissional deve ser única.

#### `AppointmentStatusEvent`

Ainda não implementado.

Histórico imutável de mudança de estado, com estado anterior, novo estado, usuário, data, motivo e metadados da operação.

#### `Cancellation` e `Absence`

Ainda não implementados.

Cancelamento e falta devem ser eventos explícitos, vinculados ao atendimento. A ausência deve identificar quem faltou — paciente ou terapeuta — e o motivo quando conhecido. Isso evita perder semântica ao guardar tudo em um único status ou texto livre.

#### `RecurringSchedule` e `RecurringScheduleParticipant`

Ainda não implementados.

Definem agenda fixa, periodicidade, dias/horários, sala, paciente, participantes, vigência e versão. Alterações geram nova versão com data efetiva; o passado nunca é reescrito.

Ocorrências devem ser materializadas até 31 de dezembro do ano operacional definido. O processo precisa ser idempotente e expor todos os conflitos encontrados.

#### `ScheduleBlock`

Ainda não implementado.

Bloqueio de profissional ou sala, com intervalo, motivo, origem e vigência. A existência de bloqueio produz alerta. Quando a política permitir prosseguir, a decisão exige justificativa e auditoria explícitas.

#### Presença operacional futura

`PatientCheckIn` não é necessário para a fundação da V2. Se uma etapa futura de sugestões exigir presença em tempo real, a forma de registrar presença, horário e origem será definida nessa etapa, sem ser inferida apenas do estado do atendimento.

### 3.5. Substituição e sugestões

#### `ReplacementCase`

Ainda não implementado.

Representa a necessidade de substituição aberta a partir de um atendimento fonte cancelado, inviabilizado ou ausente. Deve guardar motivo, estado, responsável e vínculo explícito com a origem.

#### `ReplacementAttempt`

Ainda não implementado.

Registra cada convite/decisão, paciente candidato, atendimento alvo criado, posição/racional da sugestão, aceite ou recusa, responsável e datas.

O atendimento realizado como substituição deve apontar explicitamente para o caso e, portanto, para o atendimento de origem. Não se deve inferir substituição a partir de dois registros semelhantes.

Reposição não é status de `Appointment`. O atendimento resultante usa a máquina de estados normal e poderá ficar `COMPLETED`, `MISSED` ou `CANCELLED` como qualquer outro atendimento.

### 3.6. Prontuário, evoluções e anexos

#### `MedicalRecord`

Ainda não implementado.

Um prontuário por paciente, com situação e metadados. Sua existência separa o agregado clínico do cadastro operacional.

#### `Evolution`

Ainda não implementada.

Evolução vinculada a paciente, atendimento e autor, contendo:

- especialidade do autor no momento do registro;
- conteúdo clínico;
- data de criação;
- data da última alteração;
- situação, sem exclusão física ordinária.

#### `EvolutionRevision`

Ainda não implementada.

Cada alteração autorizada gera uma revisão imutável com conteúdo anterior, autor da alteração, data e motivo quando aplicável. O autor original continua identificável.

#### `ClinicalAttachment`

Ainda não implementado.

Arquivo protegido associado ao prontuário, evolução ou categoria clínica, com:

- chave física não previsível;
- nome original apenas como metadado;
- tipo MIME detectado e permitido;
- tamanho;
- hash de integridade;
- responsável pelo envio;
- data;
- situação e metadados de retenção.

O arquivo físico não deve estar versionado no Git nem ser servido por uma URL pública direta.

### 3.7. Restrições e consistência

O banco deve reforçar invariantes que não podem depender apenas da interface:

- fim posterior ao início;
- duração permitida de 30 ou 45 minutos quando aplicável;
- unicidade de prontuário por paciente;
- unicidade de participante por atendimento;
- integridade dos vínculos de origem e substituição;
- exclusão de sobreposição de sala para atendimentos de pacientes diferentes;
- preservação de estados e históricos.

No MySQL, que não oferece equivalente direto ao `ExclusionConstraint` de intervalos do PostgreSQL,
a ocupação de sala e os conflitos de profissional devem ser validados pelo serviço de agenda em
`transaction.atomic()`. O serviço deverá bloquear com `select_for_update()` linhas estáveis dos
recursos envolvidos antes de consultar sobreposições e gravar. O algoritmo exato será fechado
antes da implementação da agenda e comprovado por testes de concorrência no MySQL real.

O atendimento conjunto não entra em conflito consigo mesmo porque utiliza um único `Appointment`
com vários participantes. Invariantes simples continuam reforçadas por constraints do banco
sempre que o MySQL as suportar.

## 4. Autorização e permissões centralizadas

### 4.1. Regra geral

A autorização deve combinar:

1. papel e permissão ampla;
2. escopo de objetos acessíveis;
3. operação pretendida;
4. estado atual do objeto.

O padrão é negar. Ocultar um botão não constitui autorização.

Quando o usuário acumula papéis, as capacidades se somam. Restrições específicas da operação continuam válidas: em particular, nenhum papel permite editar evolução escrita por outro profissional. Um Proprietário que também seja Terapeuta pode criar e editar somente suas próprias evoluções conforme o papel de Terapeuta.

### 4.2. Políticas e escopos

O app `patients` implementa:

- `professional_for_user(user)`, que resolve somente a relação explícita e não cria perfil automaticamente;
- `operational_patients_for_professional(professional)`, que retorna sem duplicatas apenas pacientes ativos com vínculo assistencial;
- uma policy específica com `patient.view`, `patient.create`, `patient.update` e `patient.inactivate`.

Usuário `THERAPIST` sem `Professional` recebe deny. Paciente inativo não integra o escopo operacional normal do terapeuta, mas seu vínculo permanece armazenado. A policy expressa capacidade cadastral; CRUD, views e services de criação/atualização/inativação ainda não foram implementados. Não existe `patient.delete` como operação normal.

Cada domínio futuro deverá manter policies e seletores próprios, por exemplo:

- `appointment_scope_for(user)`;
- `evolution_scope_for(user)`;
- `can_change_appointment(user, appointment)`;
- `can_create_evolution(user, appointment)`;
- `can_download_attachment(user, attachment)`.

Listagens, buscas, exportações e acesso por identificador devem partir do mesmo queryset escopado. Assim, uma URL direta não contorna o filtro da tela.

### 4.3. Matriz de acesso inicial

| Papel | `Patient` cadastral implementado | Capacidades futuras preservadas |
|---|---|---|
| `OWNER` | `view`, `create`, `update` e `inactivate`, inclusive leitura de inativos, sem depender de vínculo | Administração e leitura ampla por policies explícitas; nunca edita evolução alheia |
| `ADMINISTRATIVE` | `view`, `create`, `update` e `inactivate`, inclusive leitura de inativos, sem depender de vínculo | Agenda e operação cadastral; sem prontuários, evoluções ou anexos clínicos |
| `COORDINATION` | Deny-by-default enquanto não houver fonte confiável do escopo | Leitura limitada às especialidades/equipes coordenadas; sem alteração de agenda por esse papel |
| `THERAPIST` | Somente `view` de paciente ativo vinculado ao seu `Professional`; sem perfil, sem vínculo ou paciente inativo resulta em deny | Própria agenda em leitura; prontuário/histórico dos pacientes no escopo; criação e edição apenas das próprias evoluções |

Os papéis da tabela não são mutuamente exclusivos. Um usuário recebe a união das capacidades de seus papéis, sem eliminar limites de autoria ou escopo aplicáveis à operação.

O vínculo assistencial não concede acesso clínico genérico. Policies de prontuário, evolução e anexos deverão ser implementadas separadamente. Não existe bypass global de `OWNER` na infraestrutura de `Policy`.

O Django Admin não deve ser uma rota alternativa capaz de ignorar essas regras. Modelos clínicos e de agenda sensíveis devem ter administração restrita ou interfaces operacionais próprias que chamem os mesmos serviços e políticas.

Não é recomendável introduzir `django-guardian` inicialmente. Grupos resolvem permissões amplas; queries por vínculo e coordenação resolvem o escopo. Uma biblioteca de permissão por objeto só deve ser adicionada se surgirem exceções individuais numerosas que o modelo de domínio não represente bem.

## 5. Camada de regras de negócio

### 5.1. Serviços de aplicação

Toda alteração relevante deve ocorrer por um caso de uso nomeado, como:

- `schedule_appointment`;
- `reschedule_appointment`;
- `transition_appointment_status`;
- `create_recurring_schedule`;
- `revise_recurring_schedule`;
- `materialize_recurring_occurrences`;
- `register_absence`;
- `open_replacement_case`;
- `register_replacement_outcome`;
- `record_evolution`;
- `revise_evolution`;
- `store_clinical_attachment`.

Esses serviços recebem o ator, validam autorização, executam invariantes, persistem tudo em `transaction.atomic()` e produzem auditoria. Views e comandos chamam os mesmos serviços.

### 5.2. Consultas

Leituras complexas devem ficar em seletores. Isso permite otimizar agenda semanal, prontuário, relatórios e sugestões sem misturar consultas com transações.

### 5.3. Concorrência

Operações de agenda exigem proteção contra duas gravações simultâneas que passam pela mesma validação. O desenho deve combinar:

- transações;
- bloqueio pessimista quando adequado;
- constraints suportadas pelo MySQL/InnoDB;
- tratamento legível de violações de integridade.

## 6. Agenda, estados e regras operacionais

### 6.1. Estados oficiais

Os estados oficiais são:

- `WAITING` — aguardando;
- `COMPLETED` — realizado;
- `MISSED` — não realizado por ausência;
- `CANCELLED` — cancelado.

Não existe estado nem etapa de confirmação manual na V2.

### 6.2. Máquina de estados inicial

Fluxo normal:

- `WAITING` → `COMPLETED`;
- `WAITING` → `MISSED`;
- `WAITING` → `CANCELLED`.

Estados terminais não devem ser alterados silenciosamente. Correções excepcionais exigem permissão específica, justificativa e evento de auditoria, preservando o evento anterior.

### 6.3. Regras de conflito

- Uma sala não pode atender pacientes diferentes em intervalos sobrepostos.
- Vários terapeutas podem atender conjuntamente o mesmo paciente, na mesma sala, por meio de um único atendimento.
- Um profissional não pode participar de atendimentos sobrepostos.
- A possibilidade de um paciente ter atendimentos simultâneos em salas diferentes precisa ser decidida; até lá, a implementação deve assumir que isso é conflito.
- Bloqueios de sala ou profissional geram alerta. Se a operação puder sobrepor, deverá haver permissão, justificativa e auditoria.
- Conflitos de recorrência nunca devem ser descartados silenciosamente.

### 6.4. Agenda fixa

A agenda fixa deve ser versionada:

1. cria-se uma regra com vigência definida;
2. o materializador cria as ocorrências futuras até 31 de dezembro;
3. uma alteração fecha a vigência da versão anterior e cria outra;
4. ocorrências passadas permanecem intocadas;
5. ocorrências futuras afetadas são mostradas em uma prévia explícita;
6. conflitos são apresentados individualmente para decisão humana.

O materializador precisa ser idempotente: executar novamente não duplica ocorrências. Deve operar também aos sábados.

### 6.5. Duração

Os atendimentos regulares devem suportar durações de 45 minutos e 30 minutos conforme a regra aprovada. A origem da duração — tipo de atendimento, especialidade ou escolha operacional — deve ser explicitada antes da implementação para evitar regras escondidas.

## 7. Substituições e motor de sugestões

### 7.1. Registro explícito

Substituição é um processo de negócio, não uma inferência de relatório. O sistema deve guardar:

- atendimento que abriu a vaga;
- motivo;
- candidatos apresentados;
- ordem e justificativas da sugestão;
- contatos/tentativas;
- decisão humana;
- atendimento efetivamente criado ou alterado;
- responsável por cada ação.

### 7.2. Sugestão determinística futura

O motor de sugestões é uma evolução posterior e não bloqueia a fundação da V2. Quando implementado, deve ser uma função determinística e testável. Ele não decide nem altera a agenda sozinho.

Primeiro aplica filtros obrigatórios:

- paciente ativo e elegível;
- presença confirmada quando essa informação for exigida;
- compatibilidade de profissional/especialidade;
- disponibilidade de profissional;
- disponibilidade de sala;
- ausência de outro conflito de paciente;
- autorização de convênio/Unimed válida quando necessária.

Depois ordena os candidatos por critérios visíveis, como:

- paciente já presente na clínica;
- possibilidade de antecipação;
- compatibilidade de profissionais e sala;
- prioridade configurável para profissional diarista;
- urgência ou tempo de espera, se aprovado;
- restrições de autorização.

O resultado deve explicar por que cada candidato foi incluído, excluído ou posicionado. A definição de presença, os detalhes de autorização da Unimed/convênio e os pesos do ranking serão decididos nessa etapa futura. Não devem gerar modelos ou mecanismos antecipados na fundação.

## 8. Prontuário e arquivos clínicos seguros

### 8.1. Prontuário e evoluções

- Registros clínicos não são excluídos na operação comum.
- O terapeuta cria e altera somente sua própria evolução.
- O Proprietário pode visualizar prontuários e evoluções de toda a clínica, mas não editar evolução alheia; se também for Terapeuta, cria e edita apenas as próprias evoluções.
- Toda alteração gera revisão histórica.
- Coordenação lê apenas o escopo de suas áreas.
- Administrativo não vê conteúdo, anexos, trechos, indicadores ou metadados que revelem informação clínica.
- O acesso multidisciplinar do terapeuta depende do vínculo assistencial real com o paciente.

### 8.2. Armazenamento privado

Anexos devem usar diretório privado fora da raiz pública de mídia, ou armazenamento de objetos com bucket privado. O navegador nunca recebe um caminho permanente público.

O download ocorre por endpoint autenticado que:

1. localiza o anexo por identificador não previsível;
2. aplica a política de acesso ao paciente/prontuário;
3. registra auditoria;
4. entrega o arquivo por streaming ou gera URL assinada de curtíssima duração.

### 8.3. Upload

O upload deve validar extensão, tipo MIME real, tamanho, nome, categoria e integridade. Nomes fornecidos pelo usuário não devem definir o caminho físico. Antivírus pode ser incorporado conforme infraestrutura disponível e risco dos formatos aceitos.

Arquivos de paciente, backups, exportações e `.env` não podem entrar no Git.

## 9. Estratégia de frontend

A recomendação é manter o frontend server-rendered com:

- Django Templates;
- Bootstrap;
- JavaScript modular e pequeno;
- formulários POST seguidos de redirect;
- endpoints JSON restritos para interações que realmente exigem atualização assíncrona.

React, Vue ou uma SPA não se justificam nesta fase: aumentariam implantação, autenticação, autorização duplicada, testes e manutenção sem benefício proporcional ao fluxo administrativo.

HTMX pode ser avaliado posteriormente para trechos como busca de pacientes, agenda e sugestões, mas não é dependência arquitetural inicial.

Regras importantes:

- componentes repetidos em `includes`/partials;
- CSS e JavaScript em arquivos estáticos, não espalhados em templates;
- nenhuma regra de segurança confiada ao navegador;
- acessibilidade e responsividade consideradas desde os primeiros fluxos;
- mensagens claras para conflito, bloqueio, estado e falta de autorização.

## 10. Banco de dados e implantação

### 10.1. Banco recomendado

MySQL 8.0.11 ou superior deve ser usado em desenvolvimento, testes de integração, integração
contínua, homologação e produção. A configuração deve usar InnoDB, `utf8mb4`, modo estrito e
isolamento `read committed`.

SQLite não é adequado como banco de produção da V2 porque a agenda precisa de concorrência real,
transações robustas e comportamento próximo ao ambiente produtivo. Mantê-lo nos testes também
esconderia diferenças importantes. O SQLite existente continua exclusivo da V1.

### 10.2. PythonAnywhere

A conta paga atual do PythonAnywhere já disponibiliza MySQL. A implantação deve usar banco e
usuário de aplicação próprios da V2, sem reutilizar o SQLite ou credenciais da V1, conforme a
documentação oficial: [MySQL no PythonAnywhere](https://help.pythonanywhere.com/pages/UsingMySQL/).

Antes de fechar a implantação, é necessário confirmar:

- versão do MySQL e recursos disponíveis no plano atual;
- limites de armazenamento e conexões;
- disponibilidade e retenção de backups;
- espaço para anexos privados;
- execução de tarefas agendadas para materialização, manutenção e backups;
- estratégia de restauração testada;
- uso de serviço externo de objetos, caso o volume de anexos justifique.

### 10.3. Ambientes

Devem existir configurações separadas para desenvolvimento, teste, homologação e produção, com segredos exclusivamente por variáveis de ambiente. Produção deve habilitar HTTPS, cookies seguros, cabeçalhos de segurança, hosts restritos e logs sem conteúdo clínico.

## 11. Estratégia de testes

Ao fim da Etapa 2, 133 testes estão aprovados, cobrindo a fundação, papéis, infraestrutura deny-by-default, auditoria-base, equipe, paciente, vínculo assistencial, selectors e policy cadastral de paciente. Os cenários dependentes das Etapas 3 a 10 continuam requisitos de teste futuros.

### 11.1. Pirâmide de testes

- **Unitários:** máquina de estados, validações, políticas e regras de recorrência; ranking de sugestões quando essa fase for implementada.
- **Integração:** serviços com MySQL, transações, constraints, autorização por queryset e arquivos protegidos.
- **Interface:** principais formulários, respostas HTTP e visibilidade por papel.
- **Concorrência:** duas marcações simultâneas de sala/profissional e operações de substituição concorrentes.
- **Migração:** importação repetida, reconciliação, preservação de IDs legados e arquivos.
- **Ponta a ponta seletivos:** fluxos críticos, sem transformar todos os cenários em testes lentos de navegador.

### 11.2. Cenários mínimos

Os testes devem cobrir, no mínimo:

- matriz completa dos quatro papéis;
- acúmulo de papéis sem ampliação indevida da edição de evoluções;
- tentativa por URL direta e por identificador de objeto fora do escopo;
- Administrativo sem acesso a qualquer conteúdo clínico;
- Coordenação limitada às áreas atribuídas;
- Terapeuta limitado à própria agenda e a pacientes vinculados;
- edição de evolução apenas pelo autor autorizado;
- Proprietário com leitura clínica global sem edição de evolução alheia;
- criação automática e idempotente do vínculo ao realizar o primeiro atendimento, incluindo todos os participantes de atendimento conjunto;
- permanência do vínculo durante a situação ativa e preservação histórica após inativação do paciente;
- atendimento conjunto sem falso conflito de sala;
- conflito de pacientes diferentes na mesma sala;
- conflito de profissional;
- alerta e sobreposição auditada de bloqueio;
- durações de 30 e 45 minutos;
- sábados;
- materialização até 31 de dezembro e idempotência;
- conflito de recorrência visível;
- transições de `WAITING` diretamente para `COMPLETED`, `MISSED` ou `CANCELLED`, sem estado de confirmação;
- cancelamento, falta de paciente e falta de terapeuta;
- substituição com origem e destino explícitos, sem ser status do atendimento;
- download protegido, upload inválido e tentativa de enumeração;
- inativação sem perda histórica;
- importação de dados órfãos ou inconsistentes com relatório de exceções;
- backup e restauração em ensaio operacional.

Os testes de integração devem executar no MySQL real da CI, não em SQLite.

## 12. Estratégia de migração do legado

### 12.1. Princípios

- Banco novo e vazio para a V2.
- Legado tratado como fonte somente leitura durante cada execução.
- ETL idempotente, versionado e auditável.
- Tabela de mapeamento entre tipo/ID legado e tipo/ID V2.
- Lotes de importação identificáveis e reversíveis no banco de destino antes do corte.
- Nenhuma correção silenciosa de dados ambíguos.

### 12.2. Ordem de importação

1. usuários e papéis;
2. especialidades e profissionais;
3. atribuições de coordenação;
4. pacientes e responsáveis;
5. convênios e autorizações disponíveis;
6. vínculos assistenciais recuperáveis;
7. salas e bloqueios;
8. regras de agenda fixa;
9. atendimentos e participantes;
10. faltas, cancelamentos e históricos de status;
11. prontuários e evoluções;
12. anexos, com hash e relatório de arquivos ausentes;
13. substituições somente quando a relação puder ser comprovada;
14. dados auxiliares de relatórios.

Registros coincidentes não devem ser automaticamente convertidos em atendimento conjunto ou substituição. Casos ambíguos entram em relatório para decisão ou são importados com marcação de procedência e sem semântica inventada.

### 12.3. Ensaios e validação

Devem ocorrer múltiplos ensaios completos em cópia recente do legado. Cada ensaio produz:

- contagem por tabela e por estado;
- mapeamentos ausentes;
- órfãos e duplicidades;
- conflitos de agenda encontrados;
- arquivos presentes, ausentes e hashes divergentes;
- amostras de prontuários conferidas por responsável autorizado;
- comparação de relatórios-chave;
- tempo total e espaço utilizado.

Como o legado não possui um `updated_at` confiável em todas as entidades, uma importação incremental genérica é arriscada. A estratégia preferencial é ensaiar importações completas e realizar a carga final durante uma janela em que o legado esteja bloqueado para novas escritas.

### 12.4. Corte e contingência

1. comunicar e iniciar a janela;
2. bloquear escrita no legado;
3. gerar backup verificável;
4. executar a importação final;
5. executar reconciliações automáticas e amostrais;
6. obter aceite operacional;
7. liberar a V2;
8. manter o legado somente leitura;
9. acompanhar erros e métricas do período inicial.

O plano de rollback deve definir o ponto até o qual é possível retornar ao legado sem reconciliar novas gravações. Após liberar escrita na V2, um retorno não pode ser improvisado.

## 13. Estrutura inicial de diretórios

```text
clinica_estima_v2/
├── manage.py
├── pyproject.toml
├── README.md
├── .env.example
├── config/
│   ├── __init__.py
│   ├── urls.py
│   ├── asgi.py
│   ├── wsgi.py
│   └── settings/
│       ├── __init__.py
│       ├── base.py
│       ├── development.py
│       ├── test.py
│       ├── homologation.py
│       └── production.py
├── apps/
│   ├── accounts/
│   ├── staff/
│   ├── patients/
│   ├── scheduling/
│   │   ├── models/
│   │   ├── services/
│   │   ├── selectors.py
│   │   ├── policies.py
│   │   ├── forms.py
│   │   ├── views.py
│   │   ├── urls.py
│   │   └── tests/
│   ├── medical_records/
│   ├── reports/
│   ├── audit/
│   ├── common/
│   └── legacy_import/
│       ├── adapters/
│       ├── management/commands/
│       ├── mappings/
│       └── tests/
├── templates/
│   ├── base.html
│   ├── includes/
│   └── registration/
├── static/
│   ├── css/
│   ├── js/
│   └── img/
├── private_media/
│   └── .gitkeep
├── docs/
│   ├── decisions/
│   ├── operations/
│   └── migration/
└── tests/
    ├── integration/
    └── e2e/
```

`private_media` representa apenas a interface local de desenvolvimento. Em produção, a localização real deve vir da configuração e nunca ser publicada diretamente pelo servidor web.

## 14. Ordem recomendada de implementação

### Etapa 0 — Fundação — concluída

- projeto separado;
- MySQL em desenvolvimento e CI;
- configurações por ambiente;
- lint, formatação, testes e pipeline;
- política de segredos, logs e backups;
- registros de decisão arquitetural.

### Etapa 1 — Identidade, autorização e auditoria — concluída

- modelo `User` próprio;
- grupos e permissões;
- políticas e escopos-base;
- eventos de auditoria;
- testes da matriz de acesso.

### Etapa 2 — Equipe e pacientes — concluída

- **2.1:** `Specialty`, `Professional` e `ProfessionalSpecialty`;
- **2.2:** `Patient` ativo/inativo e dados cadastrais confirmados;
- **2.3:** `PatientProfessionalLink` e service idempotente;
- **2.4:** resolução usuário/profissional, selector operacional e policy cadastral de paciente.

Itens anteriormente agrupados sob a Etapa 2, mas deliberadamente ainda não implementados, continuam obrigatórios antes de seus consumidores: `CoordinationAssignment`, `InsuranceProvider`, `PatientCoverage`, `PatientConsent`, responsáveis do paciente e detalhes pendentes do vínculo. A biometria foi retirada de `Patient` e pertence ao futuro fluxo de cobertura/atendimento.

### Etapa 3 — Núcleo da agenda — próxima

- salas, atendimentos e participantes;
- agenda semanal;
- durações;
- conflitos transacionais;
- estados e histórico;
- criação automática do vínculo assistencial na realização do primeiro atendimento;
- biometria de entrada e saída por atendimento quando exigida pela cobertura;
- bloqueios e justificativas.

### Etapa 4 — Agenda fixa — pendente

- regras recorrentes versionadas;
- materialização idempotente;
- sábado e limite de 31 de dezembro;
- prévia e tratamento visível de conflitos.

### Etapa 5 — Prontuário — pendente

- prontuário e escopos;
- evoluções e revisões;
- anexos privados;
- auditoria de acesso e testes de segurança.

### Etapa 6 — Cancelamentos, faltas e substituições — pendente

- eventos com autoria e motivo;
- distinção paciente/terapeuta;
- casos e tentativas de substituição;
- vínculo explícito entre origem e atendimento resultante.

### Etapa 7 — Sugestões futuras, sem bloquear a fundação — pendente

- definição operacional de presença;
- filtros de elegibilidade;
- ranking determinístico;
- explicações e parâmetros configuráveis;
- decisão sempre humana.

### Etapa 8 — Relatórios, aniversariantes e simulação — pendente

- definições unificadas;
- relatórios por escopo;
- simulação isolada da agenda oficial;
- importação CSV validada e auditada.

### Etapa 9 — Migração e homologação — pendente

- adaptadores ETL;
- ensaios completos;
- reconciliação;
- testes de carga e restauração;
- homologação por cada perfil operacional.

### Etapa 10 — Corte — pendente

- treinamento;
- janela de congelamento;
- backup;
- carga final;
- validação e aceite;
- V2 em produção e legado somente leitura;
- monitoramento intensivo.

As correções urgentes do legado — autorização da consulta, proteção da mídia, rotação de segredos, atualização segura do Django e remoção de mutações via GET — devem ser tratadas em plano separado, mediante autorização específica. Elas não devem esperar a V2, mas também não devem virar uma refatoração disfarçada do legado.

## 15. Riscos e decisões pendentes

### 15.1. Conflitos entre legado e especificação

| Tema | Legado | Direção da V2 |
|---|---|---|
| Confirmação | Conceito ausente ou inconsistente | Sem estado ou etapa de confirmação manual |
| Duração | Fluxos orientados a 60 minutos | 30 e 45 minutos |
| Agenda do terapeuta | Há mutações disponíveis | Somente leitura |
| Coordenação | Acesso inconsistente | Leitura limitada às áreas atribuídas |
| Administrativo clínico | Algumas rotas permitem ou podem revelar dados | Nenhum acesso clínico |
| Salas | Sem proteção robusta de sobreposição | Restrição de pacientes diferentes |
| Atendimento conjunto | Inferido por linhas coincidentes | Um atendimento com vários participantes |
| Bloqueios | Comportamento inconsistente | Alerta, eventual justificativa e auditoria |
| Agenda fixa | Alterações podem reescrever ou omitir ocorrências | Versionamento, preservação do passado e conflitos visíveis |
| Substituição | Inferida | Relação explícita entre origem, tentativa e destino |
| Papéis | Tratados de forma rígida ou inconsistente | Múltiplos papéis cumulativos, preservando limites de autoria |
| Vínculo assistencial | Incompleto ou inferido | Criado automaticamente no primeiro atendimento realizado e mantido enquanto o paciente estiver ativo |
| Evolução | Autoria/histórico insuficientes | Autor obrigatório e revisões imutáveis |
| Anexos | Mídia pública/direta | Armazenamento privado e download autorizado |
| Exclusão | Exclusões físicas possíveis | Inativação e preservação histórica |
| Imagem | Informação cadastral sem enforcement consistente | Consentimento escopado e aplicado |
| Biometria | Sem representação correta por atendimento | Cobertura aplicável determina a exigência; entrada e saída são registradas separadamente no atendimento |
| Sábado | Regras/implementação divergentes | Dia operacional suportado |
| Financeiro | Elementos legados | Fora do escopo inicial da V2 |

### 15.2. Riscos principais

- Dados legados ambíguos podem impedir reconstrução exata de autoria, vínculo, substituição e atendimento conjunto.
- Migração de anexos pode encontrar arquivos ausentes, públicos ou sem correspondência confiável.
- A versão, collation, limites e comportamento de bloqueio do MySQL no PythonAnywhere precisam ser validados antes da implantação.
- Regras ainda indefinidas podem contaminar o modelo se forem decididas apenas durante a construção.
- Operação simultânea prolongada de V1 e V2 aumenta risco de divergência; por isso não se recomenda dual-write.
- Permissões clínicas incorretas têm impacto de confidencialidade e devem bloquear a liberação.
- Falta de definição objetiva de presença e autorização do convênio reduz a confiabilidade das sugestões.
- Restrições concorrentes de agenda precisam ser testadas no mesmo banco usado em produção.
- Retenção mínima de cinco anos exige dimensionamento de arquivos, backups e restauração.

### 15.3. Decisões resolvidas

- Usuários podem acumular múltiplos papéis, com capacidades cumulativas e preservação dos limites de autoria.
- Não existe bypass global de `OWNER`; capacidades são concedidas explicitamente por recurso e operação.
- O escopo operacional implementado do terapeuta inclui somente pacientes ativos com vínculo assistencial ao seu `Professional`; ausência de perfil ou vínculo resulta em deny.
- O primeiro atendimento efetivamente realizado deverá criar automaticamente o vínculo para cada terapeuta participante.
- O vínculo permanece enquanto o paciente estiver ativo e seu histórico nunca é apagado; pacientes inativos saem das telas operacionais normais do terapeuta.
- O Proprietário visualiza toda a clínica, mas não edita evolução alheia; se também for Terapeuta, edita somente as próprias evoluções.
- A V2 não possui `CONFIRMED`; `WAITING` transiciona diretamente para `COMPLETED`, `MISSED` ou `CANCELLED`.
- Reposição é processo/relação explícita e não status de `Appointment`.
- Biometria não é estado de `Patient`: a cobertura Unimed aplicável exigirá registros separados de entrada e saída em cada atendimento.

### 15.4. Pendências consolidadas de equipe e pacientes

Estas questões permanecem abertas ou decididas mas pendentes de implementação:

- definir a regra operacional de `Professional.is_active` para selectors, policies, agenda e criação de novos vínculos;
- modelar o escopo de `COORDINATION` por especialidade/equipe, incluindo cardinalidade, vigência e eventuais subáreas;
- implementar `InsuranceProvider` e `PatientCoverage`, incluindo migração de convênio/carteirinha, vigência e autorizações;
- implementar `PatientConsent` versionado/escopado e definir categorias/finalidades, sem confundir consentimento externo com acesso interno a arquivo clínico;
- especificar os dados de responsáveis do paciente;
- definir busca sem acentos sem reproduzir o `nome_search` derivado da V1;
- definir reconciliação de duplicidades na importação, sem usar CPF, telefone ou nome como identidade automática;
- decidir se será necessária validação completa de CPF além da forma de 11 dígitos;
- implementar services de criação, atualização e inativação de `Patient` com autorização e auditoria conscientes;
- definir origem/auditoria da criação de `PatientProfessionalLink` quando o fluxo de `Appointment` existir;
- decidir se vínculo assistencial precisará de encerramento ou revogação explícitos;
- decidir se especialidade deve ser registrada no contexto do atendimento, do vínculo ou de ambos;
- definir se existirá acesso histórico específico do terapeuta a paciente inativo além do escopo operacional normal;
- modelar os registros de biometria de entrada/saída, suas exceções, autoria e auditoria, sem armazenar molde facial por inferência.

### 15.5. Decisões pendentes com efeito localizado

As questões abaixo não impedem o início da fundação. Cada uma deve ser resolvida antes da implementação da funcionalidade diretamente afetada.

**DECISÃO PENDENTE 1 — Escopo da Coordenação.** Um coordenador pode responder por várias especialidades e existem subáreas que exigem escopo mais granular?

**DECISÃO PENDENTE 2 — Correção de estado terminal.** Quais papéis podem corrigir `COMPLETED`, `MISSED` ou `CANCELLED`, em qual prazo e com quais motivos?

**DECISÃO PENDENTE 3 — Conflito do paciente.** O paciente pode ter atendimentos simultâneos em salas diferentes em alguma situação válida?

**DECISÃO PENDENTE 4 — Obrigatoriedade de sala.** Todo atendimento exige sala, inclusive remoto, externo ou administrativo?

**DECISÃO PENDENTE 5 — Sobreposição de bloqueio.** A justificativa é sempre obrigatória e quais papéis podem autorizar a sobreposição de bloqueio de sala ou profissional?

**DECISÃO PENDENTE 6 — Alteração de agenda fixa.** Ao mudar uma regra, quais ocorrências futuras podem ser canceladas/substituídas em lote e quais exigem decisão individual?

**DECISÃO PENDENTE 7 — Política de anexos.** Formatos, tamanhos, categorias, prazo de retenção e necessidade de antivírus.

**DECISÃO PENDENTE 8 — Contagem de atendimento conjunto.** Relatórios contam um atendimento, um atendimento por profissional, ambos, ou métricas distintas explicitamente nomeadas?

**DECISÃO PENDENTE 9 — Infraestrutura.** Confirmar versão e limites do MySQL no PythonAnywhere, armazenamento privado, política de backups e tarefas agendadas.

### 15.6. Decisões futuras que podem aguardar

Podem ser refinadas após os fundamentos, sem bloquear o início:

- desenho visual definitivo da lista de aniversariantes;
- layout exato da agenda semanal;
- adoção ou não de HTMX;
- pesos finais do ranking de sugestões;
- forma de registrar presença em tempo real, caso a sugestão de reposição venha a exigir isso;
- regras detalhadas de autorização da Unimed/convênio para sugestões;
- categorias e finalidades avançadas de consentimento de imagem;
- critérios para reconhecer substituições no legado sem inventar histórico;
- nome/código definitivo e atributos adicionais da Sala 8A;
- persistência e compartilhamento de simulações;
- armazenamento de objetos em longo prazo;
- eventual módulo financeiro futuro;
- qualquer uso futuro de inteligência artificial.

## Conclusão

A V2 foi criada como projeto Django separado, em MySQL, organizada como monólito modular e protegida por uma base de autorização centralizada em papel, operação e escopo. Agenda, prontuário, arquivos e substituições ainda precisam ser implementados como domínios explícitos, com serviços transacionais, históricos imutáveis e auditoria.

Essa estratégia evita carregar para a nova versão os riscos estruturais identificados no legado, permite ensaiar a migração repetidamente e mantém a operação atual estável até um corte controlado. As Etapas 0 a 2 fornecem a base para iniciar a Etapa 3; as questões pendentes devem ser resolvidas antes das funcionalidades que dependem diretamente delas, sem serem apagadas por ainda não estarem implementadas.
