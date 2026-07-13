# Media Finder

Base de um painel web para pesquisar mídia em fontes autorizadas pelo usuário, comparar resultados e enviar torrents ao qBittorrent. Esta entrega implementa as **Fases 1 a 6**: fundação, contrato de providers, processamento de domínio, interface de busca, integração real com qBittorrent e providers Prowlarr/Jackett.

## O que está pronto

- FastAPI com páginas server-rendered em Jinja2.
- Tema escuro responsivo para desktop e celular.
- Configuração por variáveis de ambiente usando Pydantic Settings.
- SQLAlchemy 2.x com SQLite e sessões por request.
- Migration inicial do Alembic para `providers`, `search_history`, `download_history` e `settings`.
- Health check em `GET /health` com status HTTP `503` quando o banco não está acessível.
- Assets locais em `/static`, incluindo HTMX 2.0.7 sem dependência de CDN.
- Dockerfile baseado em `python:3.12-slim`, identidade `PUID`/`PGID` configurável, execução final não-root, migration automática e healthcheck.
- Exemplo de serviço para Docker Compose.
- Contrato assíncrono `SearchProvider`, schemas normalizados e registry explícito.
- `MockProvider` determinístico com latência, timeout, erro, lista vazia e health configuráveis.
- `SearchService` com execução concorrente, timeout por provider e erros parciais estruturados.
- Endpoint JSON `GET /providers/health` para providers habilitados.
- Contratos `SearchFilters`, `SearchSort`, `ScoringPreferences` e `ProcessedSearchResult`.
- Parser determinístico de release, tamanho e magnet/info hash sem chamadas externas.
- Normalização baseada em evidência, deduplicação forte por hash e fraca opcional por título/tamanho/qualidade.
- Filtros AND entre categorias e OR dentro de cada categoria, ordenação estável e scoring explicável/configurável.
- Pipeline assíncrono `process_search_results` com métricas por etapa e preservação de erros dos providers.
- Interface completa de busca com Jinja2, HTMX local, filtros, ordenação, loading, estados vazios e layout desktop/mobile.
- Rotas `/search`, `/search/history` e `/search/result/{result_token}`.
- Histórico SQLite com paginação e somente metadados não sensíveis.
- Tokens aleatórios temporários em memória, TTL, limite de armazenamento e rate limit por IP.
- Integração real com qBittorrent usando `qbittorrent-api`, autenticação reutilizável, timeouts e chamadas fora do event loop.
- Integrações reais opcionais com Prowlarr e Jackett, usando APIs oficiais, indexadores selecionáveis, cache curto, rate limit, timeouts e normalização comum.
- Categorias configuráveis somente para `movie → movies` e `series → series`; `anime` e `other` permanecem desabilitados.
- POST `/downloads` protegido por CSRF e baseado exclusivamente em token temporário server-side.
- Histórico paginado de downloads, refresh de status e endpoints de health/categorias do qBittorrent.
- Testes unitários e HTTP para registry, schemas, mock, pipeline, templates, segurança e histórico.
- Testes e configuração do Ruff.

Sonarr, Radarr, Torrentio, MediaFusion, Comet, AIOStreams e scraping HTML continuam fora do escopo.

## Arquitetura das Fases 1 a 6

```text
Browser
   │
   ▼
FastAPI ── Jinja2 + HTMX local + CSS/JS local
   │
   ├── ProviderRegistry ── SearchProvider Protocol ── MockProvider / Prowlarr / Jackett
   │                                      │
   │                                      └── SearchService (asyncio.gather + timeouts)
   │                                                     │
   │                                                     ▼
   │                                normalize → deduplicate → filter → score → sort
   │                                                     │
   │                                                     ▼
   ├── Jinja2 + HTMX ── formulário ── resultados ── token detail ── download token
   │
   ├── SQLAlchemy 2.x ── SQLite (/config/media-finder.db)
   ├── Alembic ── migrations executadas no entrypoint
   └── QBitTorrentService ── qbittorrent-api síncrona em asyncio.to_thread
```

O serviço é preparado para rodar como um único container. Não há Node.js, frontend separado, Redis, Celery ou banco externo.

## Execução com Docker

### Build e execução local

Prepare o diretório persistente com permissão de escrita para o usuário configurado. O padrão compatível com o home server é `PUID=1000` e `PGID=1000`:

```bash
mkdir -p .media-finder-config
sudo chown 1000:1000 .media-finder-config
```

```bash
docker build -t media-finder:dev .
docker run --rm \
  --name media-finder \
  -p 8091:8091 \
  -v "$PWD/.media-finder-config:/config" \
  -e APP_ENV=development \
  -e PUID=1000 \
  -e PGID=1000 \
  -e DATABASE_URL=sqlite:////config/media-finder.db \
  media-finder:dev
```

Abra `http://localhost:8091` e consulte `http://localhost:8091/health`.

### Compose existente

O arquivo [`docker-compose.example.yml`](docker-compose.example.yml) contém a entrada do serviço e usa os nomes de container descritos no projeto. Ele foi pensado para ser copiado ou incorporado ao `docker-compose.yml` já existente no home server; por isso, o exemplo usa `context: ./media-finder` a partir do diretório pai.

Se o exemplo for executado diretamente a partir deste diretório, altere o contexto para `.`.

```bash
docker compose build media-finder
docker compose up -d media-finder
docker compose logs -f media-finder
```

O bloco de exemplo assume que o Compose completo existente já fornece o serviço `qbittorrent`, pois a Fase 1 mantém `depends_on` apenas para ele. Portanto, depois de incorporar o bloco ao Compose do home server, execute:

```bash
docker compose build media-finder
docker compose up -d media-finder
```

Prowlarr e Jackett são providers opcionais: não são dependências de inicialização e não impedem o boot quando estão fora do ar ou sem chave. O qBittorrent indisponível também não impede o boot.

## Contrato de providers

O contrato está em [`app/providers/base.py`](app/providers/base.py). Cada provider precisa expor `slug`, `name`, `search(SearchRequest)` e `health_check()`.

O registry é explícito: providers são registrados com `registry.register(provider, priority=...)`, slugs duplicados são rejeitados e a seleção retorna somente providers habilitados em ordem de prioridade (menor número primeiro). Nenhuma importação automática ou descoberta por glob é usada.

Exemplo mínimo:

```python
registry = ProviderRegistry()
registry.register(MyProvider(), priority=10)
service = SearchService(registry, default_timeout=8.0, provider_timeouts={"my-provider": 3.0})
result = await service.search(SearchRequest(query="Example"), ["my-provider"])
```

O resultado agregado informa `providers_requested`, `providers_succeeded`, resultados parciais, warnings estruturados e duração total. Uma falha ou timeout cancela somente a tarefa daquele provider.

O mock pode ser consultado pelo endpoint de health:

```bash
curl http://localhost:8091/providers/health
```

## Providers reais: Prowlarr e Jackett

O registro é explícito e respeita `PROWLARR_ENABLED` e `JACKETT_ENABLED`. Chaves vazias deixam o provider indisponível no health, sem falhar o boot. Chaves nunca são incluídas em logs, exceções, templates ou respostas públicas.

O adapter Prowlarr usa a API oficial com `X-Api-Key` e os endpoints `GET /api/v1/system/status`, `GET /api/v1/indexer` e `GET /api/v1/search`. A busca usa `type`, `query`, `indexerIds` e `categories` quando as capabilities permitem; caso contrário, recorre à busca geral. Consulte a [documentação oficial de busca do Prowlarr](https://wiki.servarr.com/en/prowlarr/search).

O adapter Jackett usa exclusivamente o endpoint Torznab documentado `/api/v2.0/indexers/{indexer}/results/torznab/api`: `t=caps` para capabilities e `t=search`, `t=tvsearch` ou `t=movie` para resultados. `JACKETT_INDEXERS=all` consulta o agregador configurado; uma lista separada por vírgulas restringe os indexadores. Consulte o [README oficial do Jackett](https://github.com/Jackett/Jackett).

As rotas auxiliares para a UI são `GET /providers/prowlarr/indexers` e `GET /providers/jackett/indexers`. A busca aceita os campos repetidos `prowlarr_indexers` e `jackett_indexers`. O formulário carrega os indexadores somente quando o provider é selecionado e envia `all` por padrão.

As respostas externas passam por limites de tamanho, validação JSON/XML, normalização de magnet/hash, remoção de parâmetros sensíveis de URLs e cópia defensiva no cache. Resultados parciais de indexadores não derrubam a busca; somente uma falha total é reportada ao `SearchService`.

O processamento de domínio é usado pela rota HTMX de busca:

```python
from app.services.pipeline_service import process_search_results

processed = await process_search_results(
    execution_result,
    SearchFilters(min_seeders=5),
    ScoringPreferences(preferred_qualities=["1080p"]),
    SearchSort.SCORE_DESC,
)
```

### Regras do processamento de domínio

- Campos explícitos de provider têm prioridade; inferências vêm somente do título ou de payloads de tamanho conhecidos. O payload original permanece em `raw_data`.
- `4K` e `UHD` tornam-se `2160p`; `Dublado` isolado torna-se `Dubbed`; `Original` não é convertido para `English`; `BDRip`, `BRRip` e `BluRay` permanecem distintos.
- `None` em tamanho exclui o resultado quando há limite de tamanho configurado. `None` em seeders exclui quando `min_seeders` está configurado.
- Filtros são OR dentro da categoria e AND entre categorias. A ordenação é estável e coloca valores desconhecidos por último.
- Deduplicação fraca é conservadora e pode ser desabilitada com `allow_weak_dedup=False` no pipeline. Conflitos de tamanho ficam em `deduplication_warnings`.
- O scoring não assume idioma preferido, limita a contribuição de seeders por `seeders_cap`, aplica penalidades configuráveis e explica cada componente em `score_breakdown`.
- A Fase 3 não adiciona persistência nem migration.

## Interface de busca

As rotas públicas da Fase 4 são:

| Rota | Uso |
| --- | --- |
| `GET /` | Página principal com formulário e estado inicial |
| `GET /search` | Busca HTMX ou HTML completo quando chamada diretamente |
| `GET /search/history` | Histórico paginado do SQLite |
| `GET /search/result/{result_token}` | Detalhes temporários de um resultado |

O formulário envia `query`, providers repetidos, filtros, `sort_by` e `weak_deduplication` por `GET`. Filtros vazios não restringem a busca. Temporada e episódio só são aceitos para séries e anime.

O resultado usa tabela no desktop e cards no celular. O endpoint retorna métricas de brutos, normalizados, deduplicados e filtrados, além dos erros parciais dos providers. O detalhe usa HTMX e mostra hash/magnet abreviados; o magnet completo e `raw_data` nunca são renderizados.

### Tokens e histórico

Cada resultado recebe um token aleatório `secrets.token_urlsafe` armazenado somente em memória. Os tokens expiram após `SEARCH_RESULT_TOKEN_TTL_SECONDS`, são removidos de forma lazy e respeitam `SEARCH_RESULT_STORE_MAX_ITEMS`. Reiniciar o processo invalida todos os tokens.

O histórico armazena apenas query, tipo, providers, filtros normalizados, quantidade de resultados, duração e data. Magnets, hashes, tokens, `raw_data` e credenciais não são persistidos.

O volume persistente esperado em produção é:

```text
/opt/appdata/media-finder:/config
```

Antes da primeira subida, crie o diretório no host e atribua a ele acesso de escrita para `uid/gid 1000`, ou aplique uma ACL equivalente:

```bash
sudo install -d -o 1000 -g 1000 /opt/appdata/media-finder
```

O entrypoint aceita outros valores positivos por meio de `PUID` e `PGID`. Ele ajusta o usuário interno, garante a posse de `/config`, executa as migrations e inicia o Uvicorn com `gosu` usando o UID/GID configurado. O processo da aplicação não permanece como root.

O banco ficará em `/config/media-finder.db` dentro do container, ou seja, em `/opt/appdata/media-finder/media-finder.db` no host.

## Integração com qBittorrent

As rotas da Fase 5 são:

| Rota | Uso |
| --- | --- |
| `POST /downloads` | Envia um resultado temporário usando somente `result_token`, `paused` e `csrf_token` |
| `GET /downloads` | Histórico local paginado |
| `GET /downloads/{download_id}/status` | Atualiza o status pelo hash armazenado localmente |
| `GET /qbittorrent/health` | Health autenticado e seguro, sem credenciais |
| `GET /qbittorrent/categories` | Categorias encontradas e capacidades configuradas |

O mapeamento fica no ambiente e, no Compose de exemplo, é:

```text
movie  → movies
series → series
anime  → (desabilitado)
other  → (desabilitado)
```

As categorias `movies` e `series` precisam existir no qBittorrent. Nenhuma categoria é criada automaticamente e nenhum `save_path` é enviado pelo Media Finder; os caminhos físicos permanecem sob responsabilidade do qBittorrent. Anime e other exibem `Category not configured` e não podem ser enviados.

O fluxo é idempotente: o info hash é normalizado, o histórico local e o qBittorrent são consultados antes do envio, e uma repetição retorna `duplicate`. Tags limitadas e sanitizadas seguem o formato `media-finder`, `provider:<slug>`, `type:<media_type>`, `quality:<quality>` e `language:<language>`.

O magnet completo fica apenas no resultado temporário em memória durante o fluxo. `download_history.magnet_url` permanece `NULL`; hashes são persistidos para consulta de status. O cookie de sessão usa `SameSite=Lax`, `HttpOnly` e um token CSRF aleatório comparado em tempo constante. Em produção, `APP_SECRET_KEY` precisa ter pelo menos 32 caracteres e não pode usar o placeholder do exemplo.

## Configuração

Copie [`.env.example`](.env.example) para `.env` em desenvolvimento. Em produção, injete as variáveis no Compose ou no ambiente do container. Nenhuma credencial é hardcoded.

Principais variáveis:

| Variável | Padrão | Uso |
| --- | --- | --- |
| `APP_ENV` | `production` | Badge visual do ambiente |
| `APP_HOST` | `0.0.0.0` | Interface de escuta |
| `APP_PORT` | `8091` | Porta HTTP |
| `PUID` | `1000` | UID do processo e proprietário de `/config` |
| `PGID` | `1000` | GID do processo e proprietário de `/config` |
| `DATABASE_URL` | `sqlite:////config/media-finder.db` | Local do SQLite |
| `SEARCH_QUERY_MIN_LENGTH` | `2` | Tamanho mínimo da query |
| `SEARCH_QUERY_MAX_LENGTH` | `200` | Tamanho máximo da query |
| `SEARCH_MAX_PROVIDERS` | `10` | Providers por busca |
| `SEARCH_PROVIDER_TIMEOUT_SECONDS` | `5` | Timeout individual de provider |
| `SEARCH_RESULT_TOKEN_TTL_SECONDS` | `900` | TTL do detalhe temporário |
| `SEARCH_RESULT_STORE_MAX_ITEMS` | `2000` | Limite de resultados em memória |
| `SEARCH_RATE_LIMIT_REQUESTS` | `20` | Buscas permitidas por janela/IP |
| `SEARCH_RATE_LIMIT_WINDOW_SECONDS` | `60` | Janela do rate limit |
| `SEARCH_HISTORY_PAGE_SIZE` | `25` | Registros por página do histórico |
| `PROVIDER_RATE_LIMIT_REQUESTS` | `20` | Chamadas por provider na janela |
| `PROVIDER_RATE_LIMIT_WINDOW_SECONDS` | `60` | Janela do rate limit de providers |
| `PROVIDER_CACHE_MAX_ITEMS` | `512` | Máximo de resultados normalizados em cada cache |
| `APP_SECRET_KEY` | obrigatório em produção | Chave da sessão/CSRF; gere com `openssl rand -hex 32` |
| `QBITTORRENT_URL` | `http://qbittorrent:8080` | Endpoint do qBittorrent |
| `QBITTORRENT_CATEGORY_MOVIE` | `movies` | Categoria usada por filmes |
| `QBITTORRENT_CATEGORY_SERIES` | `series` | Categoria usada por séries |
| `QBITTORRENT_CATEGORY_ANIME` | vazio | Anime permanece desabilitado por padrão |
| `QBITTORRENT_CATEGORY_OTHER` | vazio | Outros permanecem desabilitados por padrão |
| `QBITTORRENT_CONNECT_TIMEOUT_SECONDS` | `5` | Timeout de conexão/autenticação |
| `QBITTORRENT_OPERATION_TIMEOUT_SECONDS` | `15` | Timeout das operações |
| `QBITTORRENT_HEALTH_TIMEOUT_SECONDS` | `5` | Timeout do health |
| `SONARR_URL` | `http://sonarr:8989` | Endpoint futuro do Sonarr |
| `RADARR_URL` | `http://radarr:7878` | Endpoint futuro do Radarr |
| `PROWLARR_ENABLED` | `true` | Registra o Prowlarr no registry |
| `PROWLARR_URL` | `http://prowlarr:9696` | Endpoint HTTP do Prowlarr |
| `PROWLARR_API_KEY` | vazio | Chave enviada somente no header `X-Api-Key` |
| `PROWLARR_TIMEOUT_SECONDS` | `15` | Timeout das chamadas Prowlarr |
| `PROWLARR_MAX_RESULTS` | `200` | Limite de resultados Prowlarr |
| `PROWLARR_CACHE_TTL_SECONDS` | `60` | TTL do cache Prowlarr |
| `PROWLARR_MAX_CONCURRENCY` | `3` | Concorrência máxima Prowlarr |
| `JACKETT_ENABLED` | `true` | Registra o Jackett no registry |
| `JACKETT_URL` | `http://jackett:9117` | Endpoint HTTP do Jackett |
| `JACKETT_API_KEY` | vazio | Chave necessária para Torznab |
| `JACKETT_TIMEOUT_SECONDS` | `20` | Timeout das chamadas Jackett |
| `JACKETT_MAX_RESULTS` | `200` | Limite de resultados Jackett |
| `JACKETT_CACHE_TTL_SECONDS` | `60` | TTL do cache Jackett |
| `JACKETT_MAX_CONCURRENCY` | `3` | Concorrência máxima Jackett |
| `JACKETT_INDEXERS` | `all` | Agregador ou lista de indexadores separados por vírgula |
| `TORRENT_INDEXER_URL` | `http://torrent-indexer:7006` | Endpoint futuro do indexador local |

As API keys e credenciais devem ser fornecidas pelo ambiente, nunca pelo código-fonte.

## Desenvolvimento sem Docker

A aplicação requer Python 3.12 ou superior.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
export DATABASE_URL=sqlite:///./media-finder.db
alembic upgrade head
uvicorn app.main:app --reload --port 8091
```

## Banco e migrations

O entrypoint executa `alembic upgrade head` antes de iniciar o Uvicorn. Para executar manualmente:

```bash
alembic upgrade head
alembic current
```

O SQLite é persistido no volume `/config`. Um backup seguro deve ser feito com o serviço parado, ou usando o mecanismo de backup online do SQLite antes de copiar o arquivo. Para a primeira operação simples:

```bash
docker compose stop media-finder
cp /opt/appdata/media-finder/media-finder.db /opt/appdata/media-finder/media-finder.db.backup
docker compose start media-finder
```

O modo WAL e o backup online serão tratados na fase de robustez/observabilidade, antes da entrega final.

## Qualidade

```bash
ruff check .
ruff format --check .
pytest
```

## Limitações desta fase

- O armazenamento de tokens e o rate limit são locais ao processo; múltiplas réplicas exigirão uma camada compartilhada futura.
- Prowlarr e Jackett dependem de instâncias e indexadores configurados pelo usuário; testes reais são somente de leitura.
- A integração é somente com qBittorrent; Sonarr e Radarr ainda não foram implementados.
- Não há automação de importação nem integrações Sonarr/Radarr/Jellyfin.
- Não há pause/resume/delete de torrents, alteração de categoria ou remoção de arquivos.
- Não há integração Arr, Torrentio ou MediaFusion.

## Uso autorizado

O aplicativo deve ser usado somente com fontes, conteúdos e credenciais que o usuário esteja autorizado a acessar. O Media Finder não move arquivos e não substitui o Sonarr ou o Radarr na organização da biblioteca.
