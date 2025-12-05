#!/bin/sh
set -e

# 确保挂载目录存在
mkdir -p /app/data
mkdir -p /app/log

# 初次运行时，将默认资源拷贝到 data 下
# -r 递归复制
# -n 不覆盖已有文件
# 2>/dev/null 静音处理不存在情况
if [ -d /app/resources-default ]; then
  cp -rn /app/resources-default/* /app/data/ 2>/dev/null || true
fi

echo "📁 Resources checked: /app/data"

# 启动 NoneBot
exec "$@"
