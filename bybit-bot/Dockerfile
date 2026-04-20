FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY templates/ ./templates/

RUN mkdir -p /data/bybit-bot

CMD ["python", "main.py"]
