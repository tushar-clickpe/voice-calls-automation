FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (cache layer)
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy app code
COPY app/ app/
COPY data/ data/

# Create data directory for SQLite
RUN mkdir -p data/uploads

EXPOSE 8000

CMD ["uv", "run", "python", "-m", "app.main"]
