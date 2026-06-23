# Tabbit2API 优化方案

## 项目对比

| 特性 | 你的项目 (Python) | xunxun1982 (Node.js) | tabbit-toy (Node.js) |
|------|------------------|---------------------|---------------------|
| 语言 | Python + FastAPI | Node.js | Node.js |
| 认证方式 | Token | Playwright | Cookie + HMAC |
| 签名机制 | ❌ 错误 | ✅ 浏览器自动 | ✅ 正确 |
| Pro 标记 | ❌ 缺失 | ✅ 浏览器自动 | ✅ 正确 |
| 流式响应 | ✅ 支持 | ✅ 支持 | ✅ 支持 |
| 附件支持 | ❌ 不支持 | ✅ 支持 | ❌ 不支持 |
| 浏览器依赖 | ❌ 无 | ✅ 需要 | ❌ 无 |
| Token 池 | ✅ 支持 | ❌ 不支持 | ❌ 不支持 |

## 关键问题修复

### 1. 签名机制修复 ✅

**问题**：你的代码使用随机字符串作为 `X-Nonce`，但应该是 HMAC-SHA256 签名。

**修复**：已创建 `core/tabbit_sign.py` 模块，实现正确的签名机制。

**关键代码**：
```python
def generate_sign_headers(body: str, key: str) -> dict:
    ts = str(int(time.time() * 1000))
    sig = str(uuid.uuid4())
    body_hash = sha256_hex(body or "")
    msg = f"{ts}.{sig}.{body_hash}"
    nonce = hmac_sha256_hex(key, msg)
    return {
        "X-Timestamp": ts,
        "X-Nonce": nonce,  # ✅ HMAC 签名
        "X-Signature": sig,  # ✅ 随机 UUID
    }
```

### 2. Pro 会员标记修复 ✅

**问题**：你的代码生成普通的 UUID，但 Tabbit 会检查 `Unique-Uuid` 的第 5 位。

**修复**：已实现 `generate_pro_uuid()` 函数，生成带 Pro 标记的 UUID。

**关键代码**：
```python
def generate_pro_uuid(is_pro: bool = True) -> str:
    marker_pos = 5
    # ... 生成 UUID ...
    if is_pro:
        result[marker_pos] = '1'  # ✅ Pro 标记
    # ... 格式化为 UUID ...
```

### 3. 版本号编码 ✅

**问题**：`X-Req-Ctx` 需要 base64 编码的版本号。

**修复**：已实现 `generate_fingerprint_headers()` 函数。

**关键代码**：
```python
def generate_fingerprint_headers(version: str, is_pro: bool) -> dict:
    version_b64 = base64.b64encode(version.encode()).decode()
    return {
        "X-Req-Ctx": version_b64,  # ✅ base64 编码
        "Unique-Uuid": generate_pro_uuid(is_pro),
    }
```

## 已完成的修改

### 1. 新增文件：`core/tabbit_sign.py`

实现了正确的签名机制：
- `generate_sign_headers()` - HMAC 签名
- `generate_pro_uuid()` - Pro 会员 UUID
- `generate_fingerprint_headers()` - 指纹头
- `generate_trace_id()` - Trace ID
- `sha256_hex()` - SHA256 哈希
- `hmac_sha256_hex()` - HMAC-SHA256 签名

### 2. 修改文件：`core/tabbit_client.py`

更新了：
- 导入签名模块
- `_get_chat_headers()` 使用正确的签名
- `send_message()` 传递 body 给签名函数

## 测试验证

运行测试：
```bash
python -X utf8 core/tabbit_sign.py
```

预期输出：
```
=== 测试签名 headers ===
X-Timestamp: 1782234588967
X-Nonce: 805a4990661c4d79...
X-Signature: 984ebc9c-6ce4-411f-9e9c-6c3d6a180f4b
✅ 签名验证通过

=== 测试 Pro UUID ===
Pro UUID: 856ea1ea-4453-8fad-f2bc-2dff0d23c02a
标记位 (第5位): 1
✅ Pro 标记位正确

=== 测试指纹 headers ===
X-Req-Ctx: MS4xLjM5KDEwMTAxMDM5...
Unique-Uuid: cd68b19a-f963-89a6-7fbe-1d558d9dc5cd
解码后: 1.1.39(10101039)
✅ 版本号编码正确

=== 所有测试通过 ===
```

## 可选改进（参考 xunxun1982）

### 1. 会话管理优化

xunxun1982 的项目使用 Playwright 自动管理会话，你的项目可以添加：
- 会话池管理
- 自动会话创建
- 会话状态监控

### 2. 错误处理优化

xunxun1982 的项目有详细的错误分类：
- 登录状态检测
- 模型可用性检查
- 自动重试机制

### 3. 流式响应优化

xunxun1982 的项目支持真正的 SSE 流式响应：
- 实时 delta 推送
- 背压处理
- 错误恢复

## 下一步

1. **测试签名修复**
   ```bash
   python -X utf8 core/tabbit_sign.py
   ```

2. **启动服务测试**
   ```bash
   python tabbit2api.py
   ```

3. **测试 API 调用**
   ```bash
   curl -X POST http://localhost:8800/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model":"Default","messages":[{"role":"user","content":"你好"}]}'
   ```

4. **检查日志**
   - 查看签名是否正确
   - 查看是否能正常获取响应
   - 查看 Pro 模型是否可用

## 总结

你的项目已经有了很好的架构，主要问题是签名机制。通过参考 tabbit-toy 的正确实现，已经修复了：

1. ✅ **签名机制** - 使用 HMAC-SHA256 签名
2. ✅ **Pro 标记** - 生成带标记位的 UUID
3. ✅ **版本号编码** - base64 编码版本号

现在你的项目应该能够：
- ✅ 正确签名请求
- ✅ 使用 Pro 模型
- ✅ 避免 499/493 错误
