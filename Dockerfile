FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# jalan sebagai loop 24/7 (scheduler M30 + monitor + telegram-poll)
CMD ["python", "-u", "main.py", "loop"]
