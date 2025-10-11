# Base Python nhẹ nhất có hỗ trợ pip
FROM python:3.10-slim

# Đặt thư mục làm việc
WORKDIR /app

# Copy toàn bộ mã nguồn
COPY . .

# Cài thư viện
RUN pip install --no-cache-dir -r requirements.txt

# Mở port giả (Render yêu cầu)
EXPOSE 10000

# Giữ bot sống bằng cách chạy web server + bot song song
CMD ["sh", "-c", "python bot.py & python -m http.server 10000"]
