"""
工具调用解析模块
借鉴 go-proxy 的简单 JSON 格式实现
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
    借鉴 go-proxy 的简单 JSON 格式
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
4. When the user asks for information that requires a tool (like weather, search, calculations), you MUST use the appropriate tool. Do NOT answer from your own knowledge.

Available tools:
{chr(10).join(desc_parts)}
Examples:
User: What is the weather in Beijing?
Assistant: {{"tool_calls":[{{"name":"get_weather","arguments":{{"location":"Beijing"}}}}]}}

User: Hello
Assistant: Hello! How can I help you today?"""


def _validate_tool_calls(
    tool_calls: List[dict], valid_names: set
) -> Optional[List[dict]]:
    """验证并标准化工具调用"""
    if not isinstance(tool_calls, list) or len(tool_calls) == 0:
        return None

    result = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue

        name = tc.get("name", "")
        if not name or (valid_names and name not in valid_names):
            logger.warning(f"Invalid tool name: {name}")
            continue

        arguments = tc.get("arguments", {})
        if isinstance(arguments, str):
            # 尝试解析 JSON 字符串
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        elif not isinstance(arguments, dict):
            arguments = {}

        result.append(
            {
                "id": generate_tool_call_id(),
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }
        )

    return result if result else None


def _find_json_in_text(text: str) -> Optional[dict]:
    """在文本中查找 JSON 对象"""
    # 尝试查找 {"tool_calls" 或 {"tool_calls"
    patterns = ['{"tool_calls"', '{" tool_calls"']

    for pattern in patterns:
        start = text.find(pattern)
        if start < 0:
            continue

        # 用括号匹配找到完整的 JSON
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        # 尝试修复常见的 JSON 错误
                        raw = text[start : i + 1]
                        # 修复单引号
                        raw = raw.replace("'", '"')
                        # 修复缺少引号的键
                        raw = re.sub(r"(?<=[{,])\s*(\w+)\s*:", r'"\1":', raw)
                        try:
                            return json.loads(raw)
                        except json.JSONDecodeError:
                            break

    return None


def parse_tool_calls(
    content: str, valid_names: Optional[set] = None
) -> Optional[List[dict]]:
    """
    从响应内容中解析工具调用

    支持的格式:
    1. 纯 JSON: {"tool_calls":[...]}
    2. 嵌入文本中的 JSON

    返回: 工具调用列表，或 None（如果没有工具调用）
    """
    if not content or not content.strip():
        return None

    content = content.strip()

    # 1. 尝试直接解析整个内容
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "tool_calls" in data:
            return _validate_tool_calls(data["tool_calls"], valid_names or set())
    except json.JSONDecodeError:
        pass

    # 2. 尝试在文本中查找 JSON
    data = _find_json_in_text(content)
    if data and "tool_calls" in data:
        return _validate_tool_calls(data["tool_calls"], valid_names or set())

    return None


def extract_text_without_tool_calls(content: str) -> str:
    """提取文本内容，移除工具调用 JSON"""
    if not content:
        return ""

    # 查找工具调用 JSON
    data = _find_json_in_text(content)
    if data and "tool_calls" in data:
        # 移除 JSON 部分，保留其他文本
        json_str = json.dumps(data, ensure_ascii=False)
        text = content.replace(json_str, "").strip()
        return text if text else ""

    return content


class OpenAIToolCallParser:
    """
    OpenAI 格式的工具调用解析器
    用于流式和非流式响应
    """

    def __init__(self, tools: Optional[List[dict]] = None):
        self.tools = tools or []
        self.tool_names = set()
        for tool in self.tools:
            fn = tool.get("function", {})
            if fn.get("name"):
                self.tool_names.add(fn["name"])

        self.buffer = ""
        self.has_tools = len(self.tools) > 0
        self.tool_call_detected = False

    def feed(self, text: str) -> Optional[List[dict]]:
        """
        喂入文本，尝试检测工具调用

        返回: 工具调用列表，或 None（还在缓冲中）
        """
        if not self.has_tools:
            return None

        self.buffer += text

        # 检查是否包含工具调用特征
        if '{"tool_calls"' in self.buffer or '{"tool_calls"' in self.buffer:
            self.tool_call_detected = True

        # 如果检测到工具调用特征，尝试解析
        if self.tool_call_detected:
            tool_calls = parse_tool_calls(self.buffer, self.tool_names)
            if tool_calls:
                return tool_calls

        return None

    def finish(self) -> tuple[str, Optional[List[dict]]]:
        """
        结束解析

        返回: (文本内容, 工具调用列表)
        - 如果有工具调用，文本内容为空
        - 如果没有工具调用，工具调用列表为 None
        """
        if not self.buffer:
            return "", None

        if self.tool_call_detected:
            tool_calls = parse_tool_calls(self.buffer, self.tool_names)
            if tool_calls:
                return "", tool_calls

        return self.buffer, None

    @property
    def is_buffering(self) -> bool:
        """是否正在缓冲（可能包含工具调用）"""
        return self.has_tools and len(self.buffer) > 0
