# Backend deployment

This project deploys one authoritative Backend process behind the separately managed Caddy gateway:

```text
Internet
  -> Caddy (HTTPS and access control)
  -> 127.0.0.1:8000
  -> family-spending-backend
       -> ./data bind-mounted at /app/data
```

The Backend has no login system yet. Keep port 8000 bound to loopback and do not expose it directly through a cloud security group.

## 1. Server prerequisites

- Docker Engine with the Docker Compose plugin;
- a host Caddy instance or another HTTPS gateway;
- one Linux user that owns the checkout, `data/`, and `backups/`;
- enough disk space for the active data root and at least one independent backup.

The service must remain a single replica while filesystem persistence is in use. Do not scale the service or run a second writer against the same `data/` directory.

## 2. Prepare configuration and data

From the repository directory on the server:

```bash
cp .env.example .env
id -u
id -g
```

Put those numeric IDs into `PUID` and `PGID` in `.env`. Set the private IMAP address and authorization code only when email polling is enabled. Never commit `.env`.

Transfer the complete canonical data directory while no process is writing the source:

```bash
rsync -a ./data/ user@example-server:/opt/family-spending-backend/data/
ssh user@example-server 'chmod -R u=rwX,go= /opt/family-spending-backend/data'
```

The server copy becomes the only writable production copy after cutover. Do not configure bidirectional synchronization for `data/`.

## 3. Build and start

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 backend
curl --fail http://127.0.0.1:8000/api/v1/health
curl --fail http://127.0.0.1:8000/api/v1/runtime/status
```

The image and dependency graph are built from `uv.lock` with `uv sync --frozen`. The container runs as a non-root user, has a read-only root filesystem, and can write only the bind-mounted data directory and `/tmp`.

## 4. Caddy gateway

Route the Backend hostname or API path to `127.0.0.1:8000`. Preserve the host and forwarding headers and provide HTTPS plus access control at the gateway. Caddy configuration belongs to the independent `eurexis-gateway` project, not this repository.

## 5. Updates

Review storage-schema or parser-version changes before updating. For ordinary code updates:

```bash
git pull --ff-only
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/api/v1/health
```

Compose replaces the container while preserving the host-owned `./data` directory.

## 6. Consistent backups

Mutations may update several files in one logical unit, so stop the Backend around a filesystem backup:

```bash
mkdir -p backups
docker compose stop backend
docker compose run --rm --no-deps \
  -v "$(pwd)/backups:/backups" \
  backend family-spending-admin backup \
  --data-root /app/data \
  --output "/backups/family-spending-$(date +%F-%H%M%S).zip" \
  --parser-version cmb-v1
docker compose start backend
```

Copy backups to separate storage, apply retention, and periodically restore one into a disposable directory. A backup is not a second live writer.

If any backup command fails, inspect the error before restarting the service; do not delete or replace the active data directory as part of routine troubleshooting.
