FROM python:3.12-slim

RUN pip install --no-cache-dir asyncpg

COPY backfill.py /backfill.py

CMD ["python", "/backfill.py"]
