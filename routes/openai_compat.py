import json
import time
import uuid
import logging
import asyncio
import re
from typing import Any, Optional, List, Dict
from collections import deque

from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.tabbit_client import TabbitClient, MODEL_MAP
from core.token_manager import TokenManager
from core.log_store import LogStore, LogEntry
from core.config import ConfigManager
from core.tool_parser import (
    build_tools_prompt,
    parse_tool_calls,
    OpenAIToolCallParser,
    generate_tool_call_id,
)

logger = logging.getLogger("tabbit2openai")

router = APIRouter()

_tm: TokenManager | None = None
_cfg: ConfigManager | None = None
_logs: LogStore | None = None
_fallback_clients: dict[str, TabbitClient] = {}


def init(token_manager: TokenManager, config: ConfigManager, log_store: LogStore):
    global _tm, _cfg, _logs
    _tm = token_manager
    _cfg = config
    _logs = log_store


# ── JSON 缓冲池（借鉴 cursor2api-go 的 jsonBufferPool）──────

class _JsonBufferPool:
    """复用 JSON 序列化缓冲区，减少内存分配"""
    def __init__(self, max_size: int = 32):
        self._pool: deque[str] = deque(maxlen=max_size)

    def get(self) -> list:
        return []

    def put(self, buf: list):
        buf.clear()

_json_pool = _JsonBufferPool()


# ── SSE 辅助函数 ──────────────────────────────────────────

def _sse_event(data: dict) -> str:
    """格式化 SSE 事件"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _chat_chunk(completion_id: str, model: str, delta: dict, finish_reason: str | None = None) -> str:
    """生成 chat completion chunk"""
    return _sse_event({
        "id": completion_id,
        "object": "chat.completion.chunk",
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
    })


def _chat_error(completion_id: str, model: str, error_msg: str) -> str:
    """生成错误 chunk"""
    return _sse_event({
        "id": completion_id,
        "object": "chat.completion.chunk",
        "choices": [{
            "index": 0,
            "delta": {"content": f"\n\n[Error: {error_msg}]"},
            "finish_reason": "stop",
        }],
    })


# ── 文本清理函数 ──────────────────────────────────────────

def _clean_text(text: str) -> str:
    """清理文本中的特殊标签"""
    text = re.sub(r'<system-reminder>.*?</system-reminder>', '', text, flags=re.DOTALL)
    text = re.sub(r'<user_input>.*?</user_input>', '', text, flags=re.DOTALL)
    text = re.sub(r'<env>.*?</env>', '', text, flags=re.DOTALL)
    text = re.sub(r'<task_list>.*?</task_list>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_list>.*?</tool_list>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_result>.*?</tool_result>', '', text, flags=re.DOTALL)
    text = re.sub(r'<function_calls>.*?</function_calls>', '', text, flags=re.DOTALL)
    text = re.sub(r'<task_type>.*?</task_type>', '', text, flags=re.DOTALL)
    text = re.sub(r'<goal>.*?</goal>', '', text, flags=re.DOTALL)
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL)
    text = re.sub(r'<content>.*?</content>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r'^\s+|\s+$', '', text)
    return text


def _normalize_content(content) -> str:
    """规范化内容"""
    if isinstance(content, str):
        return _clean_text(content)
    elif isinstance(content, list):
        result = ""
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    result += _clean_text(item.get("text", ""))
                elif item.get("type") == "image_url":
                    result += f"[Image: {item.get('image_url', {}).get('url', '')}]"
                else:
                    result += _clean_text(str(item.get("content", "")))
            else:
                result += _clean_text(str(item))
        return result.strip()
    return _clean_text(str(content))


class ChatMessageContentPart(BaseModel):
    type: str
    text: Optional[str] = None
    image_url: Optional[Dict[str, str]] = None


class ChatMessage(BaseModel):
    role: str
    content: str | List[ChatMessageContentPart]


class ChatCompletionRequest(BaseModel):
    model: str = "best"
    messages: List[ChatMessage]
    stream: bool = False
    tools: Optional[List[dict]] = None
    tool_choice: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = 1
    stop: Optional[List[str]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Dict[str, float]] = None
    user: Optional[str] = None


class SimpleChatRequest(BaseModel):
    role: str = "user"
    content: Any


MAX_CONTENT_LENGTH = 8000
MAX_MESSAGES = 6

def _build_content(messages: List[ChatMessage], tools: Optional[List[dict]] = None) -> str:
    system_prompt = _cfg.get("proxy", "system_prompt") if _cfg else ""

    # 如果有工具，注入工具提示
    if tools:
        tools_prompt = build_tools_prompt(tools)
        if system_prompt:
            system_prompt = f"{system_prompt}\n\n{tools_prompt}"
        else:
            system_prompt = tools_prompt

    recent_messages = messages[-MAX_MESSAGES:]

    parts = []
    if system_prompt:
        parts.append(f"[System]: {system_prompt}")

    for m in recent_messages:
        label = {"user": "User", "assistant": "Assistant", "system": "System"}.get(
            m.role, m.role.capitalize()
        )
        parts.append(f"[{label}]: {_normalize_content(m.content)}")

    full_content = "\n\n".join(parts) + "\n\n[Assistant]:"

    if len(full_content) > MAX_CONTENT_LENGTH:
        logger.warning(f"Content too long ({len(full_content)} chars), truncating to {MAX_CONTENT_LENGTH}")
        full_content = full_content[:MAX_CONTENT_LENGTH]

    return full_content


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    token = authorization.strip()
    for prefix in ["Bearer ", "Bearer=", "bearer ", "bearer=", "Bearar ", "bearar="]:
        if token.startswith(prefix):
            return token[len(prefix):]
    return token


async def _get_client_and_token(authorization: str | None) -> tuple[TabbitClient, str, str]:
    if _tm.has_tokens:
        api_key = _cfg.get("proxy", "api_key")
        if api_key:
            bearer = _extract_bearer_token(authorization)
            if bearer != api_key:
                raise HTTPException(status_code=401, detail="invalid api key")
        token_info, client = await _tm.get_next()
        if token_info is None:
            raise HTTPException(status_code=503, detail="no available tokens (all cooling down)")
        return client, token_info.get("name", "unknown"), token_info["id"]

    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing token")
    if token not in _fallback_clients:
        _fallback_clients[token] = TabbitClient(
            token,
            _cfg.get("tabbit", "base_url"),
            _cfg.get("tabbit", "client_id"),
        )
    return _fallback_clients[token], "bearer", ""


async def _stream_handler(
    request: Request,
    client: TabbitClient,
    session_id: str,
    content: str,
    tabbit_model: str,
    req_model: str,
    completion_id: str,
    token_name: str,
    token_id: str,
    tools: list | None = None,
):
    """流式聊天完成处理器 - 借鉴 cursor2api-go 的安全包装器模式"""
    start = time.time()
    error_msg = ""
    finished = False  # 防止重复发送 finish_reason
    tool_parser = OpenAIToolCallParser(tools)

    try:
        # 发送角色 chunk
        yield _chat_chunk(completion_id, req_model, {"role": "assistant", "content": ""})

        async for event in client.send_message(session_id, content, tabbit_model):
            # 检测客户端断开
            if await request.is_disconnected():
                logger.debug("Client disconnected during streaming")
                break

            et, ed = event["event"], event["data"]

            if et == "message_chunk" and "content" in ed:
                text = ed["content"]

                # 尝试检测工具调用
                tool_calls = tool_parser.feed(text)

                if tool_calls:
                    # 检测到工具调用
                    yield _chat_chunk(completion_id, req_model, {"tool_calls": tool_calls})
                    yield _chat_chunk(completion_id, req_model, {}, "tool_calls")
                    finished = True
                    break
                elif not tool_parser.is_buffering:
                    # 没有工具或不在缓冲模式，直接发送文本
                    yield _chat_chunk(completion_id, req_model, {"content": text})

            elif et in ("message_finish", "finish"):
                if finished:
                    continue  # 避免重复发送

                # 流结束，检查是否有缓冲的工具调用
                text_content, tool_calls = tool_parser.finish()

                if tool_calls:
                    yield _chat_chunk(completion_id, req_model, {"tool_calls": tool_calls})
                    yield _chat_chunk(completion_id, req_model, {}, "tool_calls")
                elif text_content:
                    yield _chat_chunk(completion_id, req_model, {"content": text_content})
                    yield _chat_chunk(completion_id, req_model, {}, "stop")
                else:
                    yield _chat_chunk(completion_id, req_model, {}, "stop")

                finished = True

            elif et == "error":
                error_text = ed.get("message", "Unknown error")
                logger.error(f"Tabbit stream error: {error_text}")
                yield _chat_error(completion_id, req_model, error_text)
                finished = True
                break

        # 确保发送结束标记（如果还没有发送）
        if not finished:
            yield _chat_chunk(completion_id, req_model, {}, "stop")

        yield "data: [DONE]\n\n"

        if token_id:
            _tm.report_success(token_id)

    except asyncio.CancelledError:
        logger.debug("Stream cancelled by client")
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Stream error: {error_msg}", exc_info=True)
        if token_id:
            _tm.report_error(token_id)
        # 发送错误信息给客户端
        try:
            yield _chat_error(completion_id, req_model, error_msg)
            yield "data: [DONE]\n\n"
        except:
            pass
    finally:
        duration = time.time() - start
        _logs.add(LogEntry(
            model=req_model, token_name=token_name, stream=True,
            status="success" if not error_msg else "error",
            duration=duration, error=error_msg
        ))


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    req: ChatCompletionRequest | SimpleChatRequest,
    authorization: str = Header(None),
):
    try:
        client, token_name, token_id = await _get_client_and_token(authorization)
    except HTTPException as e:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

    try:
        if isinstance(req, SimpleChatRequest):
            tabbit_model = "Default"
            content = _normalize_content(req.content)
            tools = None
        else:
            tabbit_model = MODEL_MAP.get(req.model.lower(), "Default")
            tools = req.tools
            content = _build_content(req.messages, tools)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid request format")

    try:
        session_id = await client.create_chat_session()
    except Exception as e:
        if token_id:
            _tm.report_error(token_id)
        _logs.add(LogEntry(
            model=getattr(req, 'model', 'unknown'), token_name=token_name,
            stream=getattr(req, 'stream', False), status="error", error=str(e)
        ))
        raise HTTPException(status_code=502, detail=f"Failed to create chat session: {e}")

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"

    if getattr(req, 'stream', False):
        return StreamingResponse(
            _stream_handler(
                request, client, session_id, content, tabbit_model,
                getattr(req, 'model', 'unknown'), completion_id,
                token_name, token_id, tools
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
            },
        )

    # 非流式处理
    start = time.time()
    full_text = ""
    error_msg = ""
    tool_parser = OpenAIToolCallParser(tools)

    try:
        async for event in client.send_message(session_id, content, tabbit_model):
            if event["event"] == "message_chunk":
                text = event["data"].get("content", "")

                # 尝试检测工具调用
                tool_calls = tool_parser.feed(text)
                if tool_calls:
                    # 检测到工具调用，直接返回
                    if token_id:
                        _tm.report_success(token_id)
                    return {
                        "id": completion_id,
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": getattr(req, 'model', 'unknown'),
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": tool_calls}, "finish_reason": "tool_calls"}],
                        "usage": {
                            "prompt_tokens": len(content) // 4,
                            "completion_tokens": len(text) // 4,
                            "total_tokens": (len(content) + len(text)) // 4
                        }
                    }

                full_text += text

        # 流结束，检查是否有缓冲的工具调用
        text_content, tool_calls = tool_parser.finish()
        if tool_calls:
            if token_id:
                _tm.report_success(token_id)
            return {
                "id": completion_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": getattr(req, 'model', 'unknown'),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": tool_calls}, "finish_reason": "tool_calls"}],
                "usage": {
                    "prompt_tokens": len(content) // 4,
                    "completion_tokens": len(full_text) // 4,
                    "total_tokens": (len(content) + len(full_text)) // 4
                }
            }

        if text_content:
            full_text = text_content

        if token_id:
            _tm.report_success(token_id)
    except Exception as e:
        error_msg = str(e)
        if token_id:
            _tm.report_error(token_id)
        _logs.add(LogEntry(
            model=getattr(req, 'model', 'unknown'), token_name=token_name,
            stream=False, status="error", error=error_msg
        ))
        raise HTTPException(status_code=502, detail=str(e))

    duration = time.time() - start
    _logs.add(LogEntry(
        model=getattr(req, 'model', 'unknown'), token_name=token_name,
        stream=False, status="success", duration=duration, error=""
    ))

    input_tokens = len(content) // 4
    output_tokens = len(full_text) // 4

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": getattr(req, 'model', 'unknown'),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": full_text}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens
        }
    }


MODEL_INFO = {
    "best": {
        "id": "best",
        "name": "Default",
        "description": "自动选择最优模型，不消耗用量",
        "max_tokens": 100000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "default": {
        "id": "default",
        "name": "Default",
        "description": "自动选择最优模型，不消耗用量",
        "max_tokens": 100000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "claude-opus-4.8": {
        "id": "claude-opus-4.8",
        "name": "Claude-Opus-4.8",
        "description": "Anthropic 最新旗舰模型",
        "max_tokens": 200000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "claude-opus-4.7": {
        "id": "claude-opus-4.7",
        "name": "Claude-Opus-4.7",
        "description": "Anthropic 高级模型",
        "max_tokens": 200000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "claude-sonnet-4.6": {
        "id": "claude-sonnet-4.6",
        "name": "Claude-Sonnet-4.6",
        "description": "Anthropic 平衡模型",
        "max_tokens": 200000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "claude-haiku-4.5": {
        "id": "claude-haiku-4.5",
        "name": "Claude-Haiku-4.5",
        "description": "Anthropic 快速模型",
        "max_tokens": 200000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "gpt-5.5": {
        "id": "gpt-5.5",
        "name": "GPT-5.5",
        "description": "OpenAI 最新旗舰模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "gpt-5.4": {
        "id": "gpt-5.4",
        "name": "GPT-5.4",
        "description": "OpenAI 高级模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "gpt-5.2-chat": {
        "id": "gpt-5.2-chat",
        "name": "GPT-5.2-Chat",
        "description": "OpenAI 对话模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "gemini-3.5-flash": {
        "id": "gemini-3.5-flash",
        "name": "Gemini-3.5-Flash",
        "description": "Google 最新快速模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "gemini-3.1-pro": {
        "id": "gemini-3.1-pro",
        "name": "Gemini-3.1-Pro",
        "description": "Google 高级模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "kimi-k2.6": {
        "id": "kimi-k2.6",
        "name": "Kimi-K2.6",
        "description": "Moonshot 最新旗舰级多模态模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "kimi-k2.5": {
        "id": "kimi-k2.5",
        "name": "Kimi-K2.5",
        "description": "Moonshot 旗舰级多模态模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "glm-5.1": {
        "id": "glm-5.1",
        "name": "GLM-5.1",
        "description": "智谱最新文本模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "deepseek-v4-pro": {
        "id": "deepseek-v4-pro",
        "name": "DeepSeek-V4-Pro",
        "description": "DeepSeek 旗舰模型 Pro 版",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "deepseek-v4-flash": {
        "id": "deepseek-v4-flash",
        "name": "DeepSeek-V4-Flash",
        "description": "DeepSeek 旗舰模型 Flash 版",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "deepseek-v3.2": {
        "id": "deepseek-v3.2",
        "name": "DeepSeek-V3.2",
        "description": "DeepSeek MoE 语言模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "minimax-m3": {
        "id": "minimax-m3",
        "name": "MiniMax-M3",
        "description": "MiniMax 最新旗舰多模态模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "minimax-m2.7": {
        "id": "minimax-m2.7",
        "name": "MiniMax-M2.7",
        "description": "MiniMax 旗舰级文本模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "qwen3.5-plus": {
        "id": "qwen3.5-plus",
        "name": "Qwen3.5-Plus",
        "description": "阿里千问多模态大模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "doubao-seed-1.8": {
        "id": "doubao-seed-1.8",
        "name": "Doubao-Seed-1.8",
        "description": "字节跳动旗舰级多模态模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "longcat-flash-chat": {
        "id": "longcat-flash-chat",
        "name": "LongCat-Flash-Chat",
        "description": "美团自研旗舰模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    },
    "longcat-flash-thinking": {
        "id": "longcat-flash-thinking",
        "name": "LongCat-Flash-Thinking",
        "description": "美团自研旗舰思考模型",
        "max_tokens": 128000,
        "supports_streaming": True,
        "supports_vision": True
    }
}


@router.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": info["id"],
                "object": "model",
                "created": 1714502400,
                "owned_by": "tabbit",
                "name": info["name"],
                "description": info["description"],
                "max_tokens": info["max_tokens"],
                "supports_streaming": info["supports_streaming"],
                "supports_vision": info["supports_vision"]
            }
            for info in MODEL_INFO.values()
        ]
    }


@router.get("/models")
async def list_models_v0():
    return await list_models()


@router.post("/chat/completions")
async def chat_completions_v0(
    req: ChatCompletionRequest | SimpleChatRequest, authorization: str = Header(None)
):
    return await chat_completions(req, authorization)