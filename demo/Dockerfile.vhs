# VHS terminal renderer plus a Postgres client, so tapes can run psql against the local stack.
FROM ghcr.io/charmbracelet/vhs:latest
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends postgresql-client ca-certificates curl >/dev/null \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /vhs
