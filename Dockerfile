FROM python:3.11-slim

WORKDIR /app

# Install dependencies from bybit-bot folder
COPY bybit-bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Bybit bot application files
COPY bybit-bot/*.py ./
COPY bybit-bot/templates/ ./templates/

RUN mkdir -p /data/bybit-bot

# Run the application
CMD ["python", "main.py"]
