FROM python:3.12-slim

RUN pip install --no-cache-dir asyncpg

COPY issue-invitation.py /issue-invitation.py

# ENTRYPOINT so positional args (`email [--force]`) pass through directly:
#   docker run --rm --network coolify -e DATABASE_URL=... issue-invite you@example.com
ENTRYPOINT ["python", "/issue-invitation.py"]
