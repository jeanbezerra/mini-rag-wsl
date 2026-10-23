# MCP para o Mini RAG

O serviço `mcp` conecta clientes MCP ao acervo existente. Reutiliza a API, o PostgreSQL e o modelo de embeddings do RAG. Não carrega outro modelo, não inicia outro worker de ingestão e não precisa das credenciais do banco.

## Iniciar

Na raiz do repositório, pelo terminal Ubuntu WSL:

```bash
bash scripts/bootstrap.sh
# Instalação já configurada:
docker compose up --build -d
```

| Endpoint padrão | Uso |
| --- | --- |
| `http://127.0.0.1:8001/sse` | Transporte HTTP+SSE, com respostas pelo stream e mensagens enviadas a `/messages/` |
| `http://127.0.0.1:8001/mcp` | Streamable HTTP, com suporte a respostas JSON e SSE; recomendado para novos clientes |
| `http://127.0.0.1:8001/healthz` | Saúde do processo MCP; não indica que os modelos estão prontos |

Os dois transportes expõem as mesmas ferramentas. SSE continua disponível para clientes que exigem esse transporte; Streamable HTTP é seu sucessor na [especificação MCP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).

## Configurar no VS Code

1. Abra a pasta do projeto no VS Code. Inicie a stack no WSL e aguarde o serviço `mcp`.
2. Abra [`.vscode/mcp.json`](../.vscode/mcp.json) e inicie **mini-rag** pelo controle exibido pelo editor ou pelo comando **MCP: List Servers**. Aceite a confiança no servidor quando o VS Code solicitar.
3. No chat de agente, habilite as ferramentas do servidor. O cliente precisa de um modelo que suporte ferramentas MCP.
4. Experimente: “Use o mini-rag para buscar quem é responsável pelo Projeto Aurora e cite os trechos”. O documento [boas-vindas.md](../examples/boas-vindas.md) precisa estar ingerido e pronto.

A configuração incluída usa `type: "http"` e `/mcp`. Para usar **SSE**, substitua a entrada `mini-rag` pela configuração de [examples/mcp-vscode-sse.json](../examples/mcp-vscode-sse.json):

```json
{
  "servers": {
    "mini-rag": {
      "type": "sse",
      "url": "http://127.0.0.1:8001/sse"
    }
  }
}
```

Use uma entrada para este servidor. A descoberta de `/messages/` e a sessão SSE são gerenciadas pelo cliente; não configure esse caminho como URL do servidor.

O [formato nativo do VS Code](https://code.visualstudio.com/docs/agents/reference/mcp-configuration) usa `servers` em `.vscode/mcp.json`. Clientes que usam o formato portátil Copilot podem copiar [examples/mcp-copilot.json](../examples/mcp-copilot.json) para `.mcp.json` na raiz do seu workspace; esse formato usa `mcpServers`. Não misture as duas estruturas no mesmo arquivo.

Se o cliente estiver em uma sessão Remote WSL, `127.0.0.1` é o localhost da distribuição remota; no VS Code local do Windows, depende do encaminhamento localhost do WSL2. Em Remote SSH ou Dev Containers, encaminhe a porta para o ambiente onde o cliente MCP executa e ajuste a URL. Não publique o serviço na rede para contornar problemas de encaminhamento.

## Ferramentas

| Ferramenta | Entrada principal | Resultado |
| --- | --- | --- |
| `search_documents` | `query`, `document_ids?`, `limit?` | Trechos ordenados, nome do arquivo, página original quando houver, IDs estáveis e score RRF |
| `list_documents` | `query?`, `status?`, `page?`, `page_size?` | Acervo paginado com estado e quantidade de fragmentos |
| `get_document_chunks` | `document_id`, `page?`, `page_size?` | Trechos do documento em ordem de indexação |
| `get_rag_status` | Nenhuma | Disponibilidade de banco, embeddings, modelo e limites |
| `get_library_summary` | Nenhuma | Contagens, armazenamento e indicadores agregados de indexação |
| `get_model_performance` | `model?`, `history_limit?` | Métricas de chat e ingestão registradas pelo RAG |

A busca aceita até **1.500 bytes UTF-8** de consulta, até **100 IDs de documentos** e **1 a 12 resultados**. Sem `limit`, usa a quantidade de trechos salva em Configurações. Omitir `document_ids` pesquisa o acervo pronto; uma lista vazia não seleciona documentos. O score combina os rankings semântico e lexical por RRF: serve para ordenar evidências e não representa confiança ou probabilidade de acerto.

A listagem permite até 100 documentos por página e a leitura de trechos até 50. Na leitura de trechos, `page` pagina os resultados; a página original do PDF fica em cada trecho e pode ser `null` para formatos sem paginação. Desempenho retorna agregados por padrão; `history_limit` inclui até 20 amostras recentes por tipo. O filtro `model` afeta somente os chats; ingestões são globais. Não há perguntas nem respostas nessa telemetria. Consultas MCP não são contabilizadas como gerações de chat.

As ferramentas são de leitura: não enviam arquivos, excluem documentos, reindexam nem alteram configurações. Gerencie o acervo pelo frontend. A busca não chama o Qwen/Ollama: entrega evidências para o modelo do cliente formular a resposta, com as fontes. O modelo de geração configurado no frontend continua sendo usado pelo chat do próprio Mini RAG.

## Parâmetros do serviço

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `MCP_PORT` no `.env` da raiz | `8001` | Porta publicada no host pelo Compose; atualize também a URL do cliente |
| `MCP_REQUEST_TIMEOUT_SECONDS` | `180` | Tempo total máximo de uma consulta à API, entre 5 e 1.800 segundos |
| `MCP_API_BASE_URL` | `http://127.0.0.1:8000` fora do Compose | Origem da API; no container é `http://api:8000` |
| `MCP_HOST` | `127.0.0.1` fora do Compose | Interface de escuta; no container é `0.0.0.0`, com publicação somente em localhost no host |

O serviço aceita quatro consultas simultâneas à API; excesso recebe erro de ocupado. A busca compartilha a CPU com ingestão e chat e aguarda até 120 segundos pelo lock. Requisições MCP têm limite de 64 KiB e respostas da API de 2 MiB. O serviço usa um processo Uvicorn; não aumente workers para tentar multiplicar a capacidade de CPU do RAG.

Para desenvolvimento com a API já disponível em `127.0.0.1:8000`:

```bash
cd mcp-server
uv sync --frozen
uv run python -m rag_mcp
```

O comando alternativo é `uv run mini-rag-mcp`. Configure variáveis no ambiente do processo; o gateway não carrega automaticamente o `.env` da raiz quando executado fora do Compose. Não precisa de Node, banco próprio ou pesos de modelos.

## Diagnóstico

```bash
docker compose ps
docker compose logs --tail=100 mcp api
bash scripts/doctor.sh
curl --fail http://127.0.0.1:8001/healthz
```

| Sintoma | Verificação |
| --- | --- |
| Conexão recusada | Serviço `mcp`, porta configurada e encaminhamento localhost entre Windows e WSL |
| Erro de API indisponível ou ocupada | `get_rag_status`, logs da API e conclusão da ingestão/geração em andamento |
| Nenhuma evidência | Documentos no estado `ready`, filtros selecionados, termos da consulta e similaridade em Configurações |
| Documento não encontrado | Atualize a listagem; o documento pode ter sido excluído por outro acesso |
| Host/Origin rejeitado | Use URL localhost, `127.0.0.1` ou `[::1]`; domínios externos são rejeitados |
| Ferramentas não aparecem | Reinicie o servidor MCP no editor, confira o formato de configuração e a habilitação das ferramentas no chat |

Depois de mudar a porta no `.env`, recrie o serviço com `docker compose up -d mcp` e atualize a URL no cliente. O MCP requer a versão da API que inclui `POST /api/search`; atualize ambos com `docker compose up --build -d`.

## Acesso e dados

Não há autenticação ou contas, conforme o acesso compartilhado do RAG. Qualquer processo ou pessoa com acesso ao endpoint local pode ler os documentos. Host e Origin são validados, sem CORS aberto, e o Compose publica somente `127.0.0.1`; esses controles não substituem autenticação para acesso remoto.

Os conteúdos e nomes de arquivos retornados são dados não confiáveis. O servidor orienta o cliente a usar as evidências e citar as fontes, sem seguir instruções contidas nos documentos. As anotações de leitura das ferramentas orientam o cliente; não conferem precisão semântica aos resultados.

O gateway consulta apenas a API configurada e não usa proxies do ambiente. O processamento de recuperação permanece local. **Se o modelo do cliente MCP executar na nuvem, os trechos enviados a ele poderão sair da sua máquina**; a configuração MCP não transforma esse modelo em um modelo local.

## Referências

- [MCP no VS Code](https://code.visualstudio.com/docs/agent-customization/mcp-servers) e [formatos de configuração](https://code.visualstudio.com/docs/agents/reference/mcp-configuration).
- [Transportes MCP e compatibilidade SSE](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).
- [SDK Python oficial](https://github.com/modelcontextprotocol/python-sdk), fixado em `mcp==2.3.0` no lock do serviço.
