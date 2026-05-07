#!/usr/bin/env python3
"""
Tabbit2API Conda 环境启动脚本
适用于国内版 Tabbit (web.tabbit-ai.com)
"""
import subprocess
import sys
import os

def run_command(cmd, shell=True):
    try:
        result = subprocess.run(cmd, shell=shell, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {e.stderr}")
        return None

def main():
    print("=" * 60)
    print("Tabbit2API - Conda 环境启动")
    print("=" * 60)
    
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    env_name = "tabbit2api"
    
    print("\n1. 检查 Conda 环境...")
    result = run_command("conda env list")
    if result:
        if env_name in result:
            print(f"   ✓ 环境 {env_name} 已存在")
        else:
            print(f"   ✗ 环境 {env_name} 不存在，正在创建...")
            print("   正在安装依赖，请稍候...")
            run_command(f"conda env create -f environment.yml")
            print(f"   ✓ 环境 {env_name} 创建成功")
    
    print("\n2. 激活 Conda 环境并启动服务...")
    print("\n服务启动后访问：")
    print("  API接口: http://localhost:8800/v1/chat/completions")
    print("  管理面板: http://localhost:8800/admin")
    print("  默认密码: admin")
    print("\n按 Ctrl+C 停止服务\n")
    
    if sys.platform.startswith('win'):
        cmd = f'conda activate {env_name} && python tabbit2api.py'
    else:
        cmd = f'conda activate {env_name} && python tabbit2api.py'
    
    subprocess.run(cmd, shell=True)

if __name__ == "__main__":
    main()