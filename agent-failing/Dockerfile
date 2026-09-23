FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Dependencies are managed in requirements.txt.
COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

COPY main.py ./

# Disable stdout buffering. Unless log lines reach CloudWatch Logs immediately, there is no
# reliable way to tell which invoke produced them.
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "main.py"]
