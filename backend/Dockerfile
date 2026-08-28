FROM python:3.12-slim

# 系统依赖（WeasyPrint 需 cairo/pango；psycopg2 已用 binary 免编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装依赖（利用缓存层）
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# 拷贝源码
COPY . .

EXPOSE 8000

# 开发期用 --reload；生产去掉
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
