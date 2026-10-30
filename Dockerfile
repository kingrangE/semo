FROM apache/airflow:3.3.2
COPY requirements.txt /tmp/semo-requirements.txt
RUN pip install --no-cache-dir "apache-airflow==3.3.2" -r /tmp/semo-requirements.txt
COPY --chown=airflow:root daily_collect.py /opt/semo/
COPY --chown=airflow:root semo /opt/semo/semo
COPY --chown=airflow:root dags /opt/semo/dags
RUN mkdir -p /opt/airflow/semo-data
ENV AIRFLOW__CORE__DAGS_FOLDER=/opt/semo/dags
ENV AIRFLOW__CORE__LOAD_EXAMPLES=False
ENV SEMO_DATA_DIR=/opt/airflow/semo-data
