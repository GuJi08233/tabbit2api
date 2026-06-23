import json
import uuid
import hashlib
import base64
import time
import random
import string
import asyncio
import logging
from typing import AsyncGenerator, Optional

import httpx

from core.tabbit_sign import (
    generate_sign_headers,
    generate_pro_uuid,
    generate_fingerprint_headers,
    generate_trace_id,
    DEFAULT_SIGN_KEY,
    hmac_sha256_hex,
)

logger = logging.getLogger("tabbit2api")

MODEL_MAP = {
    "best": "Default",
    "default": "Default",
    "deepseek-v4-pro": "DeepSeek-V4-Pro",
    "deepseek-v4-flash": "DeepSeek-V4-Flash",
    "deepseek-v3.2": "DeepSeek-V3.2",
    "kimi-k2.6": "Kimi-K2.6",
    "kimi-k2.5": "Kimi-K2.5",
    "glm-5.1": "GLM-5.1",
    "glm-5v-turbo": "GLM-5V-Turbo",
    "minimax-m3": "MiniMax-M3",
    "minimax-m2.7": "MiniMax-M2.7",
    "claude-opus-4.8": "Claude-Opus-4.8",
    "claude-opus-4.7": "Claude-Opus-4.7",
    "claude-sonnet-4.6": "Claude-Sonnet-4.6",
    "claude-haiku-4.5": "Claude-Haiku-4.5",
    "gpt-5.5": "GPT-5.5",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.2-chat": "GPT-5.2-Chat",
    "gemini-3.5-flash": "Gemini-3.5-Flash",
    "gemini-3.1-pro": "Gemini-3.1-Pro",
    "qwen3.5-plus": "Qwen3.5-Plus",
    "doubao-seed-1.8": "Doubao-Seed-1.8",
    "longcat-flash-chat": "LongCat-Flash-Chat",
    "longcat-flash-thinking": "LongCat-Flash-Thinking",
}


class TabbitClient:
    def __init__(self, token_str: str, base_url: str | None = None, client_id: str | None = None):
        if not token_str:
            raise ValueError("token_str cannot be empty")

        parts = token_str.split("|")
        self.jwt_token = parts[0] if parts else ""
        self.next_auth = parts[1] if len(parts) > 1 else None
        self.device_id = parts[2] if len(parts) > 2 else str(uuid.uuid4())
        self.user_id = self._extract_user_id(self.jwt_token)
        self.base_url = base_url or "https://web.tabbit.ai"
        self.client_id = client_id or "2dd8eb4c1ed9c344d173"

        # 签名 key 管理
        self.sign_key = DEFAULT_SIGN_KEY
        self.sign_key_fetched_at = 0
        self.sign_key_ttl = 10 * 60 * 1000  # 10 分钟刷新一次

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15, read=180, write=30, pool=30),
            follow_redirects=False,
            verify=False,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=60,
            ),
        )

    def _extract_user_id(self, token: str) -> str:
        if not token:
            return str(uuid.uuid4())
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return str(uuid.uuid4())
            payload_b64 = parts[1]
            padding = 4 - (len(payload_b64) % 4)
            if padding != 4:
                payload_b64 += "=" * padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            return payload.get("id", payload.get("sub", str(uuid.uuid4())))
        except Exception:
            return str(uuid.uuid4())

    async def fetch_sign_key(self) -> str:
        """获取签名 key（逆向自 /chat/sign-key 端点）"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Cookie": f"token={self.jwt_token}",
            }
            resp = await self.client.get(
                f"{self.base_url}/chat/sign-key",
                headers=headers,
            )
            if resp.status_code == 200:
                key = resp.text.strip()
                if key:
                    self.sign_key = key
                    self.sign_key_fetched_at = int(time.time() * 1000)
                    return key
        except Exception as e:
            logger.warning(f"Failed to fetch sign key: {e}")
        return self.sign_key

    async def ensure_sign_key(self) -> str:
        """确保签名 key 有效"""
        now = int(time.time() * 1000)
        if not self.sign_key or now - self.sign_key_fetched_at > self.sign_key_ttl:
            await self.fetch_sign_key()
        return self.sign_key

    def _generate_nonce(self) -> str:
        return ''.join(random.choices(string.hexdigits, k=64))

    def _generate_uuid(self) -> str:
        return str(uuid.uuid4())

    def _get_headers(self, referer_path: str = "/panel?mode=mi&hl=zh-CN") -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Chromium";v="148", "Tabbit";v="148", "Not/A)Brand";v="99"',
            "sec-ch-ua-platform": '"Windows"',
            "x-glic": "1",
            "x-glic-chrome-version": "148.0.7778.168",
            "x-glic-chrome-channel": "unknown",
            "x-chrome-id-consistency-request": (
                f"version=1,client_id={self.client_id},"
                f"device_id={self.device_id},sync_account_id={self.user_id},"
                "signin_mode=all_accounts,signout_mode=show_confirmation"
            ),
            "referer": f"{self.base_url}{referer_path}",
        }

    def _get_chat_headers(self, session_id: str, body: str = "") -> dict:
        trace_id = generate_trace_id()

        # 生成签名 headers（正确的 HMAC 签名）
        sign_headers = generate_sign_headers(body, self.sign_key)

        # 生成指纹 headers（带 Pro 标记）
        fingerprint_headers = generate_fingerprint_headers(
            version="1.1.39(10101039)",
            is_pro=True  # 启用 Pro 模式
        )

        return {
            **self._get_headers(f"/panel/{session_id}"),
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "Trace-Id": trace_id,
            "Origin": self.base_url,
            **sign_headers,
            **fingerprint_headers,
        }

    def _get_cookies(self) -> dict:
        cookies = {
            "token": self.jwt_token,
            "user_id": self.user_id,
            "managed": "tab_browser",
            "NEXT_LOCALE": "zh",
        }
        if self.next_auth:
            cookies["next-auth.session-token"] = self.next_auth
        return cookies

    async def create_chat_session(self) -> str:
        for attempt in range(3):
            try:
                headers = {
                    **self._get_headers("/panel?mode=mi&hl=zh-CN"),
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                }

                payload = {
                    "entity": {
                        "key": hashlib.md5(b"").hexdigest(),
                        "extras": {
                            "type": "tab",
                            "url": f"{self.base_url}/newtab",
                        },
                    }
                }

                resp = await self.client.post(
                    f"{self.base_url}/panel/session",
                    json=payload,
                    headers=headers,
                    cookies=self._get_cookies(),
                )

                if resp.status_code != 200:
                    raise Exception(f"panel/session returned {resp.status_code}: {resp.text[:200]}")

                data = resp.json()
                session_id = data.get("chat_session_id")
                if session_id:
                    return session_id
                raise Exception(f"No chat_session_id in response: {resp.text[:200]}")
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(1 + attempt * 0.5)
                    continue
                raise

    async def send_message(
        self, session_id: str, content: str, model: str
    ) -> AsyncGenerator[dict, None]:
        # 确保签名 key 有效
        await self.ensure_sign_key()

        payload = {
            "chat_session_id": session_id,
            "message_id": None,
            "content": content,
            "selected_model": model,
            "parallel_group_id": None,
            "task_name": "chat",
            "agent_mode": False,
            "metadatas": {"html_content": f"<p>{content}</p>"},
            "references": [],
            "entity": {
                "key": hashlib.md5(b"").hexdigest(),
                "extras": {"type": "tab", "url": ""},
            },
        }

        # 将 payload 转换为 JSON 字符串用于签名
        body_str = json.dumps(payload, separators=(',', ':'))
        headers = self._get_chat_headers(session_id, body_str)

        # 尝试请求，如果遇到 499 错误则刷新签名 key 并重试
        for attempt in range(2):
            async with self.client.stream(
                "POST",
                f"{self.base_url}/api/v1/chat/completion",
                json=payload,
                headers=headers,
                cookies=self._get_cookies(),
            ) as resp:
                # 499 错误表示签名 key 过期，刷新后重试
                if resp.status_code == 499 and attempt == 0:
                    await self.fetch_sign_key()
                    headers = self._get_chat_headers(session_id, body_str)
                    continue

                if resp.status_code != 200:
                    body = await resp.aread()
                    raise Exception(f"Tabbit API error {resp.status_code}: {body.decode()}")

                current_event = None
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line[len("event:") :].strip()
                    elif line.startswith("data:") and current_event:
                        data_str = line[len("data:") :].strip()
                        try:
                            data = json.loads(data_str)
                            yield {"event": current_event, "data": data}
                        except Exception:
                            pass
                break  # 成功，退出重试循环

    async def close(self):
        await self.client.aclose()
