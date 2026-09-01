# Microsoft official Playwright Python image (সব ডিপেন্ডেন্সি অলরেডি ইনস্টল থাকে)
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

WORKDIR /app

# Packages install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code copy
COPY . .

# Start Server
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
