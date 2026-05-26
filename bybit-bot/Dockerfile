FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --compile -r requirements.txt

COPY *.py ./
COPY templates/ ./templates/

RUN mkdir -p /data/bybit-bot

# Optimize Python memory usage
ENV PYTHONOPTIMIZE=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-u", "main.py"]

