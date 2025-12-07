#!/bin/sh
set -e

# 确保挂载目录存在
mkdir -p /app/data
mkdir -p /app/log

# 初次运行时，将默认资源拷贝到 data 下
if [ -d /app/resources/data ]; then
  echo "📁 Checking default resources..."

  cp -rn /app/resources/data/* /app/data/ 2>/dev/null || true

  echo "📁 Resources copied to /app/data"

  # 如果 copy 成功，再删除 /app/resources
  # -r 删除整个目录
  # -f 静默，不报错
  rm -rf /app/resources
  echo "🧹 Default resources deleted from image to save space"
fi

# 启动 NoneBot
exec "$@"
