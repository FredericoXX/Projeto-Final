# Constituição do projeto

Princípios duradouros. Não descrevem a implementação corrente nem fixam
tecnologias: descrevem o que se pretende que continue verdadeiro à medida que a
implementação muda. O estado observável vive em
[`02-current-state.md`](02-current-state.md).

O projeto é um **protótipo académico** de assistente institucional genérico
para instituições de ensino superior. A abordagem técnica de recuperação de
informação continua dependente da revisão da literatura e da avaliação
experimental; nenhuma implementação atual é decisão arquitetural definitiva.

## 1. Isolamento entre instituições

Uma instituição não deve ver dados de outra. Este é o objetivo; importa
descrever com rigor como é atingido, porque uma garantia sobredeclarada é pior
do que nenhuma.

- A aplicação e os services **devem** aplicar filtros por instituição em todas
  as leituras e escritas. É aqui que o isolamento é efetivamente decidido.
- A identidade institucional usada para autorização vem sempre do utilizador
  autenticado, nunca do payload ou do caminho do pedido.
- As constraints e as foreign keys compostas da base de dados garantem
  **integridade relacional**: impedem que linhas de instituições diferentes
  fiquem relacionadas entre si.
- A base de dados **não** usa Row-Level Security nem mecanismo equivalente. As
  constraints, por si só, **não impedem** que uma consulta escrita sem filtro
  institucional leia linhas de outra instituição.
- O isolamento resulta, portanto, da **combinação** entre autenticação,
  autorização, a forma como as queries são escritas e a integridade relacional
  — não de uma barreira única que torne o erro de programação impossível.

Um recurso de outra instituição responde como inexistente, não como proibido:
a existência de outros locatários não é revelada.

Consequência prática: qualquer consulta nova que toque em dados institucionais
é revista quanto ao filtro por instituição, porque a base de dados não o fará
por ela.

## 2. Segurança e privacidade

- Segredos — chaves, tokens, palavras-passe — nunca entram no repositório, em
  logs, em exceções ou em respostas.
- Mensagens de erro devolvidas ao cliente são curtas e não expõem tracebacks,
  caminhos internos nem detalhes de implementação.
- Documentos institucionais reais e dados pessoais nunca entram em testes,
  fixtures ou artefactos versionados. O material de teste é sintético.
- Registos que possam conter excertos institucionais não são versionados nem
  partilhados sem revisão humana.
- Os logs contêm apenas informação operacional controlada, escolhida
  deliberadamente — nunca conteúdo documental, prompts, respostas de
  fornecedores ou credenciais.

## 3. Respostas fundamentadas em evidências

Uma resposta do assistente é sustentada por evidência recuperada dos documentos
da instituição. Sem evidência suficiente, a resposta correta é dizê-lo — nunca
produzir uma resposta plausível sem suporte.

**Ausência de resultados é uma resposta legítima**, não uma falha a corrigir
por relaxamento de critérios.

O sistema não é apresentado como livre de alucinações, e nenhuma documentação o
afirma. As limitações conhecidas são declaradas explicitamente, mesmo quando
inconvenientes.

## 4. Auditabilidade das respostas e das fontes

Deve ser possível saber, mais tarde, com que evidência uma resposta foi
produzida. Alterações posteriores aos documentos não devem reescrever
silenciosamente o registo do que foi dito na altura.

Este princípio é geral e não fixa mecanismo. A forma concreta de o cumprir — o
modelo de citações persistidas, e a distinção entre "recuperável agora" e
"legitimamente citado então" — é **matéria de desenho, não regra
constitucional**. O estado dessa formalização vive em
[`02-current-state.md`](02-current-state.md).

## 5. Neutralidade de fornecedor como objetivo arquitetural

Nenhum fornecedor externo, SDK ou modelo deve tornar-se difícil de substituir.
A integração com serviços externos fica isolada atrás de contratos neutros, num
módulo adaptador dedicado, para que trocar de fornecedor seja uma alteração
localizada.

Isto é um objetivo de desenho, e o seu alcance é declarado em vez de presumido:
um contrato neutro reduz o acoplamento, mas não elimina por si só a dependência
de instalação nem determina em que ponto o SDK é carregado. **Resolver um
fornecedor não deve impor o carregamento de outro**, e o conhecimento do SDK não
sai do adaptador. O que é hoje dependência de instalação, e onde o SDK é
efetivamente importado, é estado corrente e vive em
[`02-current-state.md`](02-current-state.md).

A aplicação deve arrancar sem credenciais de fornecedor; a ausência de
configuração só produz efeito no ponto em que o serviço é realmente necessário.

## 6. Separação entre instruções e dados não confiáveis

Conteúdo institucional — títulos, URLs, texto de documentos, perguntas — é
**sempre** tratado como dado não confiável. Não é concatenado com instruções, e
é serializado de forma a não conseguir alterar a estrutura construída pela
aplicação.

Esta separação **reduz o risco** de prompt injection; **não garante imunidade
semântica**. Serializar conteúdo como dados impede que ele altere a estrutura
do pedido, mas não impede que um modelo trate como instrução aquilo que lê. A
validação existente é estrutural e determinística, não semântica.

## 7. Separação de responsabilidades

Extração, segmentação, recuperação, geração de respostas e interface são
responsabilidades distintas, com contratos explícitos entre si:

- cada uma é substituível sem reescrever as outras;
- uma camada inferior não depende de uma superior;
- o mecanismo de pesquisa não se confunde com a política que decide o que é
  evidência admissível;
- a interface não é uma fronteira de segurança — o backend autoriza todos os
  pedidos.

## 8. Compatibilidade futura com diferentes fontes documentais

A recuperação e a geração de respostas devem depender apenas de conteúdo e
metadados já persistidos, para que uma fonte documental futura possa alimentar
os mesmos contratos.

Objetivo, não descrição do presente: o **processamento** documental atual
depende do armazenamento e de metadados do ficheiro de origem — nomeadamente do
caminho no storage e do tipo de conteúdo declarado. A independência conseguida
até agora é a das camadas a jusante da extração.

## 9. Disciplina de âmbito

Um trabalho faz o que declarou fazer. Melhorias adjacentes que surjam pelo
caminho são registadas, não executadas.

Quando um trabalho exige tocar numa área que a sua especificação colocou fora
de âmbito, **pára** e a questão é tratada separadamente. O âmbito não se alarga
silenciosamente.

## 10. Fluxo por branch e Pull Request

- Nunca se commita diretamente na `main`.
- Cada trabalho vive numa branch própria e chega à `main` por Pull Request.
- Uma branch tem um propósito único e coerente.
- Commits, push e Pull Requests só são criados quando explicitamente pedidos.

## 11. Honestidade das verificações

Um teste existente não é removido, enfraquecido ou reescrito para esconder uma
regressão. Acrescentar casos é sempre permitido; alterar expectativas exige
justificação explícita.

Resultados são reportados como foram obtidos. Um passo não executado é
declarado como não executado. Uma contagem só é apresentada com a indicação de
onde e quando foi medida.

## 12. Idioma e nomenclatura

Documentação e comentários em **português europeu**; identificadores, comandos,
endpoints, nomes de classes, funções e tecnologias em **inglês**. Nomes de
ficheiros e diretórios em inglês.

---

## O que não é uma invariante

Descrevem o estado atual e podem mudar. Vivem em
[`02-current-state.md`](02-current-state.md):

- as tecnologias concretas — base de dados, framework, fornecedor de geração,
  runtime de OCR — e os nomes concretos de colunas, módulos ou endpoints;
- o retrieval ser exclusivamente lexical e determinístico;
- a ausência de embeddings, pesquisa vetorial ou semântica;
- a ausência de uma decisão sobre RAG;
- a execução ser exclusivamente local e sem serviços externos no retrieval;
- a forma atual de persistência das citações e a política que a governa;
- a dependência atual do processamento documental face ao armazenamento e ao
  tipo de ficheiro;
- o número atual de migrations, testes ou módulos;
- os comandos concretos de verificação, que dependem da estrutura atual.
