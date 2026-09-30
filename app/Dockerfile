FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# --workers 1 : 워커 스레드(요리사)가 프로세스마다 생기므로, 프로세스를 1개로 고정해 "요리사 1명"을 보장한다
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
