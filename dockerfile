FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаём папку instance (для SQLite) на случай, если volume не смонтируется
RUN mkdir -p /app/instance

EXPOSE 5000

CMD ["python", "run.py"]