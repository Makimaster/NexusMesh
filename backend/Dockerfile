FROM python:3.13-slim

WORKDIR /app

# 安装 uv
RUN pip install --no-cache-dir uv

# 复制依赖文件
COPY pyproject.toml .

# 生产环境安装（不含 dev 依赖）
RUN uv sync --no-dev

# 复制应用代码
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini .

# 非 root 用户运行
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
