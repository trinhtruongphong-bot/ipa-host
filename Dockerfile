FROM python:3.10-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
ENV BOT_TOKEN ""
ENV GITHUB_TOKEN ""
ENV GITHUB_REPO ""
CMD ["python", "bot.py"]
