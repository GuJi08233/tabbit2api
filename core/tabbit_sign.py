#!/usr/bin/env python3
"""
Tabbit 签名和认证模块
参考 tabbit-toy 项目的正确实现
"""

import time
import uuid
import hashlib
import hmac
import random
import string
from typing import Tuple, Optional


# 默认签名 key（逆向自 Tabbit 60442 模块）
DEFAULT_SIGN_KEY = "f8d0e6a73f8d4b1a9c3d2e1f9a4b7c6d"


def sha256_hex(text: str) -> str:
    """计算 SHA256 哈希值（十六进制）"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hmac_sha256_hex(key: str, text: str) -> str:
    """计算 HMAC-SHA256 签名（十六进制）"""
    return hmac.new(
        key.encode("utf-8"),
        text.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def generate_sign_headers(body: str, key: str = DEFAULT_SIGN_KEY) -> dict:
    """
    生成签名 headers（逆向自 60442 模块 y()）

    返回:
        {
            "X-Timestamp": str,  # 毫秒时间戳
            "X-Nonce": str,      # HMAC-SHA256 签名
            "X-Signature": str,  # 随机 UUID
        }

    注意命名反直觉：
    - X-Signature = 随机 UUID
    - X-Nonce = HMAC-SHA256(KEY, "${timestamp}.${uuid}.${sha256(body)}")
    """
    ts = str(int(time.time() * 1000))
    sig = str(uuid.uuid4())
    body_hash = sha256_hex(body or "")
    msg = f"{ts}.{sig}.{body_hash}"
    nonce = hmac_sha256_hex(key, msg)

    return {
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Signature": sig,
    }


def generate_pro_uuid(is_pro: bool = True) -> str:
    """
    生成 Pro 会员 UUID（逆向自 1711 模块）

    Unique-Uuid 的第 5 位（0-indexed）是"已设默认浏览器"标记位：
    - '1' = 已设（Pro 解锁，premium 模型可用）
    - 其它 = 未设（Default 模型可用，premium 模型报 492）

    Args:
        is_pro: 是否为 Pro 会员

    Returns:
        带标记位的 UUID 字符串
    """
    hex_chars = "0123456789abcdef"
    marker_pos = 5
    default_browser_marker = "1"
    timestamp_positions = [2, 7, 11, 14, 18, 21, 25, 28]

    # 获取当前时间戳的十六进制表示
    ts = format(int(time.time()), '08x')[-8:]
    ts_map = {pos: ts[i] for i, pos in enumerate(timestamp_positions)}

    # 去掉 '1' 的字符集（用于非 Pro 用户）
    others = hex_chars.replace(default_browser_marker, "")

    result = []
    for i in range(32):
        if i == marker_pos:
            if is_pro:
                result.append(default_browser_marker)
            else:
                result.append(random.choice(others))
        elif i in ts_map:
            result.append(ts_map[i])
        else:
            result.append(random.choice(hex_chars))

    # 格式化为 UUID 格式
    uuid_str = "".join(result)
    return f"{uuid_str[:8]}-{uuid_str[8:12]}-{uuid_str[12:16]}-{uuid_str[16:20]}-{uuid_str[20:]}"


def generate_fingerprint_headers(
    version: str = "1.1.39(10101039)",
    is_pro: bool = True
) -> dict:
    """
    生成指纹 headers（逆向自 38363 模块 m()/HH）

    返回:
        {
            "X-Req-Ctx": str,      # base64(tabbitVersion)
            "Unique-Uuid": str,    # 带标记位的 UUID
        }
    """
    import base64

    version_b64 = base64.b64encode(version.encode("utf-8")).decode("ascii")

    return {
        "X-Req-Ctx": version_b64,
        "Unique-Uuid": generate_pro_uuid(is_pro),
    }


def generate_trace_id() -> str:
    """生成 trace-id（UUID v4）"""
    return str(uuid.uuid4())


def generate_nonce() -> str:
    """生成随机 nonce（64 位十六进制）"""
    return "".join(random.choices(string.hexdigits, k=64))


# ─── 测试函数 ─────────────────────────────────────────────
def test_sign_headers():
    """测试签名 headers 生成"""
    body = '{"test": "data"}'
    key = DEFAULT_SIGN_KEY

    headers = generate_sign_headers(body, key)

    print("=== 测试签名 headers ===")
    print(f"X-Timestamp: {headers['X-Timestamp']}")
    print(f"X-Nonce: {headers['X-Nonce'][:16]}...")
    print(f"X-Signature: {headers['X-Signature']}")

    # 验证签名
    ts = headers["X-Timestamp"]
    sig = headers["X-Signature"]
    body_hash = sha256_hex(body)
    msg = f"{ts}.{sig}.{body_hash}"
    expected_nonce = hmac_sha256_hex(key, msg)

    assert headers["X-Nonce"] == expected_nonce, "签名验证失败！"
    print("✅ 签名验证通过")


def test_pro_uuid():
    """测试 Pro UUID 生成"""
    print("\n=== 测试 Pro UUID ===")

    # Pro 用户
    pro_uuid = generate_pro_uuid(True)
    print(f"Pro UUID: {pro_uuid}")
    print(f"标记位 (第5位): {pro_uuid.split('-')[0][5]}")
    assert pro_uuid.split('-')[0][5] == '1', "Pro 标记位应该是 '1'"
    print("✅ Pro 标记位正确")

    # 非 Pro 用户
    non_pro_uuid = generate_pro_uuid(False)
    print(f"非 Pro UUID: {non_pro_uuid}")
    print(f"标记位 (第5位): {non_pro_uuid.split('-')[0][5]}")
    assert non_pro_uuid.split('-')[0][5] != '1', "非 Pro 标记位不应该是 '1'"
    print("✅ 非 Pro 标记位正确")


def test_fingerprint_headers():
    """测试指纹 headers 生成"""
    print("\n=== 测试指纹 headers ===")

    headers = generate_fingerprint_headers("1.1.39(10101039)", True)
    print(f"X-Req-Ctx: {headers['X-Req-Ctx'][:20]}...")
    print(f"Unique-Uuid: {headers['Unique-Uuid']}")

    # 验证 base64 解码
    import base64
    decoded = base64.b64decode(headers["X-Req-Ctx"]).decode("utf-8")
    print(f"解码后: {decoded}")
    assert decoded == "1.1.39(10101039)", "版本号解码失败！"
    print("✅ 版本号编码正确")


if __name__ == "__main__":
    import sys
    import io

    # 设置输出编码为 UTF-8
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=== 测试签名 headers ===")
    test_sign_headers()
    print("\n=== 测试 Pro UUID ===")
    test_pro_uuid()
    print("\n=== 测试指纹 headers ===")
    test_fingerprint_headers()
    print("\n=== 所有测试通过 ===")
