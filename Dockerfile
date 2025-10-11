FROM python:3.10-slim

WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

# Fake port cho Render Free
EXPOSE 10000

# Chạy bot nền + server giả để Render không tắt
CMD ["sh", "-c", "python bot.py & python -m http.server 10000"]
