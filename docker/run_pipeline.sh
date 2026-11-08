#!/usr/bin/env sh
# Полный прогон пайплайна (команда сервиса pipeline). Каждый шаг идемпотентен,
# поэтому повторный `docker-compose up` безопасен; при ошибке шага прогон останавливается.
set -eu

python -m etl migrate
python -m etl load
