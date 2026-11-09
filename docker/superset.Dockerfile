FROM apache/superset:4.1.1

USER root
RUN pip install --no-cache-dir psycopg2-binary==2.9.10
COPY docker/superset/superset_config.py /app/pythonpath/superset_config.py
COPY docker/superset/superset_init.sh /app/superset_init.sh
COPY bi/market_rates/ /app/dashboard_bundle/
USER superset
