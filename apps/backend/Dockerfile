FROM python:3.12-slim

WORKDIR /app

# Install system deps for psycopg2, weasyprint, python-docx
RUN apt-get update && apt-get install -y \
    gcc libpq-dev libpango-1.0-0 libpangoft2-1.0-0 \
    libharfbuzz0b libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv --no-cache-dir

# Copy dependency files first (Docker layer caching)
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen

# Playwright's Chromium is only needed for the legislation.gov.au scraper
# (an Angular SPA the public OData API doesn't serve document bytes for), run
# out-of-band via the ingest job, not per API request. --with-deps pulls in
# its own apt packages, which is a real memory/build-time cost on the small
# production droplet (already needed a swapfile just for image builds).
RUN uv run playwright install --with-deps chromium

# Copy application code
COPY src/ ./src/

# Doppler injects all env vars at runtime - no .env file needed
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "taxflow.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
