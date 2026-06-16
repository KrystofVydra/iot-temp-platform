FROM python:3.12-slim

RUN pip install --no-cache-dir asyncpg

COPY backfill.py /backfill.py

# ENTRYPOINT so CLI args pass through:
#   docker run --rm --network coolify -e DATABASE_URL=... backfill \
#       --gateway-key warehouse-01 --controller-sn 4876 --node-count 3
ENTRYPOINT ["python", "/backfill.py"]
CMD ["--help"]
