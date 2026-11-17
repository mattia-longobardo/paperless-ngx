# AGENTS.md — paperless-ngx (homelab fork)

Git, PR and deploy rules: skill `git-policy`. Here only the data of this repo and the exceptions.

## Coding hygiene

Follow skill `coding-hygiene` and the "Coding hygiene" section of `/home/mattia/docker/AGENTS.md` (HARD rules, defaults, end-of-task checklist).

## Repo

- Fork of `paperless-ngx/paperless-ngx`. Do not open PRs and do not push to `upstream`. With `gh`, always give `-R mattia-longobardo/paperless-ngx`.
- Production branch: `main`, that is upstream `main` plus the local patches. GitHub Actions is disabled.
- Local patches: OpenAI Responses API (`PAPERLESS_AI_LLM_USE_RESPONSES_API`) and OAuth2 for webhooks (`PAPERLESS_WEBHOOK_OAUTH2_*`).
- Rollback to 3.2.1: branch `local/v3.2.1-responses` in the bundle `~/.local/share/git-bundles/pers-186-paperless/paperless-ngx.bundle` on the server. The image `paperless-ngx-homelab:3.2.1-responses` must be rebuilt from this branch.
- Service: `paperless-ngx`, in the Homelab `storage/` stack. The live checkout is `storage/paperless-ngx/homelab`.
- Remote `upstream`: only `main` and no tags. Configuration: `git remote add -t main upstream <url>` and `git config remote.upstream.tagOpt --no-tags`.
- Tag filter per service: not necessary.
- Work across more runs on `main`: not necessary.

## Update to a new upstream version

Use a merge of the upstream release. Do not use rebase and do not use force push.

1. Run `git fetch upstream refs/tags/vX.Y.Z`.
2. Run `git merge --no-ff -m "chore: merge upstream vX.Y.Z" FETCH_HEAD`.
3. In `Dockerfile.homelab`, update the `FROM` tag to `X.Y.Z`.
4. Run the tests, then push to `main`.
5. After the deploy, create the tag `vX.Y.Z` on the `main` commit.

## Tests

Run the full suite in a container of the image, without `PNGX_CONTAINERIZED`: with this variable `test_system_status` fails.

1. Start Tika, Gotenberg, Greenmail and nginx in the same network namespace, with `--network container:<tika>`. The versions are in `docker/compose/docker-compose.ci-test.yml`.
2. Run `uv sync --frozen --group testing --python /usr/local/bin/python3`.
3. Run `uv run --frozen --no-sync pytest --numprocesses=4 --no-cov`.

## Critical or shared code

A file in this list starts the full suite:

- Data: `src/*/migrations/`
- Local patches: `Dockerfile.homelab`, `src/paperless/config.py`, `src/paperless/settings/__init__.py`, `src/paperless_ai/client.py`, `src/documents/workflows/webhooks.py`
- Dependencies: `pyproject.toml`, `uv.lock`

## Deploy

- Host: Homeserver.
- Lock: `flock -n /var/lock/deploy-paperless-ngx.lock <command>`
- Build: `docker build -f Dockerfile.homelab -t paperless-ngx-homelab:<version>-responses .`
- Command, from Homelab `storage/`: `docker compose up -d --no-build --no-deps --wait --wait-timeout 300 paperless-ngx`
- Active version: `docker inspect paperless-ngx -f '{{.Image}}'`
- The image tag is in Homelab `storage/docker-compose.yml`.

## Health check

1. The container is `healthy`, with the expected image ID.
2. `manage.py showmigrations` shows no pending migrations.
3. A real call to `ai_suggestions` answers 200.
4. A real webhook to Ledgerly succeeds. Use a payslip that is already imported, and compare the counts of `documents` and `payslips` in Ledgerly.

## Rollback and notification

- Before a deploy with migrations, stop the service and create the dump in `storage/paperless-ngx/dumps/`, with permissions `600`: `docker exec postgres pg_dump -U paperless -d paperless -Fc`.
- Restore: stop the service, then `pg_restore --clean --if-exists -U paperless -d paperless` inside `postgres`. Put compose and checkout back to the previous version, then run the deploy command and the health check.
- Notification: comment on the issue, which moves to `blocked`.

## Exceptions to the skill

- `git-policy` §5: the upstream commits in the `main` history are not Conventional and contain references. They are not rewritten, to keep the link with upstream. The rule applies to the commits of this fork.
- `git-policy` §4 and §8, squash only: the update to an upstream release uses a merge commit. A squash loses the link with upstream and creates conflicts at the next merge.
- `git-policy` §9.2: the fork tag has the number of the upstream release, not the number calculated from the commits.
