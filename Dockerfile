FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["python", "-m", "home_atlas.interfaces.mcp_server"]
