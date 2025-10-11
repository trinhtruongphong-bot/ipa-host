# Sử dụng Python gọn nhẹ
FROM python:3.10-slim

# Thư mục làm việc
WORKDIR /app

# Sao chép file code
COPY . .

# Cài thư viện cần thiết
RUN pip install --no-cache-dir -r requirements.txt

# Mở port giả (Render yêu cầu)
EXPOSE 10000

# Giữ bot sống bằng cách mở server giả + chạy bot song song
CMD ["sh", "-c", "python bot.py & python -m http.server 10000"]
