FROM python:3.11-slim

WORKDIR /app

COPY bybit-bot/requirements.txt .
RUN pip install --no-cache-dir --compile -r requirements.txt

COPY bybit-bot/*.py ./
COPY bybit-bot/templates/ ./templates/

RUN mkdir -p /data/bybit-bot

# Optimize Python memory usage
ENV PYTHONOPTIMIZE=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-u", "main.py"]

