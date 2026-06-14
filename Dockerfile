# syntax=docker/dockerfile:1.7
FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; open('/tmp/requirements.txt', 'w').write('\n'.join(deps))" \
    && pip install -r /tmp/requirements.txt

COPY . .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps .

EXPOSE 8080

CMD ["python", "-m", "home_atlas.interfaces.mcp_server"]
