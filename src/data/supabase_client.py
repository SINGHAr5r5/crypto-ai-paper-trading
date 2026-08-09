"""Runs SQL against the Supabase project via the Management API's database/query
endpoint. Used instead of a direct Postgres driver so the backfill script has no
extra dependencies beyond `requests` — swap for psycopg2/asyncpg once the worker
service is actually built.
"""

import os

import requests

PROJECT_REF = "fanjxckcjfghvxsubwey"
QUERY_URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"


def run_sql(sql: str) -> list[dict]:
    token = os.environ["SUPABASE_ACCESS_TOKEN"]
    resp = requests.post(
        QUERY_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()
