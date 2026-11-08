FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# пустой volume при первом монтировании берёт владельца каталога из образа
RUN useradd --create-home --uid 1000 app && mkdir /app/models && chown app:app /app/models

COPY pyproject.toml .
COPY docker/run_pipeline.sh .
COPY common/ common/
COPY etl/ etl/
COPY ml/ ml/
COPY sql/ sql/
COPY tests/ tests/

USER app

CMD ["sh", "run_pipeline.sh"]
