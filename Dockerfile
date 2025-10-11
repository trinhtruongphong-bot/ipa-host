FROM python:3.10-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

EXPOSE 10000
CMD ["sh", "-c", "python bot.py & python -m http.server 10000"]
