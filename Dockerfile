########################
# 1️⃣ Builder
########################
FROM python:3.10-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo \
    POETRY_HOME=/opt/poetry \
    PATH="/opt/poetry/bin:$PATH"

WORKDIR /app

# 构建期依赖（仅 builder）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
 && python -m pip install --no-cache-dir -U pip \
 && python -m pip install --no-cache-dir "poetry>=1.8,<2.0" \
 && rm -rf /var/lib/apt/lists/*

# 只复制依赖文件，利用缓存
COPY pyproject.toml poetry.lock* ./

# 关键：导出 requirements（不在镜像里保留 poetry 环境）
RUN poetry export -f requirements.txt --without-hashes -o /tmp/requirements.txt

# 追加 nonebot 相关（你之前是 pip 装的，这里保持一致）
# 也把 nonebot-plugin-skland 放进来
RUN printf "\n%s\n" \
    "nonebot2[fastapi,httpx]" \
    "nonebot-adapter-onebot" \
    "nonebot-adapter-qq" \
    "nonebot-plugin-skland" \
    >> /tmp/requirements.txt

# 预编译 wheels（runtime 离线安装，减少层内垃圾与构建工具泄漏）
RUN python -m pip wheel --wheel-dir /wheels -r /tmp/requirements.txt

# Playwright：在 builder 下载浏览器（runtime 不再下载）
# 注意：这里先把 playwright 也 wheel/安装进 builder 的 python 环境，用来执行 install
RUN python -m pip install --no-cache-dir playwright \
 && python -m playwright install chromium

# 再复制源码（放到最后，最大化缓存命中）
COPY . .

# 默认环境变量文件（可选）
RUN cp .env.dev.example .env.dev || true

# 清理源码里的 pyc
RUN find . -name '*.pyc' -delete \
 && find . -name '__pycache__' -type d -exec rm -rf {} +


########################
# 2️⃣ Runtime (ultra-slim)
########################
FROM python:3.10-slim AS runtime

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Tokyo \
    LANG=zh_CN.UTF-8 \
    LC_ALL=zh_CN.UTF-8 \
    HOST=0.0.0.0 \
    PORT=8181 \
    GIT_PYTHON_REFRESH=quiet \
    # 让 Playwright 直接使用我们拷贝进来的浏览器
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 运行时依赖：只装 Playwright 必需库 + 基础运行依赖 + 精简字体/locale
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    locales \
    git \
    \
    # Playwright/Chromium runtime deps（比你原来那串精简很多）
    libnss3 \
    libnspr4 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxkbcommon0 \
    libxshmfence1 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    \
    # 字体：CJK + Emoji（比 fonts-noto 全家桶轻）
    fonts-noto-cjk \
    fonts-noto-color-emoji \
 && sed -i 's/# zh_CN.UTF-8 UTF-8/zh_CN.UTF-8 UTF-8/' /etc/locale.gen \
 && locale-gen \
 && rm -rf /var/lib/apt/lists/*

# 离线安装 wheels（runtime 不需要 gcc/build-essential）
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir -U pip \
 && python -m pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* \
 && rm -rf /wheels

# 拷贝 Playwright 浏览器文件（builder 已下载）
COPY --from=builder /ms-playwright /ms-playwright

# 拷贝应用源码
COPY --from=builder /app /app

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8181 5888
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "bot.py"]