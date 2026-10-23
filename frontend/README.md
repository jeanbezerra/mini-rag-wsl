# Interface Mini RAG

React 19, TypeScript, Vite 8 e Fluent UI React v9. A API é acessada por `/api` na mesma origem. No desenvolvimento, o Vite encaminha as chamadas para `localhost:8000`; no contêiner, o Nginx encaminha para `api:8000`.

```bash
npm ci
npm run dev
npm test
npm run build
```

Use Node.js 22.12 ou superior. O Dockerfile usa Node.js 22 para compilar e Nginx para servir a aplicação na porta 8080. Para executar a aplicação completa no Ubuntu WSL, siga o README da raiz.

## Comportamento

- Upload sequencial de múltiplos PDF, TXT, MD e DOCX. O progresso de envio usa bytes reais; os estados de ingestão são consultados na API a cada cinco segundos e ao retornar à aba.
- Chat NDJSON incremental com decodificação UTF-8, interrupção com `AbortController`, tratamento de erros e detecção de conexão encerrada antes do evento `done`.
- Histórico de até 40 conversas no navegador. Não sincroniza entre navegadores. Respostas incompletas são identificadas após recarregar a página. Se o armazenamento estiver indisponível ou cheio, a interface informa a limitação.
- Seleção de documentos prontos, trechos das fontes em diálogos, confirmação de exclusão e tentativa de ingestão após erro.
- Markdown com HTML desabilitado, sem imagens remotas, sem execução de código. Links usam a transformação segura padrão do `react-markdown`.
- A pergunta respeita os limites da API: até 2.000 caracteres e 1.500 bytes UTF-8. O histórico enviado inclui as últimas 12 mensagens completas, com até 4.000 caracteres cada.
- Configurações globais sem login, acessíveis no menu e no cabeçalho. Quatro objetivos organizam os controles: modelo e respostas, velocidade e memória, busca nos documentos, ingestão e limites. Cada parâmetro apresenta seu efeito, unidade e intervalo aceito.
- A edição usa `/api/settings`, com revisão para impedir que uma aba sobrescreva silenciosamente outra. Conflitos preservam os ajustes pendentes; recarregar ou voltar sem salvar exige confirmação. “Desfazer” retorna ao último estado carregado e “Restaurar padrões” preenche o formulário, sem persistir até salvar.
- Modelos são listados por `/api/models`; a interface não baixa modelos. A indisponibilidade do Ollama permite editar os demais parâmetros. O chat e seu rascunho permanecem montados ao abrir as configurações.

## Fluent UI e validação

`@fluentui/react-components` 9.74.11 e `@fluentui/react-icons` 2.0.344, com componentes estáveis, `FluentProvider`, tema claro de marca verde-petróleo, tokens semânticos e Griffel. `Dialog` e `Popover` preservam suas composições oficiais. `Field` associa o rótulo e a validação à pergunta. Os controles e o conteúdo estão em português do Brasil.

Os testes cobrem limites e recuperação do histórico, erros da API, cancelamento, fim inesperado do stream, divisão de caracteres UTF-8 entre pacotes, validação dos parâmetros, dependências entre contexto e resposta, sobreposição dos trechos e conflitos de revisão. O build inclui verificação estrita de tipos. A documentação de design foi consultada no catálogo oficial Fluent 2 e a API foi conferida nos tipos instalados.

A avaliação de acessibilidade automatizada e a inspeção visual complementam esses testes. Uma validação completa com leitor de tela e cores forçadas permanece necessária antes de declarar conformidade integral com WCAG. Sentinelas de foco internas do Tabster (`[data-tabster-dummy]`) podem aparecer como falso positivo `aria-hidden-focus` em verificadores automáticos; não remova esses elementos do aplicativo.
