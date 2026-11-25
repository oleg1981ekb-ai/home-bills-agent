FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml /app/
COPY src/ /app/src/
RUN pip install --no-cache-dir /app

COPY . /app

CMD ["python", "-m", "home_bills_agent.main"]
