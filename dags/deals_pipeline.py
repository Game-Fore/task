from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.models.param import Param
from airflow.operators.bash import BashOperator

PYTHON = "/opt/pipeline-venv/bin/python"

# по расписанию окно — месяц интервала; при ручном запуске его можно задать в параметрах
START = "{{ params.start_date or data_interval_start | ds }}"
END = "{{ params.end_date or macros.ds_add(data_interval_end | ds, -1) }}"

with DAG(
    dag_id="deals_pipeline",
    schedule="@monthly",
    start_date=pendulum.datetime(2023, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2)},
    params={
        "start_date": Param(None, type=["null", "string"], format="date", title="Начало окна (loading_date)"),
        "end_date": Param(None, type=["null", "string"], format="date", title="Конец окна, включительно"),
    },
    tags=["smart-logistics"],
) as dag:

    def step(task_id: str, command: str) -> BashOperator:
        return BashOperator(task_id=task_id, bash_command=f"{PYTHON} -m {command}", cwd="/opt/pipeline")

    migrate = step("migrate", "etl migrate")
    load = step("load", f"etl load --start-date {START} --end-date {END}")
    mart = step("mart", f"etl mart --start-date {START}")
    ml_train = step("ml_train", "ml train")
    ml_score = step("ml_score", "ml score")

    migrate >> load >> mart >> ml_train >> ml_score
