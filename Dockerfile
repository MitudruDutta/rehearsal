# Rehearsal platform image: API + console + worker in one image (choose the role with the command).
# The worker drives Docker to run application sandboxes, so it needs a Docker daemon it may use:
# give it a dedicated runner host, never the daemon of a machine that runs anything else.

FROM node:22-bookworm-slim AS console
WORKDIR /src/web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
# public contact for the landing page ("Talk to us"), baked into the static console: --build-arg NEXT_PUBLIC_CONTACT_EMAIL=...
ARG NEXT_PUBLIC_CONTACT_EMAIL="" NEXT_PUBLIC_CONTACT_URL=""
# where the landing page's "Docs" link leads: the address of the documentation site (docs/). Empty: the API reference at /docs
ARG NEXT_PUBLIC_DOCS_URL=""
RUN mkdir -p ../rehearsal/api && pnpm build

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 REHEARSAL_DATA_DIR=/var/lib/rehearsal
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/rehearsal
COPY pyproject.toml ./
COPY PACKAGE.md ./
COPY rehearsal/ rehearsal/
COPY examples/ examples/
# Supabase's public root CA, for REHEARSAL_DATABASE_URL=...?sslmode=verify-full&sslrootcert=/srv/rehearsal/infra/certs/...
COPY infra/certs/ infra/certs/
COPY --from=console /src/rehearsal/api/static rehearsal/api/static
# the client wheel is served at /downloads so users can install the CLI straight from this server
RUN pip install ".[server,telemetry]" && pip wheel --no-deps -w /srv/rehearsal/downloads . \
    && useradd --create-home rehearsal && mkdir -p /var/lib/rehearsal && chown rehearsal /var/lib/rehearsal
ENV REHEARSAL_DOWNLOADS_DIR=/srv/rehearsal/downloads
USER rehearsal
EXPOSE 7800
ENTRYPOINT ["rehearsal"]
CMD ["serve", "--host", "0.0.0.0", "--port", "7800"]
