# Validação da implementação

Registro de 22 de outubro de 2026. Escopo: aplicação pessoal local para Ubuntu 24.04+ no WSL2. Não representa certificação de produção ou benchmark de desempenho.

## Evidências executadas

| Verificação | Resultado |
| --- | --- |
| Backend Python 3.12, `uv sync --frozen` | Dependências resolvidas pelo lock |
| `uv run ruff check .` e `uv run ruff format --check .` | Passou |
| `uv run pytest -q`, incluindo integração | 23 testes passaram |
| Frontend, `npm test` | 11 testes passaram |
| `npm run build` | TypeScript e build de produção passaram |
| `npm audit --omit=dev` | Nenhuma vulnerabilidade reportada no momento da execução |
| Compose normal e override de testes, `docker compose config --quiet` | Configurações válidas |
| Scripts Bash no Ubuntu 26.04 WSL2 | Sintaxe válida |
| Bootstrap com runtime Docker simulado em diretório temporário | Senhas geradas, `.env` com permissão 600, segunda execução preserva credenciais |
| Playwright com Chrome, API simulada | Upload, chat, fontes, histórico após recarga, exclusão e navegação móvel passaram, sem erros de página |
| Inspeção visual | Desktop e biblioteca móvel em 320, 390 e 768 pixels; corrigidos largura e preenchimento da área móvel |
| Axe WCAG 2 A/AA e 2.1 AA, desktop e móvel | Nenhum achado nos estados examinados, excluindo somente sentinelas internas `[data-tabster-dummy]` do Fluent/Tabster |

## PostgreSQL 18 readiness

- **Baseline do servidor:** PostgreSQL 18.6, pgvector 0.8.7, checksums ativos. Servidor efêmero real no Ubuntu 26.04 WSL2, localhost:15432; binários extraídos e extensão compilada em `/tmp`, sem instalação no sistema.
- **Topologia:** uma instância local, sem réplica. Implantação entregue: Compose com imagem oficial PostgreSQL 18.6 e extensão compilada, volume no diretório pai `/var/lib/postgresql` do layout PostgreSQL 18.
- **Mudança:** instalação inicial de schema `rag`, documentos, chunks com vetores de 384 dimensões, configuração do modelo e registro de migração.
- **Compatibilidade:** versão maior verificada em migração e startup; migração repetida com sucesso no servidor real. Modelo de embeddings registrado no banco para impedir mistura de espaços vetoriais.
- **Locks e concorrência:** testes de fila, retomada de trabalho interrompido, perda/reaquisição da conexão de advisory lock, rejeição de um segundo worker, deduplicação, exclusão em cascata e limites de permissões. Chamadas nativas de CPU continuam protegidas durante cancelamento asyncio/AnyIO.
- **Segurança:** roles `rag_app` e `rag_migrator` sem superuser, criação de banco ou criação de roles; API recebeu DML, tentativa de DDL foi rejeitada. Inicialização das roles executada a partir do script entregue.
- **Desempenho:** busca híbrida validada nos caminhos semântico, lexical, combinado, sem resultado e por documentos. Full-text usa filtro `@@` compatível com GIN. Busca vetorial exata foi escolhida para o acervo pequeno; não foi medido volume representativo de produção nem construído índice ANN.
- **WAL e backup:** durabilidade padrão preservada. Script entregue exporta banco e arquivos com API pausada. Backup e restauração completos ainda não foram ensaiados.
- **Forward fix:** migrações idempotentes na versão inicial. Trocar o modelo de embeddings requer reindexação em um banco novo; credenciais do bootstrap não são alteradas silenciosamente.
- **Exceções:** skill PostgreSQL local contém `SKILL.md`, mas suas referências e scripts de auditoria não estão instalados. Foram usados documentação oficial, revisão de código e execução no servidor real.
- **Resultado:** **PRONTO COM RISCOS**, no escopo local; execução completa das imagens e ensaio de restauração permanecem pendentes.

## Embeddings e ingestão reais

O modelo `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` foi baixado e executado com `CPUExecutionProvider`. Foram verificados vetores finitos de 384 dimensões e tokenizer com limite de 128 tokens. Um documento longo produziu 16 fragmentos, preservou um marcador no final e não excedeu a janela de inferência. A similaridade usa cosseno, que não exige normalização prévia dos vetores.

Os vetores reais foram inseridos e recuperados no PostgreSQL pela role da aplicação, com filtro por documento. Também foi executado um smoke da API com `Runtime` real: upload TXT, fila persistente, extração, embeddings, estado `ready` e exclusão de arquivo/chunks. Todos os documentos de teste foram removidos ao terminar.

## Fluent UI React

- **Pacotes:** React 19, Fluent UI React Components 9.74.11 e ícones oficiais 2.0.344.
- **Composição:** provider, tema claro, tokens semânticos, Griffel, Field, Dialog, Popover, botões, badges e estados de feedback.
- **Conteúdo:** português do Brasil; upload, falhas, vazio, carga e progresso; pergunta limitada conforme orçamento do backend.
- **Acessibilidade:** nomes, composição de diálogos, navegação, fluxo móvel e análise automatizada nos estados de teste. As sentinelas internas de foco Tabster são mantidas no aplicativo; o scan as exclui por dispararem `aria-hidden-focus`.
- **Limites:** leitor de tela, cores forçadas e toda a matriz de estados WCAG não foram auditados. O teste de navegador usou API simulada; o teste de ingestão usou banco e embedding reais.
- **Resultado:** **CONFORME COM EXCEÇÕES** no escopo validado.

## Validações pendentes

O daemon Docker do ambiente estava parado, portanto **as imagens não foram construídas nem a stack completa foi iniciada**. O contrato HTTP/streaming com Ollama foi testado com transporte simulado, mas **a geração real pelo Qwen3/Ollama não foi executada**. A compatibilidade com Ubuntu 24.04 é baseada na execução via containers e requisitos documentados; a distribuição WSL disponível para testes foi Ubuntu 26.04.

Há um aviso de depreciação do `TestClient` Starlette para seu transporte HTTPX nos testes. A suíte passou; o aviso não afeta o cliente HTTPX usado pela aplicação para falar com Ollama.

Para completar a validação na máquina de destino: execute `bash scripts/bootstrap.sh`, aguarde os modelos, rode `bash scripts/doctor.sh`, envie o exemplo e confira uma resposta com suas fontes. Depois ensaie backup/restauração em outro projeto Compose com volumes novos.

## Instalador de dependências

`scripts/install-deps.sh`, o bootstrap atualizado e `scripts/tests/test-install-deps.sh` passaram na análise ShellCheck. Os **14 cenários** do instalador passaram no WSL Ubuntu 26.04, com uma instalação Ubuntu 24.04 simulada: runtime pronto, dependências básicas ausentes, Desktop indisponível, instalação inicial nativa, execução via sudo, grupo do usuário via sudo com Docker já pronto, daemon nativo parado, pacotes conflitantes, systemd desativado, plugin quebrado, somente Compose ausente, ajuda e argumentos inválidos/incompletos.

O teste usa Bubblewrap com rede desligada, arquivos do host somente leitura e comandos administrativos simulados. Verifica a configuração do repositório oficial, instalação apenas dos pacotes ausentes e orientações de ativação do grupo Docker. Nenhum pacote real foi instalado nem serviço real iniciado por esses testes. Execute com `bash scripts/tests/test-install-deps.sh`; Bubblewrap deve estar disponível e permitir namespaces de usuário.

## Limpeza de Kubernetes no WSL

`scripts/cleanup-wsl.sh` e seus testes passaram no ShellCheck. Os **24 cenários** de `scripts/tests/test-cleanup-wsl.sh` passaram com Bubblewrap, rede desligada e comandos administrativos simulados. Cobrem pacotes held, simulação sem mutações, reset local explícito, preservação de Docker CE e seus dados, dependências APT extras, falhas de resolução APT, ausência de kubeadm/socket/systemd, instalações Kubernetes alternativas, repetição sem pacotes e argumentos inválidos.

Também foram executadas duas prévias reais no Ubuntu 26.04 WSL: a padrão e a de reset com `--delete-cluster-data`, ambas **sem `--apply`**. O APT identificou exatamente sete pacotes (kubeadm, kubelet, kubectl, kubernetes-cni, cri-tools, containerd e runc), cinco deles marcados como hold, e nenhuma dependência extra para remoção. O `kubeadm reset --help` instalado confirmou suporte aos parâmetros usados. Nenhum nó real foi reinicializado, serviço parado ou pacote removido.

O detector do instalador foi corrigido para reconhecer tanto `install ok installed` quanto `hold ok installed`. Os 14 testes do instalador continuaram passando. A remoção real permanece uma ação explícita do usuário na máquina de destino; o script não altera a integração Rancher/Desktop do Windows.

## Configurações globais pelo frontend

A área de configurações oferece 21 parâmetros em quatro objetivos: modelo e respostas, velocidade e memória, busca e ingestão. Todos os acessos podem consultar e salvar os mesmos valores, sem contas ou autenticação. As explicações diferenciam ajustes de inferência de treinamento do modelo, informam limites e esclarecem quando cada alteração entra em vigor.

- **Backend:** Ruff aprovado e 49 testes passaram, incluindo integração com PostgreSQL 18.6 + pgvector 0.8.7 real. Foram verificados validação estrita, aplicação ao chat e à ingestão, opções enviadas ao Ollama, orçamento de contexto, modelos locais de geração, conflitos, processamento ativo e cancelamento durante gravação. O chat aceita até 10.000 IDs de documentos, alinhado ao teto configurável da biblioteca.
- **Persistência:** migração V1→V2 executada repetidamente preservou documento, vetor e configuração salva. Em 24 gravações concorrentes com a mesma revisão, somente uma venceu. A role da aplicação não pode inserir/excluir a configuração, alterar sua chave nem fazer DDL. Os parâmetros privados permanecem fora do contrato público.
- **CPU e PDF reais:** o MiniLM executou com `CPUExecutionProvider`; salvar duas para uma thread criou uma nova sessão ONNX. Um PDF com 501 páginas foi rejeitado no limite 500 e ficou pronto após salvar 800 e repetir a ingestão. Reiniciar o runtime preservou a revisão, o limite e a configuração de CPU, mesmo com valores iniciais diferentes no ambiente.
- **Frontend:** build de produção e 23 testes passaram. Playwright com Chrome e API simulada verificou salvar, validação entre campos, seleção de modelo, desfazer, restaurar sem aplicar automaticamente, retenção de edições em 409, recarga confirmada, indisponibilidade do Ollama e preservação do rascunho do chat.
- **Visual e acessibilidade:** interface inspecionada em desktop e em 320, 390 e 768 pixels, sem transbordamento horizontal e com ações de rodapé acessíveis. Nove análises Axe WCAG 2 A/AA e 2.1 AA não encontraram violações nos estados examinados, incluindo diálogo e modelos indisponíveis; foram excluídas somente as sentinelas internas `[data-tabster-dummy]`. Escape devolveu o foco ao acionador do diálogo. Leitor de tela e cores forçadas permanecem fora da validação.
- **Proxy:** `proxy_read_timeout` elevado para 1.900 segundos, compatível com a configuração de geração de até 1.800 segundos. A configuração foi inspecionada; Nginx não estava instalado para executar `nginx -t`.

O banco de ensaio ficou isolado em `/tmp` no WSL, sem modificar Kubernetes ou instalar pacotes no sistema. A conexão dos testes Windows usou IPv4 explícito (`127.0.0.1`); `localhost` apresentou falha de encaminhamento no ambiente. A stack Docker completa e a geração real pelo Ollama continuam pendentes, conforme as limitações anteriores.

## Biblioteca avançada

A área fica acima de Configurações no menu e separa Acervo, Indexação e Desempenho. O objetivo é localizar arquivos que precisam de atenção, inspecionar a estrutura dos trechos e observar o tempo das operações reais. A mensagem central é que métricas de estrutura e execução oferecem evidências para ajustes, sem constituir uma avaliação de precisão semântica.

### Dados e testes

- **Gates:** 72 testes backend passaram, incluindo cinco integrações com PostgreSQL 18 real; Ruff aprovado. Frontend com 30 testes aprovados e build de produção concluído. `git diff --check` sem achados.
- **Indexação real:** PDF de sete páginas com MiniLM em CPU produziu quatro páginas com texto, três sem texto e quatro fragmentos de 19 tokens. Três repetições exatas adicionais foram identificadas dentro do documento. A contagem de tokens inclui os tokens especiais da entrada do modelo. Nenhum dado de documento legado foi estimado.
- **Telemetria:** até 500 operações por tipo persistidas. Foram inseridas 502 amostras de chat e 502 de ingestão para verificar retenção, filtro de modelo dentro da mesma janela e percentis apenas de operações concluídas. As medições não contêm perguntas ou respostas.
- **Tempos:** latência do chat vai do início do stream à conclusão e inclui espera pela CPU, embedding da pergunta, busca e geração. Primeiro token usa o mesmo início; busca inclui embedding e SQL. Tokens/s usa exclusivamente `eval_count / eval_duration` de uma conclusão válida do Ollama. O histórico de ingestão inclui processamento e persistência, sem espera na fila ou pelo lock; o detalhe do documento mede até a gravação dos vetores antes da atualização/commit final.
- **Falhas:** chat concluído, sem fontes, erro e cancelamento foram exercitados com banco e embeddings reais, usando transporte Ollama simulado. Telemetria indisponível não alterou NDJSON nem manteve o lock da CPU. Uma gravação artificialmente lenta foi encerrada pelo timeout de dois segundos. Erro de ingestão foi contabilizado separadamente.
- **Reindexação:** confirmação na interface, original preservado, remoção atômica dos vetores e metadados antigos e retorno à fila. Requisições concorrentes não duplicam o trabalho; erro posterior não deixa vetores antigos disponíveis. Detalhe usa snapshot de leitura consistente durante reindexação concorrente.

### Gráficos e interface

Apache ECharts **6.1.0**, com imports modulares, renderizador SVG e carregamento sob demanda. A composição usa barra empilhada para estados, histograma para faixas de tokens, barras horizontais ordenadas para concentração por documento e linha temporal para desempenho. Barras partem de zero; a faixa de estados termina no total exato; a linha usa tempo real, sem eixo duplo. Os gráficos não usam padrões, animação ou gradientes decorativos. Rótulos, contagens e tabelas HTML expansíveis preservam os valores sem depender de cor ou hover.

- **Fluxos Playwright/Chrome:** pesquisa, estado, ordem, paginação, detalhe, trechos paginados, retry, exclusão/reindexação confirmadas, retorno aos filtros, retenção do rascunho do chat, filtro de modelo, alternância de métricas, ingestões e estados vazio/indisponível passaram com API simulada.
- **Visual:** desktop, 320, 390 e 768 pixels inspecionados. Corrigido overflow das abas em 320 pixels. Detalhe e parâmetros de ingestão expandidos também verificados em 320/390. Gráficos aguardam dimensões positivas antes de inicializar, inclusive quando a lista fica oculta pelo detalhe ou em cores forçadas. Nenhum erro de página; o único erro de recurso registrado foi o HTTP 503 provocado no ensaio de indisponibilidade.
- **Acessibilidade:** 25 análises Axe WCAG 2 A/AA e 2.1 AA sem violações nos estados examinados. Excluídas somente as sentinelas internas `[data-tabster-dummy]`. Escape retorna ao acionador de reindexação; no celular, voltar à conversa foca o menu visível. Cores forçadas e redução de movimento inspecionadas, incluindo acesso à tabela do gráfico. Leitor de tela e cobertura integral de WCAG não foram validados.
- **Bundle:** página avançada aproximadamente 39 KB minificados / 10 KB gzip; ECharts aproximadamente 541 KB minificados / 185 KB gzip, carregado separadamente. O aviso Vite de chunk acima de 500 KB permanece visível. O gráfico não integra o carregamento inicial do chat.

**Fluent UI React — CONFORME COM EXCEÇÕES:** React 19, componentes Fluent 9.74.11 e ícones oficiais 2.0.344; provider e tema existentes preservados. Button, Field, Input, Select, TabList/Tab, Badge, InfoLabel, ProgressBar e Dialog usam APIs públicas, tokens semânticos e Griffel. Conteúdo em português e descrições técnicas sob demanda. Exceções: leitor de tela e matriz completa de estados/tecnologias assistivas não auditados; biblioteca ECharts lazy mantém o aviso de tamanho descrito acima.

### PostgreSQL 18 readiness

- **Baseline/topologia:** PostgreSQL 18.6 (`180006`), pgvector 0.8.7, checksums ativos, instância única isolada no WSL Ubuntu 26.04. Destino continua Compose local, sem réplica.
- **Mudança/compatibilidade:** migração V3 adiciona colunas anuláveis de métricas/tokenização e tabelas de histórico com retenção. Upgrade V2→V3 repetido três vezes preservou documentos, vetores, configuração global e campos legados nulos. Não há recálculo de embeddings na migração.
- **Locks/concorrência:** DDL usa os limites existentes de lock de 10 s e statement de 60 s, antes da API iniciar. Reindexação tem lock da linha do documento; gravação final publica vetores e métricas na mesma transação. Uma leitura de detalhe pausada antes do reindex retornou o snapshot antigo consistente; uma leitura nova retornou fila sem fragmentos.
- **Segurança:** `rag_app` recebeu SELECT/INSERT/DELETE nas tabelas de histórico e mantém os privilégios anteriores dos documentos. UPDATE do histórico, DDL, alteração da identidade dos embeddings e INSERT/DELETE da configuração global foram recusados. Nenhuma credencial está no contrato público de métricas.
- **Desempenho/capacidade:** EXPLAIN ANALYZE/BUFFERS com 200 documentos e 4.976 fragmentos confirmou resumo/lista globais lendo apenas metadados de `rag.documents`, sem varrer conteúdo ou vetores. Detalhes usam índices por documento. Os tempos desse fixture não constituem benchmark para o teto de 10.000 arquivos/20.000 fragmentos por arquivo; não foram adicionados índices por suposição.
- **WAL/backup/recuperação:** durabilidade preservada. `pg_dump` custom V3 e restore em outro banco isolado preservaram documento/vetor, histórico, revisão da configuração e grants; `pg_amcheck` terminou sem erros. Esse ensaio é do banco, não do script completo com arquivos e volumes Docker.
- **Forward fix:** migração aditiva e idempotente; documentos legados continuam disponíveis e podem ser reindexados individualmente. Não foi executado rollback destrutivo. Nenhum serviço Kubernetes ou pacote do sistema foi alterado.
- **Resultado:** **PRONTO COM RISCOS** no escopo local validado. Permanecem pendentes a stack Docker completa, geração/benchmark com Ollama real, Ubuntu 24.04 real e ensaio no volume máximo permitido. As referências/scripts da skill PostgreSQL local continuam ausentes, conforme registrado anteriormente.

## Temas Claro e Escuro

O frontend oferece Claro, Escuro e Sistema nos cabeçalhos do chat, das configurações e da biblioteca avançada. A preferência é local ao navegador, persiste em `mini-rag.appearance` e sincroniza abas da mesma origem. Sistema é o padrão e acompanha mudanças do sistema operacional; uma seleção manual prevalece sobre essas mudanças.

- **Fluent UI React — versão e composição:** componentes 9.74.11 e ícones oficiais 2.0.344 preservados. Temas separados com `createLightTheme`/`createDarkTheme`, rampa verde-petróleo existente e ajustes semânticos de ações, links e erro. Um único `AppearanceProvider` envolve a aplicação e os portais; Menu/MenuItemRadio, Tooltip, Button, Dialog e Popover mantêm suas composições públicas.
- **Estilo e comportamento:** superfícies, texto, estados, campos, Markdown e gráficos usam o tema ativo. ECharts atualiza as cores ao trocar o tema, incluindo instâncias que ficaram ocultas. A mudança preservou rascunhos do chat, campos pendentes das configurações e a revisão dos parâmetros globais. Cabeçalhos móveis foram compactados sem retirar status ou contagem de documentos.
- **Primeira pintura e CSP:** `appearance-init.js` externo e síncrono antecede o bundle React. Sete cenários de navegador com o bundle bloqueado confirmaram tema, superfície, cor de texto, `color-scheme` e `theme-color` corretos antes de React, incluindo escolha explícita, Sistema, valor ausente/inválido e armazenamento indisponível. A política `script-src 'self'` foi preservada; não foi liberado script inline. Testes ligam as cores literais dessa inicialização aos valores reais do tema Fluent.
- **Testes:** 51 testes frontend e build de produção aprovados. Os 21 testes de aparência cobrem leitura/gravação, exceções de armazenamento, eventos entre abas, resolução do sistema, bootstrap real e contraste. Inspeção do build e `git diff --check` sem erros; permanece o aviso conhecido de bundle ECharts acima de 500 KB, carregado sob demanda.
- **Navegador:** Playwright/Chrome executou o build com a CSP de produção e API simulada. Foram verificados seleção por menu/teclado, opção marcada, recarga, sincronização entre abas, remoção da preferência, mudanças do sistema, armazenamento bloqueado e cota excedida. Eventos de `sessionStorage` ou de outras chaves não alteraram a aparência. Nenhum erro de página ou aviso de console nos fluxos finais.
- **Contraste:** testes dos temas verificaram texto de ações e links em repouso/hover/pressionado/selecionado, além de erros e avisos sobre superfícies comuns e de feedback. Revisão independente confirmou 12 estados renderizados de botão e checkbox: mínimo 4,57:1 para texto das ações; indicadores de checkbox acima de 5:1. Marcas gráficas superaram 3:1 e texto dos gráficos superou 4,5:1 em ambos os temas.
- **Visual e acessibilidade:** desktop, 320, 390 e 768 pixels inspecionados. Foram corrigidos contraste do texto de erro escuro, refluxo móvel e Spinners decorativos redundantes. Blocos de código horizontalmente roláveis recebem foco e nome acessível somente quando há overflow. As 39 análises Axe WCAG 2 A/AA e 2.1 AA nos temas normais não tiveram violações nos estados examinados, excluindo somente sentinelas `[data-tabster-dummy]`.
- **Cores forçadas:** inspeção e uma análise estrutural adicional passaram. Somente `color-contrast` foi desabilitada nessa análise: o Chrome aplica as cores de sistema na pintura, mas o Axe usado prefere o valor autoral de `-webkit-text-fill-color`. A revisão confirmou `color` efetivo preto/branco e contraste 21:1 nos dois esquemas do sistema, com `forced-color-adjust: auto`. Essa exceção não se aplica às análises dos temas Claro/Escuro.
- **Conteúdo e limites:** opções, tooltips e estado anunciado em português; ajuda técnica permanece sob demanda. Não foram auditados leitor de tela, toda a matriz WCAG ou todos os ambientes de navegador. O teste estático com CSP representa as regras entregues pelo Nginx, sem iniciar a stack Docker completa.
- **Resultado Fluent UI React:** **CONFORME COM EXCEÇÕES**, no escopo visual e funcional testado; as exceções de tecnologia assistiva, emulação de cores forçadas e aviso de bundle estão descritas acima.
