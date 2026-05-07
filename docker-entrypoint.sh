#!/bin/bash
set -e

CONFIG_FILE="/app/data/config.json"
APP_CONFIG="/app/config.json"

echo "[Entrypoint] 初始化目录..."
mkdir -p /app/data
chmod 755 /app/data

echo "[Entrypoint] 处理配置文件..."
if [ -f "$CONFIG_FILE" ]; then
    echo "[Entrypoint] 使用已有配置: $CONFIG_FILE"
    rm -f "$APP_CONFIG"
    ln -sf "$CONFIG_FILE" "$APP_CONFIG"
elif [ -f "$APP_CONFIG" ]; then
    echo "[Entrypoint] 迁移配置到持久化目录..."
    cp "$APP_CONFIG" "$CONFIG_FILE"
    rm -f "$APP_CONFIG"
    ln -sf "$CONFIG_FILE" "$APP_CONFIG"
else
    echo "[Entrypoint] 首次启动，准备自动生成配置文件..."
    rm -f "$APP_CONFIG"
    ln -sf "$CONFIG_FILE" "$APP_CONFIG"
    echo "[Entrypoint] 配置链接已创建"
fi

echo "[Entrypoint] 启动前检查..."
if [ ! -f "$APP_CONFIG" ] && [ ! -L "$APP_CONFIG" ]; then
    echo "[Entrypoint] 错误: 配置文件链接未创建成功"
    exit 1
fi

echo "[Entrypoint] 启动 Tabbit2API..."
exec python tabbit2api.py
