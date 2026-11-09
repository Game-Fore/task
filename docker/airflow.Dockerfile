FROM apache/airflow:2.10.5-python3.12

# код пайплайна живёт в своём venv, чтобы его зависимости не конфликтовали с зависимостями Airflow
USER root
RUN mkdir -p /opt/pipeline-venv /opt/pipeline /opt/airflow/ml_models \
    && chown -R airflow: /opt/pipeline-venv /opt/pipeline /opt/airflow/ml_models
USER airflow

COPY requirements.txt /opt/pipeline/
RUN python -m venv /opt/pipeline-venv \
    && PIP_USER=false /opt/pipeline-venv/bin/pip install --no-cache-dir -r /opt/pipeline/requirements.txt

COPY common/ /opt/pipeline/common/
COPY etl/ /opt/pipeline/etl/
COPY ml/ /opt/pipeline/ml/
COPY sql/ /opt/pipeline/sql/
COPY dags/ /opt/airflow/dags/
COPY docker/airflow_init.sh /opt/airflow/airflow_init.sh
