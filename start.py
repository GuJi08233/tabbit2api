#!/usr/bin/env python3
"""
Tabbit2API 本地启动脚本
适用于国际版 Tabbit (web.tabbit.ai)
"""
import subprocess
import sys
import os

def main():
    print("=" * 60)
    print("Tabbit2API - 国际版适配")
    print("=" * 60)
    print("\n确保已安装依赖：")
    print("  pip install -r requirements.txt")
    print("\n服务启动后访问：")
    print("  API接口: http://localhost:8800/v1/chat/completions")
    print("  管理面板: http://localhost:8800/admin")
    print("  默认密码: admin")
    print("\n" + "=" * 60 + "\n")
    
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    try:
        subprocess.run([
            sys.executable, "-m", "uvicorn",
            "tabbit2api:app",
            "--host", "0.0.0.0",
            "--port", "8800",
            "--reload"
        ], check=True)
    except subprocess.CalledProcessError as e:
        print(f"启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()