FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Зависимости отдельным слоем: правки кода не инвалидируют кэш pip install.
COPY requirements.txt .
RUN pip install -r requirements.txt

RUN useradd --create-home --uid 1000 app

COPY pyproject.toml .
COPY docker/run_pipeline.sh .
COPY common/ common/
COPY etl/ etl/
COPY sql/ sql/
COPY tests/ tests/

USER app

CMD ["sh", "run_pipeline.sh"]
