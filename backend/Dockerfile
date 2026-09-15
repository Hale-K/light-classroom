FROM python:3.12-slim

# 国内构建加速：apt 走腾讯云内网/镜像源
RUN sed -i 's|deb.debian.org|mirrors.cloud.tencent.com|g' /etc/apt/sources.list.d/debian.sources || true

# 系统依赖（WeasyPrint 需 cairo/pango；psycopg2 已用 binary 免编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 国内服务器构建加速：走清华 PyPI 镜像
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 安装依赖（利用缓存层）
COPY pyproject.toml ./
RUN pip install --no-cache-dir filelock "fsspec>=0.8.5" jinja2 networkx "sympy>=1.13.3" typing-extensions setuptools \
    && pip install --no-cache-dir torch==2.14.0+cpu --no-deps --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -e ".[dev]" \
    && pip check

# 拷贝源码
COPY . .

EXPOSE 8000

# 开发期用 --reload；生产去掉
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
