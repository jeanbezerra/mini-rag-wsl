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
