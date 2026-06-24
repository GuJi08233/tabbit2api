"""
工具调用解析模块
参考 go-proxy 的简单 JSON 格式实现
"""

import json
import re
import uuid
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("tabbit2openai")


def generate_tool_call_id() -> str:
    """生成工具调用 ID，格式: call_ + 随机字符"""
    return f"call_{uuid.uuid4().hex[:24]}"


def build_tools_prompt(tools: List[dict]) -> str:
    """
    构建工具提示文本
    参考 go-proxy 的简单 JSON 格式
    """
    if not tools:
        return ""

    desc_parts = []
    for tool in tools:
        fn = tool.get("function", {})
        name = fn.get("name", "")
        if not name:
            continue

        desc_parts.append(f"### {name}")
        if fn.get("description"):
            desc_parts.append(f"Description: {fn['description']}")
        if fn.get("parameters"):
            param_json = json.dumps(fn["parameters"], ensure_ascii=False)
            desc_parts.append(f"Parameters: {param_json}")
        desc_parts.append("")

    return f"""You are an assistant that can use tools. Follow these rules STRICTLY:

1. If you need to use a tool, your ENTIRE response must be a single JSON object in this exact format:
{{"tool_calls":[{{"name":"TOOL_NAME","arguments":{{"param":"value"}}}}]}}

2. Do NOT include markdown code blocks, explanations, or any other text before or after the JSON.
3. If no tool is needed, answer normally and do NOT output any JSON.

Available tools:
{chr(10).join(desc_parts)}
Examples:
User: What is the weather in Beijing?
Assistant: {{"tool_calls":[{{"name":"get_weather","arguments":{{"location":"Beijing"}}}}]}}

User: Hello
Assistant: Hello! How can I help you today?"""


def parse_tool_calls(content: str) -> Optional[List[dict]]:
    """
    从响应内容中解析工具调用
    参考 go-proxy 的实现：查找 tool_calls 关键字，然后用括号匹配找到完整 JSON
    """
    if not content:
        return None

    # 查找 tool_calls 关键字
    idx = content.find("tool_calls")
    if idx < 0:
        return None

    # 向前找到最近的 {
    start = content.rfind("{", 0, idx)
    if start < 0:
        return None

    # 用括号匹配找到完整的 JSON
    depth = 0
    end = -1
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end < 0:
        return None

    raw = content[start:end]

    # 尝试解析 JSON
    parsed = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # 尝试修复常见的 JSON 错误
        # 1. 单引号替换为双引号
        fixed = raw.replace("'", '"')
        # 2. 键添加引号
        fixed = re.sub(r'(?:(\w+)\s*:)', r'"\1":', fixed)
        try:
            parsed = json.loads(fixed)
        except json.JSONDecodeError:
            return None

    if not parsed or "tool_calls" not in parsed:
        return None

    tool_calls = parsed["tool_calls"]
    if not isinstance(tool_calls, list) or len(tool_calls) == 0:
        return None

    # 转换为 OpenAI 格式
    result = []
    for i, tc in enumerate(tool_calls):
        if not isinstance(tc, dict):
            continue

        name = tc.get("name", "")
        if not name:
            continue

        arguments = tc.get("arguments", {})
        if isinstance(arguments, str):
            args_str = arguments
        else:
            args_str = json.dumps(arguments, ensure_ascii=False)

        result.append({
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": args_str,
            },
        })

    return result if result else None


class OpenAIToolCallParser:
    """
    OpenAI 格式的工具调用解析器
    参考 go-proxy 的流式处理方式：缓冲所有内容，在结束时才解析
    """

    def __init__(self, tools: Optional[List[dict]] = None):
        self.tools = tools or []
        self.has_tools = len(self.tools) > 0
        self.buffer = ""
        self.tool_call_detected = False

    def feed(self, text: str) -> Optional[List[dict]]:
        """
        喂入文本，尝试检测工具调用
        返回: 工具调用列表，或 None（还在缓冲中）
        """
        if not self.has_tools:
            return None

        self.buffer += text

        # 检查是否包含 tool_calls 关键字
        if "tool_calls" in self.buffer:
            self.tool_call_detected = True

        # 如果检测到工具调用特征，尝试解析
        if self.tool_call_detected:
            tool_calls = parse_tool_calls(self.buffer)
            if tool_calls:
                return tool_calls

        return None

    def finish(self) -> tuple[str, Optional[List[dict]]]:
        """
        结束解析
        返回: (文本内容, 工具调用列表)
        """
        if not self.buffer:
            return "", None

        if self.tool_call_detected:
            tool_calls = parse_tool_calls(self.buffer)
            if tool_calls:
                return "", tool_calls

        return self.buffer, None

    @property
    def is_buffering(self) -> bool:
        """是否正在缓冲（可能包含工具调用）"""
        return self.has_tools and len(self.buffer) > 0
