# Especificação Funcional — Sistema da Clínica V2

**Versão:** 0.3  
**Status:** Em implementação — Etapas 0, 1 e 2 concluídas  
**Origem:** auditoria do sistema legado + requisitos confirmados com a clínica + decisões de escopo

## 1. Objetivo

A V2 deverá reconstruir o sistema atual com uma estrutura mais segura, organizada, testável e fácil de manter, preservando as funcionalidades utilizadas pela clínica e corrigindo problemas estruturais do legado.

O sistema legado será referência funcional e fonte dos dados existentes. As regras deste documento serão a fonte de verdade para a nova implementação.

Objetivos principais:

- preservar funcionalidades úteis;
- tornar permissões explícitas e seguras;
- preservar corretamente o histórico clínico;
- reconstruir a agenda com regras consistentes;
- melhorar o fluxo de reposições;
- facilitar futuras alterações;
- reduzir duplicação e código difícil de compreender;
- possuir testes e documentação;
- permitir evolução futura, inclusive financeiro e usos específicos de IA.

## 2. Escopo inicial

A primeira reconstrução deverá contemplar:

- autenticação e usuários;
- pacientes;
- terapeutas e equipe;
- especialidades e coordenação;
- agenda;
- agenda fixa;
- salas;
- bloqueios;
- consultas;
- prontuários;
- evoluções;
- anexos;
- faltas;
- cancelamentos;
- reposições;
- relatórios atuais;
- grade editável/simulação;
- biometria facial;
- aniversariantes;
- sugestão de reposições;
- auxílio à criação de agendas.

### Fora do escopo inicial

O módulo financeiro completo será tratado em fase posterior. A arquitetura não deverá impedir sua adição futura.

Funcionalidades genéricas de IA também ficam fora do núcleo inicial. IA só deverá ser adicionada posteriormente para casos concretos em que traga benefício operacional claro.

### 2.1 Estado consolidado da implementação

| Etapa | Estado | Escopo consolidado |
|---|---|---|
| 0 — Fundação | **Implementada** | Projeto V2 independente, MySQL, configurações por ambiente, testes, lint, CI, segredos por ambiente e estrutura modular inicial |
| 1 — Identidade, autorização e auditoria | **Implementada** | `User` próprio, papéis oficiais, `Policy`/`PolicyContext` deny-by-default, grupos Django, matriz-base e `AuditEvent` append-oriented |
| 2 — Equipe e pacientes | **Implementada** | 2.1 equipe e especialidades; 2.2 `Patient`; 2.3 vínculo assistencial; 2.4 selectors e policy cadastral de paciente |
| 3 — Núcleo da agenda | **Próxima** | Ainda não implementada |
| 4 a 10 | **Pendentes** | Agenda fixa, prontuário, faltas/substituições, sugestões, relatórios, migração, homologação e corte |

A conclusão da Etapa 2 não significa que convênios, consentimentos, escopo de Coordenação ou demais itens futuros tenham sido descartados. Esses requisitos permanecem decididos ou em aberto e devem ser implementados antes das funcionalidades que dependem deles.

## 3. Perfis de usuário

Os quatro papéis oficiais são:

- `OWNER` — Dono;
- `ADMINISTRATIVE` — Administrativo;
- `COORDINATION` — Coordenação;
- `THERAPIST` — Terapeuta.

Um mesmo usuário poderá acumular múltiplos perfis. As capacidades concedidas pelos perfis se acumulam, sempre respeitando o escopo e as restrições de cada operação. Por exemplo, um usuário poderá ser simultaneamente Dono e Terapeuta.

O acúmulo de perfis não autoriza editar evolução escrita por outro profissional.

Todas as permissões deverão ser verificadas no backend. Esconder botões, links ou elementos da interface não é suficiente como controle de acesso.

Os papéis e sua acumulação estão implementados sobre `Group`/`Permission` nativos do Django. A infraestrutura central de autorização usa deny-by-default: uma operação sem regra explícita é negada. Não existe bypass global de `OWNER` nem de superusuário criado por essa camada; capacidades amplas devem ser concedidas explicitamente pela policy de cada recurso, preservando restrições futuras como autoria de evolução.

## 4. Permissões

Até a conclusão da Etapa 2, a matriz concreta implementada cobre somente operações cadastrais de `Patient`: `patient.view`, `patient.create`, `patient.update` e `patient.inactivate`. Essa policy expressa capacidade; views, formulários e services de CRUD de paciente ainda não foram implementados. Não existe `patient.delete` como operação normal.

`OWNER` e `ADMINISTRATIVE` possuem as quatro capacidades cadastrais explícitas, inclusive leitura do cadastro inativo. `THERAPIST` possui somente `patient.view` para paciente ativo dentro de seu escopo assistencial. `COORDINATION` permanece deny-by-default para pacientes até que seu escopo por especialidade/equipe possa ser representado corretamente. Nenhuma dessas regras concede acesso implícito a prontuário, evolução ou anexo clínico.

### 4.1 Dono

O Dono possui acesso integral de visualização e administração do sistema, respeitadas as regras de autoria e preservação dos registros clínicos.

Pode:

- visualizar todas as agendas;
- criar e alterar agendamentos;
- visualizar todos os pacientes;
- visualizar todos os prontuários;
- visualizar todas as evoluções;
- administrar equipe;
- administrar salas;
- acessar relatórios;
- realizar operações administrativas autorizadas.

O Dono não pode editar evolução criada por outro profissional. Se o mesmo usuário também possuir o perfil de Terapeuta, poderá criar e editar suas próprias evoluções segundo as regras desse perfil.

### 4.2 Administrativo

O Administrativo é responsável principalmente pela operação da clínica.

Pode:

- visualizar todas as agendas;
- criar e alterar agendamentos;
- cadastrar e editar pacientes;
- visualizar dados cadastrais dos pacientes;
- organizar faltas e reposições;
- administrar aspectos operacionais da agenda;
- visualizar relatórios administrativos;
- realizar operações administrativas autorizadas.

Não pode:

- visualizar evoluções clínicas;
- visualizar conteúdo clínico do prontuário;
- acessar anexos clínicos protegidos.

### 4.3 Coordenação

A Coordenação possui acesso somente à sua área/especialidade de coordenação.

Pode visualizar:

- pacientes da sua área;
- prontuários desses pacientes;
- evoluções relacionadas à sua área;
- agendas dos profissionais da área coordenada.

Não pode alterar a agenda.

A Coordenação é um perfil de visualização e supervisão, não de administração operacional.

### 4.4 Terapeuta

A permissão do terapeuta é baseada no vínculo real com o paciente.

O vínculo assistencial deverá ser criado automaticamente quando o terapeuta efetivamente realizar o primeiro atendimento do paciente. Em atendimento conjunto, o vínculo poderá ser estabelecido para todos os profissionais participantes. A Administração não precisará cadastrar manualmente esse vínculo no fluxo normal.

Depois de criado, o vínculo permanece enquanto o paciente estiver ativo. Fim de agenda fixa, troca de agenda ou período sem atendimento não encerram automaticamente o vínculo. Quando o paciente se tornar inativo, deixará de aparecer para o terapeuta nas telas operacionais normais, mas o vínculo histórico será preservado.

#### Agenda

O terapeuta:

- visualiza exclusivamente a própria agenda;
- não visualiza a agenda completa de outros terapeutas;
- não altera a própria agenda;
- não altera a agenda de outros terapeutas.

Alterações de agenda são realizadas por usuários administrativos autorizados.

#### Pacientes

O terapeuta somente poderá acessar dados de pacientes que sejam seus pacientes.

Para um paciente que ele atende, pode:

- visualizar dados cadastrais;
- visualizar prontuário;
- visualizar o histórico multidisciplinar de evoluções;
- criar evolução;
- editar a própria evolução.

Para paciente sem vínculo com o terapeuta, não pode acessar dados cadastrais, prontuário ou evoluções.

#### Histórico multidisciplinar

Quando o terapeuta possui vínculo com o paciente, poderá visualizar evoluções realizadas por outros profissionais para esse mesmo paciente. Isso não concede acesso aos demais pacientes desses profissionais.

## 5. Pacientes

Os dados cadastrais atuais deverão ser preservados na migração, mas cada dado deve ser destinado à entidade correta da V2 em vez de achatar toda a estrutura legada em `Patient`.

O modelo `Patient` implementado possui:

- chave primária interna estável;
- `name`;
- `cpf` opcional e não único;
- `birth_date` opcional;
- `phone` opcional e não único;
- `default_service_type`, preservando os valores operacionais existentes;
- `is_active`;
- `created_at`;
- `updated_at`.

CPF, telefone, nome ou outro dado mutável não são usados como chave. A validação completa de CPF, caso necessária além da forma de 11 dígitos, continua em aberto. A estratégia de busca sem acentos substituirá o `nome_search` derivado do legado, mas ainda não foi definida.

### 5.1 Inativação e histórico

Pacientes não deverão ser fisicamente excluídos durante a operação normal. Deverão possuir estado ativo/inativo.

O histórico deverá ser preservado por pelo menos cinco anos, conforme requisito da clínica.

Pacientes inativos não deverão aparecer normalmente como opções para novos atendimentos, mas seu histórico deverá permanecer acessível aos usuários autorizados.

### 5.2 Convênios e cobertura

`InsuranceProvider` e `PatientCoverage` ainda não foram implementados. Os campos legados de convênio e carteirinha não foram colocados diretamente em `Patient`: deverão ser preservados por meio das entidades de cobertura, com vigência, situação e dados necessários à autorização.

### 5.3 Vínculo assistencial e escopo operacional

`PatientProfessionalLink` está implementado com `patient`, `professional` e `established_at`. Existe no máximo um vínculo por par paciente/profissional, e os dois lados são protegidos contra deleção destrutiva enquanto houver vínculo.

O service idempotente de garantia do vínculo existe, mas a criação automática a partir de atendimento ainda depende da Etapa 3. A regra confirmada é:

- mero agendamento não cria vínculo;
- `WAITING`, `MISSED` e `CANCELLED` não criam vínculo;
- quando um profissional participar efetivamente de um `Appointment` que passe para `COMPLETED`, o sistema deverá criar ou reutilizar o vínculo;
- em atendimento conjunto, a operação deverá ser aplicada a cada profissional participante;
- agenda encerrada, ausência de consultas futuras ou passagem de tempo não encerram o vínculo;
- a inativação do paciente preserva o vínculo histórico.

Estão implementados `professional_for_user` e `operational_patients_for_professional`. O escopo operacional do terapeuta inclui somente pacientes ativos vinculados ao seu `Professional`; usuário sem relação explícita com `Professional` recebe deny. Paciente inativo fica fora desse escopo normal, sem apagar o vínculo. Eventual acesso histórico específico do terapeuta a paciente inativo ainda precisa ser definido.

## 6. Autorização de imagem

A autorização de uso externo de imagem deixará de ser apenas informativa e deverá efetivamente controlar os usos aos quais o consentimento se aplica. `PatientConsent`, ou desenho arquitetural equivalente versionado e escopado, ainda não foi implementado.

A regra detalhada de quais categorias de arquivo e funcionalidades dependem dessa autorização deverá ser definida antes da implementação específica desse recurso.

Consentimento para uso externo de imagem não deve ser confundido com autorização interna para acessar anexos clínicos. O acesso interno continuará sujeito à policy do prontuário/anexo, independentemente da finalidade do consentimento de imagem.

## 7. Agenda

A agenda continuará sendo um dos módulos centrais do sistema. Suas regras estão decididas nos pontos abaixo, mas `Appointment`, `AppointmentParticipant`, `Room` e os fluxos de agenda ainda não foram implementados; constituem a próxima etapa.

Um `Appointment` representará um paciente, uma sala e um intervalo. Participação conjunta será representada por vários profissionais no mesmo atendimento, e não por atendimentos duplicados que apenas coincidem em horário.

Deverá suportar:

- visualização semanal;
- navegação entre períodos;
- criação de atendimento;
- agenda fixa;
- atendimento avulso;
- cancelamento;
- falta;
- realização;
- reposição;
- bloqueios;
- identificação de sala;
- atendimentos conjuntos.

## 8. Duração dos atendimentos

A duração usual será de 45 minutos.

Também existirão atendimentos de 30 minutos.

A duração deverá fazer parte explicitamente do atendimento e não depender de uma duração global rígida.

## 9. Estados do atendimento

A V2 não terá etapa nem estado de confirmação manual.

Estados-base:

- `WAITING` / AGUARDANDO;
- `COMPLETED` / REALIZADO;
- `MISSED` / FALTA;
- `CANCELLED` / CANCELADO.

Um atendimento aguardando poderá posteriormente ser marcado como realizado, falta ou cancelado.

A distinção entre cancelamento, falta do paciente e falta do terapeuta deverá ser preservada de forma consistente, inclusive nos relatórios.

## 10. Salas e atendimento conjunto

Uma sala não pode conter dois pacientes diferentes simultaneamente.

Vários terapeutas podem utilizar simultaneamente a mesma sala quando estiverem atendendo conjuntamente o mesmo paciente.

Exemplo permitido:

- Sala 3, 10:00;
- Paciente João;
- Terapeuta A;
- Terapeuta B.

Exemplo de conflito:

- Sala 3, 10:00;
- Paciente João com Terapeuta A;
- Paciente Maria com Terapeuta B.

## 11. Sala 8A

Deverá ser acrescentada uma nova sala denominada provisoriamente `8A`, decorrente da divisão física da antiga sala 8.

Como essa necessidade é urgente, a sala poderá ser adicionada ao sistema legado antes da conclusão da V2 por meio de alteração pequena e controlada.

## 12. Bloqueios

Existirão bloqueios de terapeuta e de sala.

Um bloqueio não deverá necessariamente impedir o agendamento. O sistema deverá exibir aviso claro ao usuário autorizado, que poderá decidir prosseguir quando a operação da clínica justificar isso.

Esse aviso de bloqueio configurado não elimina a validação de conflito real: um profissional não poderá participar de atendimentos sobrepostos, e pacientes diferentes não poderão ocupar a mesma sala simultaneamente.

## 13. Agenda fixa

A agenda fixa continuará existindo.

Sua materialização poderá continuar até 31 de dezembro do ano corrente.

### 13.1 Alterações

Alterações não deverão modificar retroativamente o histórico.

Regra geral:

- ocorrências anteriores permanecem como estavam;
- a nova configuração passa a valer a partir da alteração.

Consultas realizadas e histórico anterior não deverão ser silenciosamente reescritos.

A implementação exata do tratamento das ocorrências futuras já materializadas será definida na arquitetura respeitando essa regra.

### 13.2 Conflitos

Conflitos de agenda fixa deverão ser detectados e informados claramente. O sistema deverá apresentar opções aplicáveis e permitir que o usuário autorizado decida como proceder quando a regra de negócio permitir.

Conflitos não deverão ser ignorados silenciosamente.

## 14. Agenda de sábado

Existe um problema conhecido com a agenda dos pacientes aos sábados.

A V2 deverá suportar sábado normalmente.

Antes da migração, o problema deverá ser investigado para determinar se sua causa está na grade, agenda fixa, materialização, filtros ou outra regra. O comportamento incorreto atual não deverá ser simplesmente reproduzido.

## 15. Evoluções

Prontuário, evoluções e suas policies ainda não foram implementados. Quando implementados, terapeutas poderão criar evoluções somente para pacientes aos quais possuem acesso.

Uma evolução deverá registrar explicitamente pelo menos:

- paciente;
- atendimento relacionado;
- autor;
- data de criação;
- data da última alteração;
- conteúdo.

O terapeuta poderá editar suas próprias evoluções e não poderá editar a evolução de outro terapeuta. Essa restrição também se aplica ao Dono: possuir esse perfil permite visualizar todas as evoluções, mas não editar uma evolução alheia. Um Dono que também seja Terapeuta mantém o direito de criar e editar somente as próprias evoluções conforme as regras do perfil de Terapeuta.

## 16. Histórico e exclusões clínicas

Informações clínicas importantes não deverão desaparecer silenciosamente.

Sempre que adequado, a V2 deverá privilegiar estados como ativo, inativo, cancelado ou revertido em vez de exclusão física.

Pacientes, atendimentos, prontuários e demais registros que componham histórico relevante deverão preservar rastreabilidade.

## 17. Anexos clínicos

Imagens, vídeos e outros anexos clínicos deverão exigir autorização do sistema para acesso.

Não deverão depender exclusivamente de uma URL pública conhecida.

Uploads deverão possuir validações adequadas de tipo e tamanho.

O diretório de mídia de produção não deverá ser versionado no Git.

## 18. Faltas

O sistema deverá distinguir pelo menos:

- falta do paciente;
- falta do terapeuta.

As definições utilizadas em agenda, relatórios e reposições deverão ser consistentes em todo o sistema.

## 19. Reposição

Reposições ainda não foram implementadas. Na V2, reposição será um conceito explícito e não deverá ser inferida simplesmente porque um atendimento é avulso.

Reposição não é um estado do atendimento. Ela deverá ser representada como processo ou relação explícita entre o atendimento de origem e o atendimento resultante. O atendimento resultante seguirá os mesmos estados dos demais atendimentos e poderá ficar REALIZADO, FALTA ou CANCELADO.

Quando aplicável, deverá ser possível saber:

- qual atendimento ou falta originou a reposição;
- quem foi remanejado;
- para qual horário;
- qual terapeuta realizou;
- quando ocorreu.

## 20. Sugestão automática de reposição

A V2 poderá, em fase posterior à fundação, auxiliar a recepção a encontrar possíveis reposições. A definição detalhada desse mecanismo não bloqueia o início da V2.

O processo poderá considerar:

- paciente que faltou;
- terapeuta que faltou;
- pacientes presentes na clínica;
- terapeutas que atendem esses pacientes;
- disponibilidade dos terapeutas;
- agenda dos pacientes;
- possibilidade de antecipação;
- sala disponível;
- conflitos existentes;
- prioridade operacional dos terapeutas remunerados por diária;
- necessidade de verificar liberação da Unimed, quando aplicável.

Quando implementada, essa funcionalidade deverá utilizar regras determinísticas. O sistema sugere e a recepção decide. Detalhes de presença, autorização da Unimed e ranking permanecem decisões futuras da funcionalidade e não são pré-requisitos da fundação arquitetural.

## 21. Auxílio à criação de agenda

Ao criar ou reorganizar uma agenda, o sistema deverá poder sugerir combinações viáveis de paciente, terapeuta, horário e sala, considerando disponibilidade e conflitos conhecidos.

Assim como na reposição, será inicialmente um sistema de regras e sugestões, não uma decisão autônoma por IA.

## 22. Prioridade de terapeutas por diária

A clínica informou que determinadas reposições devem priorizar profissionais remunerados por diária.

Essa característica deverá ser representada como dado configurável e não como lista de nomes escrita no código.

A forma exata será definida durante a modelagem.

## 23. Biometria facial

A biometria ainda não foi implementada. A regra confirmada substitui a ideia anterior de biometria como estado permanente do paciente:

- paciente com cobertura Unimed aplicável deverá realizar biometria na entrada e na saída de cada atendimento;
- a cobertura vigente determinará se o atendimento exige biometria;
- cada `Appointment` deverá registrar separadamente a biometria de entrada e a biometria de saída;
- `Patient` não possui nem deverá receber `biometric_status` permanente para representar essa regra;
- nenhum molde facial ou outro dado biométrico foi modelado nesta etapa.

O formato exato dos registros, horários, responsáveis, exceções e auditoria será definido com `PatientCoverage` e `Appointment`, preservando a regra acima.

## 24. Relatórios

Relatórios ainda não foram implementados. Os relatórios atuais necessários deverão inicialmente ser preservados.

Suas regras internas deverão, porém, ser unificadas. Conceitos como falta e reposição deverão possuir a mesma definição em todos os relatórios.

## 25. Aniversariantes

Deverá existir uma maneira simples de visualizar os pacientes que fazem aniversário no dia.

A localização exata dessa informação na interface será definida posteriormente.

## 26. Grade editável / simulação

A funcionalidade atual de grade/simulação deverá permanecer.

O comportamento inicial continuará sendo de simulação separada da agenda oficial, salvo decisão posterior da clínica.

A interface deverá deixar claro quando as alterações são apenas simulações.

## 27. Importação de pacientes

A importação CSV existente será inicialmente preservada.

O fluxo deverá ser revisado para validação adequada dos dados e para evitar exposição desnecessária de dados pessoais em logs.

## 28. Segurança

Segurança será requisito estrutural da V2.

Deverão ser garantidos pelo menos:

- autorização no backend;
- arquivos clínicos protegidos;
- nenhuma credencial versionada;
- operações destrutivas usando métodos apropriados;
- proteção CSRF;
- validação de uploads;
- política adequada de senhas;
- configuração segura de produção;
- registro de autoria das evoluções;
- proteção contra acesso por IDs arbitrários;
- trilha de auditoria para ações clínicas relevantes.

## 29. Auditoria e rastreabilidade

A infraestrutura `AuditEvent` e seu service explícito estão implementados de forma append-oriented. Checks de policy e selectors, por serem leituras, não geram eventos automaticamente. A instrumentação dos futuros casos de uso de mutação permanece pendente e não deverá usar signals genéricos para esconder efeitos de negócio.

A V2 deverá permitir identificar ações importantes, incluindo quando aplicável:

- quem criou uma evolução;
- quem editou uma evolução;
- quando houve edição;
- quem alterou um atendimento;
- quem cancelou um atendimento;
- quando ocorreu o cancelamento;
- quem alterou permissões;
- quem realizou operações clínicas relevantes.

## 30. Dados e backups

A V2 deverá possuir estratégia documentada de backup de:

- banco de dados;
- arquivos clínicos.

Também deverá existir procedimento de restauração.

A configuração atual do PythonAnywhere deverá ser investigada antes da migração.

### 30.1. Banco oficial da V2

MySQL será o banco oficial da V2 em desenvolvimento, testes, integração contínua, homologação e
produção. A fundação deverá usar o backend oficial do Django para MySQL, banco próprio e vazio,
InnoDB, `utf8mb4`, modo estrito e a mesma família de versão em todos os ambientes.

O SQLite do legado continuará pertencendo exclusivamente à V1 e não poderá ser reutilizado nem
modificado pela V2. Credenciais e endereços de produção não serão registrados no código ou na
documentação versionada.

A escolha considera a infraestrutura MySQL já disponível na conta paga do PythonAnywhere e a
ausência, neste momento, de requisito funcional confirmado que dependa exclusivamente de
PostgreSQL. Se surgir tal requisito, a decisão deverá ser reavaliada formalmente antes de criar
dependência específica de outro banco.

## 31. Código e manutenção

A V2 não deverá repetir a organização monolítica do legado.

A arquitetura concreta será definida em etapa posterior, mas são objetivos obrigatórios:

- separar domínios;
- evitar arquivos de views gigantescos;
- separar regras de negócio da apresentação;
- reduzir duplicação;
- possuir testes automatizados;
- possuir documentação;
- organizar JavaScript e CSS;
- centralizar regras de permissão;
- evitar regras importantes somente em templates ou forms.

## 32. Testes

Regras críticas deverão possuir testes automatizados.

Na consolidação ao fim da Etapa 2, a V2 possui 133 testes automatizados aprovados, cobrindo fundação, papéis, deny-by-default, auditoria-base, equipe, paciente, vínculo assistencial, selectors e policy cadastral de paciente. Os cenários abaixo que dependem de agenda, prontuário, anexos, migração ou concorrência continuam pendentes.

### Permissões

- terapeuta não acessa paciente alheio;
- terapeuta visualiza somente a própria agenda;
- administrativo não acessa prontuário/evoluções;
- coordenação fica limitada à sua área;
- capacidades de múltiplos perfis se acumulam sem ampliar a edição de evoluções alheias;
- dono visualiza todas as evoluções, mas não altera evolução alheia.

### Agenda

- sala não recebe pacientes diferentes simultaneamente;
- atendimento conjunto do mesmo paciente é permitido;
- durações de 30 e 45 minutos funcionam corretamente;
- bloqueios produzem alertas;
- transições entre AGUARDANDO, REALIZADO, FALTA e CANCELADO respeitam as regras permitidas;
- sábado funciona corretamente.

### Prontuário

- evolução possui autor;
- terapeuta não altera evolução alheia;
- terapeuta não acessa paciente sem vínculo;
- primeiro atendimento realizado cria automaticamente o vínculo do terapeuta e, em atendimento conjunto, dos profissionais participantes;
- vínculo permanece enquanto o paciente está ativo e é preservado historicamente após a inativação;
- paciente inativo não aparece ao terapeuta nas telas operacionais normais;
- anexo não pode ser acessado sem autorização adequada.

### Agenda fixa

- alteração não modifica o histórico anterior;
- conflitos são detectados e apresentados.

### Reposição

- reposição mantém relação com sua origem;
- reposição não é estado do atendimento;
- atendimento resultante de reposição usa os estados normais do atendimento;
- atendimento avulso não é automaticamente classificado como reposição.

## 33. Migração

A V2 deverá ser desenvolvida sem destruir ou modificar indiscriminadamente o banco utilizado pela clínica.

A V1 permanecerá em produção durante o desenvolvimento. V1 e V2 são projetos e bancos separados; não haverá dual-write. A migração ocorrerá posteriormente por ETL ensaiado, seguido de reconciliação, homologação e corte controlado.

A migração deverá ser uma etapa própria:

1. extração do legado;
2. transformação e validação;
3. importação na V2;
4. conferência de integridade.

Dados históricos deverão ser preservados sempre que possível.

A migração deverá possuir verificações quantitativas e de integridade antes da troca definitiva.

## 34. Funcionalidades adiadas

### 34.1 Financeiro

Fica fora da primeira reconstrução.

Posteriormente deverá receber especificação própria envolvendo, entre outros pontos:

- valores;
- convênios;
- pagamentos;
- repasses;
- faturamento;
- regras por terapeuta;
- possíveis diárias.

### 34.2 IA

Não será criado um módulo genérico de IA apenas por existir interesse na tecnologia.

Primeiro serão construídos processos e dados confiáveis. Depois serão avaliados casos concretos em que IA possa reduzir trabalho ou melhorar processos.

## 35. Critério geral de sucesso

A V2 será considerada pronta quando, além de as telas funcionarem:

- as regras da clínica estiverem documentadas;
- as permissões forem aplicadas no backend;
- os dados históricos tiverem sido preservados;
- prontuários e anexos estiverem protegidos;
- a agenda possuir regras consistentes;
- reposições forem rastreáveis;
- atendimento conjunto funcionar corretamente;
- sábado funcionar corretamente;
- usuários entenderem alertas e conflitos;
- regras críticas possuírem testes automatizados;
- existir backup e restauração documentados;
- o código estiver dividido em módulos compreensíveis;
- outra pessoa conseguir compreender e manter o projeto sem depender exclusivamente do desenvolvedor original.

## 36. Próxima etapa

A arquitetura técnica da V2 está descrita em `PLANO_ARQUITETURA_V2.md`, com base em:

1. `AUDITORIA_SISTEMA.md`;
2. este `ESPECIFICACAO_V2.md`;
3. código real do legado.

As Etapas 0, 1 e 2 estão concluídas. A Etapa 3, núcleo da agenda, é a próxima. As Etapas 4 a 10 permanecem pendentes. Cada questão ainda aberta deverá ser resolvida antes da implementação da parte do sistema que dependa dela.

## 37. Pendências preservadas para recuperação

As pendências abaixo não estão resolvidas e não devem ser inferidas durante a implementação:

- regra operacional de `Professional.is_active`, inclusive seu efeito sobre selectors e criação de novos vínculos;
- modelagem do escopo de `COORDINATION` por especialidade/equipe;
- `InsuranceProvider` e `PatientCoverage`, inclusive vigência, autorizações e migração de convênio/carteirinha;
- `PatientConsent`, suas categorias/finalidades e a distinção entre consentimento externo e autorização interna de anexo;
- dados de responsáveis do paciente, ainda não especificados;
- estratégia de busca sem acentos que substituirá `nome_search`;
- tratamento de duplicidades e identidade durante a importação de pacientes;
- eventual validação completa de CPF;
- services de criação, atualização e inativação de `Patient`;
- auditoria dos futuros casos de uso de mutação;
- origem e auditoria da criação de `PatientProfessionalLink`;
- eventual necessidade de encerramento ou revogação explícita do vínculo assistencial;
- necessidade e semântica de associar especialidade ao atendimento ou ao vínculo;
- eventual acesso histórico específico do terapeuta a paciente inativo;
- representação detalhada da biometria de entrada/saída e exceções operacionais;
- todas as decisões de agenda, anexos, infraestrutura, relatórios e migração ainda marcadas como abertas no plano de arquitetura.

Uma pendência continuar neste documento não significa que esteja implementada; significa que não pode ser perdida apenas porque sua etapa ainda não chegou.
