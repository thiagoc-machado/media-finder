# Media Finder

Base de um painel web para pesquisar mídia em fontes autorizadas pelo usuário, comparar resultados e enviar torrents ao qBittorrent. Esta entrega fecha o MVP nas **Fases 1 a 9**: catálogo TMDB, resolução de IMDb, busca concorrente em providers, filtros, deduplicação, qBittorrent e histórico.

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
- Provider mock determinístico disponível somente nas fixtures de teste; o runtime oferece exclusivamente providers reais configurados.
- Provider opcional DuckDuckGo em modo somente leitura para testes acadêmicos de pesquisa pública `site:drive.google.com`; somente PDFs e `.torrent` são aceitos. PDFs podem ser salvos em `/books` e torrents são enviados ao qBittorrent.
- `SearchService` com execução concorrente, timeout por provider e erros parciais estruturados.
- Endpoint JSON `GET /providers/health` para providers habilitados.
- Contratos `SearchFilters`, `SearchSort`, `ScoringPreferences` e `ProcessedSearchResult`.
- Parser determinístico de release, tamanho e magnet/info hash sem chamadas externas.
- Normalização baseada em evidência, deduplicação forte por hash e fraca opcional por título/tamanho/qualidade.
- Filtros AND entre categorias e OR dentro de cada categoria, ordenação estável e scoring explicável/configurável.
- Pipeline assíncrono `process_search_results` com métricas por etapa e preservação de erros dos providers.
- Interface completa de busca com Jinja2, HTMX local, filtros, ordenação, loading, estados vazios e layout desktop/mobile.
- Rotas `/search`, `/search/history` e `/search/result/{result_token}`.
- Rota `/files` separada para localizar PDFs e `.torrent` públicos sem misturar a busca de mídia.
- Histórico SQLite com paginação e somente metadados não sensíveis.
- Tokens aleatórios temporários em memória, TTL, limite de armazenamento e rate limit por IP.
- Integração real com qBittorrent usando `qbittorrent-api`, autenticação reutilizável, timeouts e chamadas fora do event loop.
- Integrações reais opcionais com Prowlarr e Jackett, usando APIs oficiais, indexadores selecionáveis, cache curto, rate limit, timeouts e normalização comum.
- Integrações opcionais com addons Stremio Torrentio e MediaFusion por manifest e stream resources, com cliente genérico, limites de resposta, redirects revalidados, proteção SSRF, cache, concorrência e status seguro.
- Resultados Stremio normalizados para o contrato comum; magnet/hash podem ir para qBittorrent, enquanto streaming HTTP, fontes externas e streams não acionáveis ficam identificados sem download.
- Subfase 8.1: cliente TMDB assíncrono com autenticação Bearer/API key explícita, cache em memória, schemas normalizados, busca multi, detalhes, external IDs, temporadas e partials HTMX.
- Fase 9: estabilização do fluxo completo, presets simples, filtros avançados recolhíveis, validação de categorias antes do envio, status manual e documentação final do MVP.
- Categorias configuráveis somente para `movie → movies` e `series → series`; `anime` e `other` permanecem desabilitados.
- POST `/downloads` protegido por CSRF e baseado exclusivamente em token temporário server-side.
- Histórico paginado de downloads, refresh de status e endpoints de health/categorias do qBittorrent.
- Testes unitários e HTTP para registry, schemas, mock, pipeline, templates, segurança e histórico.
- Testes e configuração do Ruff.

Radarr e Sonarr não possuem clientes ou cadastro automático: reconhecem downloads somente pelas categorias `movies` e `series` quando a mídia correspondente já está monitorada. Cinemeta, Debrid, streaming HTTP, scraping HTML e novos containers continuam fora do escopo.

### Pesquisa acadêmica na web

Para os testes acadêmicos solicitados, o provider usa diretamente a página HTML pública do DuckDuckGo, acrescentando `site:drive.google.com`. O filtro de segurança é aplicado localmente: somente resultados cujo título termina em `.pdf` ou `.torrent` entram no sistema. Não usa API, chave, OAuth ou acesso à API do Drive. PDFs podem ser salvos localmente em `/books` e torrents são enviados ao qBittorrent. O provider não contorna login/CAPTCHA. A extensão do arquivo não prova autorização autoral; a responsabilidade de usar apenas conteúdo autorizado continua sendo do usuário.

```dotenv
DUCKDUCKGO_SEARCH_ENABLED=true
DUCKDUCKGO_SEARCH_TIMEOUT_SECONDS=10
DUCKDUCKGO_SEARCH_MAX_RESULTS=10
```

Para habilitar o armazenamento de PDFs públicos, o Compose monta `/mnt/storage/Livros` do host em `/books` no container. Arquivos `.torrent` públicos são baixados temporariamente e enviados ao qBittorrent. Garanta que a pasta exista e seja gravável pelo `PUID`/`PGID` configurado:

```bash
sudo mkdir -p /mnt/storage/Livros
sudo chown 1000:1000 /mnt/storage/Livros
```

## Arquitetura do MVP (Fases 1 a 9)

```text
Browser
   │
   ▼
FastAPI ── Jinja2 + HTMX local + CSS/JS local
   │
   ├── ProviderRegistry ── SearchProvider Protocol ── Prowlarr / Jackett / Torrentio / MediaFusion
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

O endpoint de health lista somente os providers reais habilitados e configurados:

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

## Providers Stremio: Torrentio e MediaFusion

Os providers Stremio são opcionais e ficam desabilitados por padrão. Cada addon é configurado por sua própria `MANIFEST_URL`; não há instância pública, URL, token ou chave hardcoded. O valor deve ser a URL absoluta do `manifest.json`, sem query, fragmento ou credenciais. O caminho configurado é preservado ao construir `/stream/movie/...` ou `/stream/series/...`.

Variáveis principais:

| Variável | Padrão | Uso |
| --- | --- | --- |
| `TORRENTIO_ENABLED` | `false` | Habilita o adapter Torrentio |
| `TORRENTIO_MANIFEST_URL` | vazio | Manifest configurado pelo usuário |
| `TORRENTIO_TIMEOUT_SECONDS` | `20` | Timeout HTTP |
| `TORRENTIO_CACHE_TTL_SECONDS` | `120` | TTL local de manifest/streams |
| `TORRENTIO_MAX_RESULTS` | `200` | Limite de resultados |
| `TORRENTIO_MAX_CONCURRENCY` | `2` | Concorrência por addon |
| `MEDIAFUSION_ENABLED` | `false` | Habilita o adapter MediaFusion |
| `MEDIAFUSION_MANIFEST_URL` | vazio | Manifest configurado pelo usuário |
| `MEDIAFUSION_TIMEOUT_SECONDS` | `20` | Timeout HTTP |
| `MEDIAFUSION_CACHE_TTL_SECONDS` | `120` | TTL local de manifest/streams |
| `MEDIAFUSION_MAX_RESULTS` | `200` | Limite de resultados |
| `MEDIAFUSION_MAX_CONCURRENCY` | `2` | Concorrência por addon |
| `STREMIO_ADDON_MAX_RESPONSE_BYTES` | `5242880` | Tamanho máximo de resposta |
| `STREMIO_ADDON_MAX_REDIRECTS` | `2` | Redirects permitidos e revalidados |
| `STREMIO_ADDON_ALLOWED_SCHEMES` | `http,https` | Schemes aceitos |
| `STREMIO_ADDON_ALLOW_PRIVATE_HOSTS` | `false` | Exceção explícita para hosts privados |

A busca desses addons exige um IMDb ID resolvido no formato `tt` seguido de 7 a 10 dígitos. Não existe lookup TMDB, busca textual ou tentativa de adivinhar o ID. Filmes usam `/stream/movie/tt1234567.json`; séries usam `/stream/series/tt1234567:1:2.json`. MediaFusion aceita somente filme e série e ignora entradas live/HLS.

O cliente aceita resources e aliases comuns do protocolo Stremio, mas consome somente manifest e stream resources. `sources` do tipo `tracker:http(s)/udp` entram no magnet; `dht:` é ignorado. O campo `url` não é baixado nem seguido: URL HTTP vira `http_stream`, `externalUrl`/`ytId` vira `external` e respostas sem ação ficam `unsupported`. A UI mostra essa capability e só habilita qBittorrent para `magnet` ou `info_hash`.

As rotas de observabilidade são `GET /providers/torrentio/status`, `GET /providers/mediafusion/status` e o agregado `GET /providers/health`. Status nunca retorna a URL do manifest. A proteção SSRF bloqueia hosts privados, loopback, link-local, metadados, redirects para outro host e componentes de URL inseguros, salvo quando a exceção é habilitada explicitamente.

Quando Torrentio/MediaFusion e Prowlarr/Jackett retornam o mesmo hash, a deduplicação mantém todos os providers, trackers únicos, o maior número conhecido de seeders e a capability mais forte, nesta ordem: `magnet`, `info_hash`, `http_stream`, `external`, `unsupported`.

## Subfase 8: catálogo TMDB e resolução guiada

O catálogo TMDB desta entrega é uma camada de resolução independente da busca de releases. As rotas são:

| Rota | Uso |
| --- | --- |
| `GET /metadata/search?query=...&media_type=all` | Busca candidatos de filmes e séries em partial HTMX |
| `GET /metadata/select/{candidate_token}` | Seleciona um candidato temporário e resolve o IMDb ID no backend |
| `GET /metadata/series/{resolved_token}/season/{season_number}` | Lista episódios de uma temporada resolvida |
| `GET /search/resolved?resolved_media_token=...` | Executa a busca existente com título, TMDB ID, IMDb ID e episódio validados |
| `GET /metadata/tmdb/health` | Health leve de autenticação/configuração, sem busca ampla |
| `GET /metadata/tmdb/movie/{tmdb_id}` | Detalhes de filme e external IDs |
| `GET /metadata/tmdb/series/{tmdb_id}` | Detalhes de série e temporadas |
| `GET /metadata/tmdb/{tmdb_id}/season/{season_number}` | Episódios normalizados de uma temporada |

`TMDB_AUTH_MODE=bearer` envia a credencial somente no header `Authorization`; `TMDB_AUTH_MODE=api_key` envia o parâmetro oficial `api_key`. A chave nunca é colocada no frontend, logs, SQLite ou mensagens de erro. HTTPS é obrigatório por padrão; HTTP exige `TMDB_ALLOW_HTTP=true` ou ambiente de teste.

Resultados `person` e adultos são descartados. Textos são limpos e limitados, datas inválidas tornam-se `None`, candidatos mantêm a ordem de relevância e imagens são construídas exclusivamente de `TMDB_IMAGE_BASE_URL` mais paths TMDB validados. Não há proxy de imagens nem URLs arbitrárias.

No modo simples, o navegador envia apenas o texto para o TMDB e, depois da seleção, um token temporário de candidato. O backend consulta novamente detalhes e external IDs, exige um IMDb no formato `tt` seguido de 7 a 10 dígitos e guarda o objeto resolvido somente em memória. Tokens têm TTL, namespaces separados, limite de itens e cópia defensiva; reiniciar o container limpa esse estado.

Filmes seguem diretamente para os releases. Séries exibem somente temporadas válidas e consultam os episódios no TMDB antes de aceitar a busca. `METADATA_SHOW_SPECIALS=false` oculta a season 0 por padrão; habilite explicitamente apenas quando desejar incluir specials. A busca avançada manual continua disponível e mantém o suporte a IMDb, temporada, episódio, providers, filtros, scoring, deduplicação e ordenação.

O histórico registra a resolução de forma limitada em `filters_json` (`resolved_media`, título, TMDB ID, IMDb ID e, quando aplicável, temporada/episódio), sem tokens, chave da API ou payload bruto. Cinemeta, fallback de metadados e novos providers permanecem fora do MVP.

## Interface de busca

As rotas públicas da Fase 4 são:

| Rota | Uso |
| --- | --- |
| `GET /` | Página principal com formulário e estado inicial |
| `GET /search` | Busca HTMX ou HTML completo quando chamada diretamente |
| `GET /search/history` | Histórico paginado do SQLite |
| `GET /search/result/{result_token}` | Detalhes temporários de um resultado |

O formulário envia `query`, providers repetidos, filtros, `sort_by` e `weak_deduplication` por `GET`. Filtros vazios não restringem a busca. Temporada e episódio só são aceitos para séries e anime.

O resultado usa tabela no desktop e cards no celular. O endpoint retorna métricas de brutos, normalizados, deduplicados e filtrados, além dos erros parciais dos providers. O detalhe usa HTMX e mostra hash/magnet abreviados; o magnet completo e `raw_data` nunca são renderizados. Idioma, qualidade, tamanho máximo, seeders mínimos, ordenação e providers ficam no primeiro nível; codec, source type, tracker, termos, deduplicação fraca e indexadores ficam em `Advanced filters`. Os presets `PT-BR 1080p`, `Castellano 1080p` e `Best available` apenas preenchem os filtros no navegador.

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
| `TMDB_ENABLED` | `true` | Habilita o catálogo TMDB; sem chave fica indisponível sem impedir o boot |
| `TMDB_AUTH_MODE` | `bearer` | `bearer` ou `api_key` |
| `TMDB_BASE_URL` | `https://api.themoviedb.org/3` | Origem da API TMDB |
| `TMDB_IMAGE_BASE_URL` | `https://image.tmdb.org/t/p` | Origem configurada para imagens TMDB |
| `TMDB_LANGUAGE` | `pt-BR` | Idioma solicitado ao TMDB |
| `TMDB_REGION` | `ES` | Região solicitada ao TMDB |
| `TMDB_TIMEOUT_SECONDS` | `10` | Timeout das chamadas TMDB |
| `TMDB_CACHE_TTL_SECONDS` | `3600` | TTL do cache TMDB |
| `TMDB_MAX_RESULTS` | `20` | Limite de candidatos |
| `TMDB_MAX_CONCURRENCY` | `3` | Concorrência máxima TMDB |
| `TMDB_ALLOW_HTTP` | `false` | Exceção explícita para testes/ambientes controlados |
| `METADATA_SEARCH_MIN_LENGTH` | `2` | Tamanho mínimo do título |
| `METADATA_SEARCH_MAX_LENGTH` | `200` | Tamanho máximo do título |
| `METADATA_RESULT_STORE_MAX_ITEMS` | `1000` | Limite de cache de metadados |
| `METADATA_RESULT_TOKEN_TTL_SECONDS` | `900` | TTL dos tokens temporários de candidatos e mídia resolvida |
| `METADATA_RATE_LIMIT_REQUESTS` | `30` | Chamadas de metadata por janela |
| `METADATA_RATE_LIMIT_WINDOW_SECONDS` | `60` | Janela do rate limit de metadata |
| `METADATA_SHOW_SPECIALS` | `false` | Inclui explicitamente a season 0 no fluxo de séries |
| `APP_SECRET_KEY` | obrigatório em produção | Chave da sessão/CSRF; gere com `openssl rand -hex 32` |
| `QBITTORRENT_URL` | `http://qbittorrent:8080` | Endpoint do qBittorrent |
| `QBITTORRENT_CATEGORY_MOVIE` | `movies` | Categoria usada por filmes |
| `QBITTORRENT_CATEGORY_SERIES` | `series` | Categoria usada por séries |
| `QBITTORRENT_CATEGORY_ANIME` | vazio | Anime permanece desabilitado por padrão |
| `QBITTORRENT_CATEGORY_OTHER` | vazio | Outros permanecem desabilitados por padrão |
| `QBITTORRENT_CONNECT_TIMEOUT_SECONDS` | `5` | Timeout de conexão/autenticação |
| `QBITTORRENT_OPERATION_TIMEOUT_SECONDS` | `15` | Timeout das operações |
| `QBITTORRENT_HEALTH_TIMEOUT_SECONDS` | `5` | Timeout do health |
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

As API keys e credenciais devem ser fornecidas pelo ambiente, nunca pelo código-fonte. O `.env.example` contém somente placeholders; variáveis legadas de Cinemeta, Sonarr, Radarr e indexador local não fazem parte do contrato do MVP.

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

Para atualizar, faça backup do arquivo SQLite, baixe as alterações e recrie somente o serviço:

```bash
docker compose stop media-finder
cp /opt/appdata/media-finder/media-finder.db /opt/appdata/media-finder/media-finder.db.backup
docker compose build media-finder
docker compose up -d media-finder
```

O entrypoint executa as migrations antes do boot. Em caso de falha, consulte `docker compose logs media-finder`, confirme a permissão UID/GID 1000:1000 em `/config` e verifique `/health`.

## Fechamento do MVP

Media Finder sends torrents to qBittorrent. Radarr and Sonarr only import them automatically when the corresponding media is already monitored.

O fluxo fechado é: título → TMDB → IMDb → providers → filtros/deduplicação → resultado elegível → qBittorrent → histórico/status. Filmes usam `movies`; séries usam `series`. O botão de download é desabilitado quando a categoria não existe, qBittorrent está indisponível ou o resultado não possui magnet/hash; quando existe magnet, a UI também oferece `Abrir magnet` diretamente.

Na validação local final, migrations, SQLite, `/health`, healthcheck, UID/GID e ausência de secrets nos logs passaram; o container consumiu aproximadamente 65 MiB em idle. Os providers externos não estavam executando neste workspace, portanto a validação real de Torrentio, MediaFusion, Prowlarr, Jackett e qBittorrent deve ser repetida no Compose do home server.

O MVP não adiciona clientes Radarr/Sonarr, não cadastra mídia, não move arquivos e não altera categorias. Também não implementa Cinemeta, Debrid, streaming HTTP, autenticação avançada, Redis, Celery, PostgreSQL, frontend separado ou novos containers.

## Qualidade

```bash
ruff check .
ruff format --check .
pytest
```

## Limitações desta fase

- O armazenamento de tokens e o rate limit são locais ao processo; múltiplas réplicas exigiriam uma camada compartilhada.
- Prowlarr, Jackett, Torrentio e MediaFusion dependem de instâncias/manifests configurados pelo usuário.
- A integração com Radarr/Sonarr é indireta, por categoria e monitoramento existente.
- Não há pause/resume/delete de torrents, alteração de categoria ou remoção de arquivos.
- Torrentio e MediaFusion estão limitados ao contrato Stremio descrito acima; Debrid e streaming HTTP não são downloads qBittorrent.

## Uso autorizado

O aplicativo deve ser usado somente com fontes, conteúdos e credenciais que o usuário esteja autorizado a acessar. O Media Finder não move arquivos e não substitui o Sonarr ou o Radarr na organização da biblioteca.
