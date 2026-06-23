# 修复完成 - 对照 tabbit-toy 优化 tabbit2api

## 修复的问题

| 问题 | 修复前 | 修复后 |
|------|--------|--------|
| **X-Nonce** | ❌ 随机字符串 | ✅ HMAC-SHA256 签名 |
| **Unique-Uuid** | ❌ 普通 UUID | ✅ 带 Pro 标记的 UUID |
| **签名 key** | ❌ 硬编码 | ✅ 自动刷新 |
| **499 错误** | ❌ 无处理 | ✅ 自动重试 |

## 新增文件

### `core/tabbit_sign.py` - 签名模块

```python
# 核心函数
generate_sign_headers(body, key)      # HMAC 签名
generate_pro_uuid(is_pro)             # Pro 会员 UUID
generate_fingerprint_headers(version)  # 指纹头
sha256_hex(text)                      # SHA256 哈希
hmac_sha256_hex(key, text)           # HMAC-SHA256
```

## 修改的文件

### `core/tabbit_client.py`

1. **导入签名模块**
2. **添加签名 key 管理**
   - `sign_key` - 当前签名 key
   - `sign_key_fetched_at` - 上次获取时间
   - `sign_key_ttl` - 过期时间（10分钟）

3. **新增方法**
   - `fetch_sign_key()` - 获取签名 key
   - `ensure_sign_key()` - 确保 key 有效

4. **更新方法**
   - `_get_chat_headers()` - 使用正确签名
   - `send_message()` - 添加 499 重试

## 测试验证

### 运行测试

```bash
python -X utf8 core/tabbit_sign.py
```

### 预期结果

```
✅ 签名验证通过
✅ Pro 标记位正确（第5位为'1'）
✅ 版本号编码正确
```

## 关键改进

1. **签名正确性** - 避免 499 错误
2. **Pro 模型支持** - Claude-Opus-4.8、GPT-5.5 等
3. **自动刷新** - 签名 key 过期时自动获取
4. **容错机制** - 499 错误时自动重试

## 使用方法

### 启动服务

```bash
python tabbit2api.py
```

### 测试 API

```bash
curl -X POST http://localhost:8800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Default","messages":[{"role":"user","content":"你好"}]}'
```

## 参考来源

- **tabbit-toy 项目** - 正确的签名实现
- **Tabbit 逆向文档** - 签名算法细节
