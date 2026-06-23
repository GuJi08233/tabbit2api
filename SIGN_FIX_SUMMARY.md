# 签名修复完成总结

## 问题诊断

你的项目存在以下关键问题：

### 1. ❌ 签名机制错误

**原代码**：
```python
"X-Nonce": self._generate_nonce(),  # 随机字符串 ❌
"X-Signature": self._generate_uuid(),  # 随机 UUID ✅
```

**问题**：
- `X-Nonce` 应该是 HMAC-SHA256 签名，而不是随机字符串
- Tabbit 服务端会验证签名，随机字符串会导致 499 错误

### 2. ❌ Pro 会员标记缺失

**原代码**：
```python
"Unique-Uuid": self._generate_uuid(),  # 普通 UUID ❌
```

**问题**：
- Tabbit 会检查 `Unique-Uuid` 的第 5 位是否为 `1`
- 普通 UUID 无法使用 Pro 模型（Claude-Opus-4.8 等）

### 3. ❌ 签名 key 刷新机制缺失

**问题**：
- 签名 key 可能会过期
- 没有自动刷新机制

## 修复方案

### 1. ✅ 创建签名模块：`core/tabbit_sign.py`

实现了正确的签名机制：

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

### 2. ✅ 实现 Pro UUID 生成

```python
def generate_pro_uuid(is_pro: bool = True) -> str:
    marker_pos = 5
    # ... 生成 UUID ...
    if is_pro:
        result[marker_pos] = '1'  # ✅ Pro 标记
    # ... 格式化为 UUID ...
```

### 3. ✅ 实现签名 key 刷新

```python
async def fetch_sign_key(self) -> str:
    """获取签名 key（逆向自 /chat/sign-key 端点）"""
    resp = await self.client.get(f"{self.base_url}/chat/sign-key")
    if resp.status_code == 200:
        self.sign_key = resp.text.strip()
    return self.sign_key

async def ensure_sign_key(self) -> str:
    """确保签名 key 有效"""
    if now - self.sign_key_fetched_at > self.sign_key_ttl:
        await self.fetch_sign_key()
    return self.sign_key
```

### 4. ✅ 实现 499 重试机制

```python
# 尝试请求，如果遇到 499 错误则刷新签名 key 并重试
for attempt in range(2):
    async with self.client.stream(...) as resp:
        # 499 错误表示签名 key 过期，刷新后重试
        if resp.status_code == 499 and attempt == 0:
            await self.fetch_sign_key()
            headers = self._get_chat_headers(session_id, body_str)
            continue
        # ... 处理响应 ...
```

## 修改的文件

### 1. 新增文件

- `core/tabbit_sign.py` - 签名模块
  - `generate_sign_headers()` - HMAC 签名
  - `generate_pro_uuid()` - Pro 会员 UUID
  - `generate_fingerprint_headers()` - 指纹头
  - `generate_trace_id()` - Trace ID
  - `sha256_hex()` - SHA256 哈希
  - `hmac_sha256_hex()` - HMAC-SHA256 签名

### 2. 修改文件

- `core/tabbit_client.py` - Tabbit 客户端
  - 导入签名模块
  - 添加签名 key 管理
  - 更新 `_get_chat_headers()` 使用正确签名
  - 添加 `fetch_sign_key()` 方法
  - 添加 `ensure_sign_key()` 方法
  - 更新 `send_message()` 添加 499 重试

## 测试验证

### 运行测试

```bash
python -X utf8 core/tabbit_sign.py
```

### 预期输出

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

## 验证步骤

### 1. 测试签名模块

```bash
python -X utf8 core/tabbit_sign.py
```

### 2. 测试客户端创建

```bash
python -X utf8 -c "
from core.tabbit_client import TabbitClient
client = TabbitClient('test-token')
print('✅ 客户端创建成功')
"
```

### 3. 测试签名 headers

```bash
python -X utf8 -c "
from core.tabbit_client import TabbitClient
client = TabbitClient('test-token')
headers = client._get_chat_headers('test-session', '{\"test\": \"data\"}')
print('✅ 签名 headers 生成成功')
print(f'  - X-Nonce: {headers.get(\"X-Nonce\", \"N/A\")[:16]}...')
print(f'  - Unique-Uuid: {headers.get(\"Unique-Uuid\", \"N/A\")}')
"
```

### 4. 启动服务测试

```bash
python tabbit2api.py
```

### 5. 测试 API 调用

```bash
curl -X POST http://localhost:8800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Default","messages":[{"role":"user","content":"你好"}]}'
```

## 预期效果

修复后，你的项目应该能够：

1. ✅ **正确签名请求** - 避免 499 错误
2. ✅ **使用 Pro 模型** - Claude-Opus-4.8、GPT-5.5 等
3. ✅ **自动刷新签名 key** - 避免签名过期
4. ✅ **499 自动重试** - 提高成功率

## 参考资料

- **tabbit-toy 项目**：正确的签名实现
- **Tabbit 逆向文档**：签名算法细节
- **HMAC-SHA256**：签名算法说明

## 下一步

1. **运行测试**：验证签名是否正确
2. **启动服务**：测试完整功能
3. **测试 Pro 模型**：验证 Pro 标记是否生效
4. **监控日志**：查看是否有 499 错误
5. **优化性能**：根据需要调整缓存策略
