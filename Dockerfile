########################
# 1️⃣ Builder 镜像
########################
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo

WORKDIR /app

# 编译期依赖（只在 builder 里）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
 && pip install --no-cache-dir --upgrade pip setuptools wheel \
 && rm -rf /var/lib/apt/lists/*

# 只复制依赖定义，利用缓存
COPY requirements.txt ./

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 再复制源码
COPY . .

# 默认环境变量
RUN cp .env.dev.example .env.dev || true

# 清理构建垃圾
RUN find . -name '*.pyc' -delete \
    && find . -name '__pycache__' -type d -exec rm -rf {} +

########################
# 2️⃣ Runtime 镜像
########################
FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo \
    LANG=zh_CN.UTF-8 \
    LC_ALL=zh_CN.UTF-8 \
    HOST=0.0.0.0 \
    PORT=8181 \
    GIT_PYTHON_REFRESH=quiet

WORKDIR /app

# 运行依赖（git + Playwright + 字体 + 图形库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    docker.io \
    locales \
    locales-all \
    fontconfig \
    fonts-noto \
    fonts-noto-color-emoji \
    fonts-unifont \
    fonts-wqy-zenhei \
    libnss3 \
    libxss1 \
    libasound2t64 \
    libxrandr2 \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libgtk-3-0t64 \
    libgbm1 \
    libxshmfence1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libdrm2 \
    libxkbcommon0 \
    libx11-6 \
    libx11-xcb1 \
    libxext6 \
    libxfixes3 \
    libxrender1 \
    libxau6 \
    libxdmcp6 \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
 && rm -rf /var/lib/apt/lists/*

RUN locale-gen zh_CN.UTF-8 || true

# 从 builder 拷依赖和代码
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# 安装 Playwright 浏览器（构建时完成）
RUN python -m playwright install chromium

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh \
    && chmod +x /docker-entrypoint.sh

EXPOSE 8181
EXPOSE 5888

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "bot.py"]
