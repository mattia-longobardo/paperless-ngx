# AGENTS.md — paperless-ngx (fork homelab)

Regole git, PR e deploy: skill `git-policy`. Qui solo i dati di questa repo e le eccezioni.

## Repo

- Fork di `paperless-ngx/paperless-ngx`. Non aprire PR e non fare push verso `upstream`. Con `gh`, indica sempre `-R mattia-longobardo/paperless-ngx`.
- Branch di produzione: `main`, cioè upstream `main` più le patch locali. GitHub Actions è disattivato.
- Patch locali: OpenAI Responses API (`PAPERLESS_AI_LLM_USE_RESPONSES_API`) e OAuth2 per i webhook (`PAPERLESS_WEBHOOK_OAUTH2_*`).
- Rollback a 3.2.1: branch `local/v3.2.1-responses` nel bundle `~/.local/share/git-bundles/pers-186-paperless/paperless-ngx.bundle` del server. L'immagine `paperless-ngx-homelab:3.2.1-responses` va ricostruita da questa branch.
- Servizio: `paperless-ngx`, nello stack `storage/` di Homelab. La checkout live è `storage/paperless-ngx/homelab`.
- Remote `upstream`: solo `main` e nessun tag. Configurazione: `git remote add -t main upstream <url>` e `git config remote.upstream.tagOpt --no-tags`.
- Filtro tag per servizio: non serve.
- Lavoro su più run su `main`: non serve.

## Aggiornamento a una nuova versione upstream

Usa un merge della release upstream. Non usare rebase e non usare force push.

1. Esegui `git fetch upstream refs/tags/vX.Y.Z`.
2. Esegui `git merge --no-ff -m "chore: merge upstream vX.Y.Z" FETCH_HEAD`.
3. In `Dockerfile.homelab`, aggiorna il tag `FROM` a `X.Y.Z`.
4. Esegui i test, poi il push su `main`.
5. Dopo il deploy, crea il tag `vX.Y.Z` sul commit di `main`.

## Test

Esegui la suite completa in un container dell'immagine, senza `PNGX_CONTAINERIZED`: con questa variabile `test_system_status` fallisce.

1. Avvia Tika, Gotenberg, Greenmail e nginx nello stesso network namespace, con `--network container:<tika>`. Le versioni sono in `docker/compose/docker-compose.ci-test.yml`.
2. Esegui `uv sync --frozen --group testing --python /usr/local/bin/python3`.
3. Esegui `uv run --frozen --no-sync pytest --numprocesses=4 --no-cov`.

## Codice critico o condiviso

Un file in questa lista fa partire tutta la suite:

- Dati: `src/*/migrations/`
- Patch locali: `Dockerfile.homelab`, `src/paperless/config.py`, `src/paperless/settings/__init__.py`, `src/paperless_ai/client.py`, `src/documents/workflows/webhooks.py`
- Dipendenze: `pyproject.toml`, `uv.lock`

## Deploy

- Host: Homeserver.
- Lock: `flock -n /var/lock/deploy-paperless-ngx.lock <comando>`
- Build: `docker build -f Dockerfile.homelab -t paperless-ngx-homelab:<versione>-responses .`
- Comando, da `storage/` di Homelab: `docker compose up -d --no-build --no-deps --wait --wait-timeout 300 paperless-ngx`
- Versione attiva: `docker inspect paperless-ngx -f '{{.Image}}'`
- Il tag dell'immagine è in `storage/docker-compose.yml` di Homelab.

## Health check

1. Il container è `healthy`, con l'ID immagine previsto.
2. `manage.py showmigrations` non mostra migrazioni in attesa.
3. Una chiamata reale a `ai_suggestions` risponde 200.
4. Un webhook reale verso Ledgerly riesce. Usa un cedolino già importato, e confronta i conteggi di `documents` e `payslips` in Ledgerly.

## Rollback e notifica

- Prima di un deploy con migrazioni, ferma il servizio e crea il dump in `storage/paperless-ngx/dumps/`, con permessi `600`: `docker exec postgres pg_dump -U paperless -d paperless -Fc`.
- Ripristino: ferma il servizio, poi `pg_restore --clean --if-exists -U paperless -d paperless` dentro `postgres`. Riporta compose e checkout alla versione precedente, poi esegui il comando di deploy e l'health check.
- Notifica: commento sulla issue, che passa in `blocked`.

## Eccezioni alla skill

- `git-policy` §5: i commit upstream nella history di `main` non sono Conventional e contengono riferimenti. Non si riscrivono, per conservare il collegamento con upstream. La regola vale per i commit di questo fork.
- `git-policy` §4 e §8, solo squash: l'aggiornamento a una release upstream usa un merge commit. Uno squash perde il collegamento con upstream e crea conflitti al merge successivo.
- `git-policy` §9.2: il tag del fork ha il numero della release upstream, non il numero calcolato dai commit.
