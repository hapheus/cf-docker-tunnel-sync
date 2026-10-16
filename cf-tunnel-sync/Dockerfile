FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py healthcheck.py cloudflare.py models.py ./
COPY static ./static

EXPOSE 8090

CMD ["python", "app.py"]
