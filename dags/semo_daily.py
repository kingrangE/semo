"""Airflow 3: collect public Sejong calendar and notices every day at 06:00 KST."""

from datetime import timedelta

import pendulum
from airflow.sdk import dag, task


@dag(
    dag_id="semo_daily",
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 10, 29, tz="Asia/Seoul"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["semo"],
)
def semo_daily():
    @task(execution_timeout=timedelta(hours=2))
    def collect_public_html():
        import os
        import subprocess
        import sys
        from pathlib import Path

        project = Path(__file__).resolve().parents[1]
        subprocess.run(
            [
                sys.executable,
                str(project / "daily_collect.py"),
                "--output",
                os.environ.get("SEMO_DATA_DIR", str(project / "artifacts/daily")),
            ],
            check=True,
        )

    @task(execution_timeout=timedelta(hours=1))
    def index_documents():
        import os
        import subprocess
        import sys
        from pathlib import Path

        from airflow.exceptions import AirflowSkipException

        if not os.environ.get("OPENAI_API_KEY"):
            raise AirflowSkipException(
                "OPENAI_API_KEY is not configured; collection remains available"
            )
        project = Path(__file__).resolve().parents[1]
        subprocess.run(
            [sys.executable, "-m", "semo.index_cli"], cwd=project, check=True
        )

    collect_public_html() >> index_documents()


semo_daily()
