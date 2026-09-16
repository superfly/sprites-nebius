"""Adapted conversion subset, MIT (c) 2024 fuergaosi233; see SOURCE.json.

Unsupported Anthropic server-side tools/thinking are rejected, never silently
turned into an inference call. No content or provider error body is logged.
"""

import json


class ConversionError(ValueError):
    """Static, content-free input or upstream protocol error."""


def text_content(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise ConversionError("Expected text content")
    if any(not isinstance(b, dict) or b.get("type") != "text"
           or not isinstance(b.get("text"), str) for b in value):
        raise ConversionError("Only text tool results and system blocks are supported")
    return "\n".join(b["text"] for b in value)


def request_to_openai(body, model, max_tokens):
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
        raise ConversionError("Expected a messages array")
    tokens = body.get("max_tokens")
    if isinstance(tokens, bool) or not isinstance(tokens, int) or not 1 <= tokens <= max_tokens:
        raise ConversionError("Requested token budget is outside the configured limit")
    if body.get("thinking", {}).get("type", "disabled") != "disabled":
        raise ConversionError("Anthropic thinking is unsupported by this adapter")
    messages = []
    if body.get("system"):
        messages.append({"role": "system", "content": text_content(body["system"])})
    pending = set()
    history = body["messages"]
    for index, message in enumerate(history):
        if not isinstance(message, dict) or message.get("role") not in ("user", "assistant", "system"):
            raise ConversionError("Unsupported message role")
        role, content = message["role"], message.get("content")
        if role == "system":
            # Claude Code 2.1.273 uses mid-conversation system instructions.
            # Keep their priority and position; never downgrade them to user
            # text or promote a tool result. Tool changes/effort stay unsupported.
            if set(message) - {"role", "content", "clear_at"} or pending:
                raise ConversionError("Unsupported mid-conversation system settings")
            before = next((m.get("role") for m in reversed(history[:index]) if isinstance(m, dict) and m.get("role") != "system"), None)
            after = next((m.get("role") for m in history[index + 1:] if isinstance(m, dict) and m.get("role") != "system"), None)
            if before != "user" or after not in (None, "assistant"):
                raise ConversionError("Invalid mid-conversation system position")
            text = text_content(content)
            clear = message.get("clear_at", "never")
            if clear not in ("never", "next_user_message"):
                raise ConversionError("Unsupported system clearing rule")
            if clear == "next_user_message" and any(isinstance(m, dict) and m.get("role") == "user" for m in history[index + 1:]):
                continue
            messages.append({"role": "system", "content": text})
            continue
        if isinstance(content, str):
            if pending:
                raise ConversionError("Missing tool results")
            messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            raise ConversionError("Expected message content")
        text, calls, results = [], [], []
        for block in content:
            if not isinstance(block, dict):
                raise ConversionError("Invalid content block")
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str):
                text.append(block["text"])
            elif kind == "tool_use" and role == "assistant":
                if pending or not all(isinstance(block.get(k), str) and block[k] for k in ("id", "name")) or not isinstance(block.get("input"), dict):
                    raise ConversionError("Invalid tool call")
                calls.append({"id": block["id"], "type": "function", "function": {
                    "name": block["name"], "arguments": json.dumps(block["input"])}})
            elif kind == "tool_result" and role == "user":
                if block.get("tool_use_id") not in pending:
                    raise ConversionError("Unexpected or duplicate tool result")
                pending.remove(block["tool_use_id"])
                results.append({"role": "tool", "tool_call_id": block["tool_use_id"],
                                "content": text_content(block.get("content", ""))})
            else:
                raise ConversionError("Unsupported content block")
        if pending:
            raise ConversionError("Missing tool results")
        messages.extend(results)
        if text or calls:
            converted = {"role": role, "content": "\n".join(text) or None}
            if calls:
                pending = {c["id"] for c in calls}
                if len(pending) != len(calls):
                    raise ConversionError("Duplicate tool call ID")
                converted["tool_calls"] = calls
            messages.append(converted)
    if pending:
        raise ConversionError("Missing tool results")
    if not messages:
        raise ConversionError("Expected at least one message")
    request = {"model": model, "messages": messages, "max_tokens": tokens,
               "stream": body.get("stream", False)}
    if not isinstance(request["stream"], bool):
        raise ConversionError("stream must be a boolean")
    for source, target in (("temperature", "temperature"), ("top_p", "top_p"), ("stop_sequences", "stop")):
        if body.get(source) is not None:
            request[target] = body[source]
    tools = []
    for tool in body.get("tools", []):
        if not isinstance(tool, dict) or tool.get("type", "custom") != "custom" or not isinstance(tool.get("name"), str) or not isinstance(tool.get("input_schema"), dict):
            raise ConversionError("Only client-executed custom tools are supported; search is disabled")
        tools.append({"type": "function", "function": {"name": tool["name"],
                      "description": tool.get("description", ""), "parameters": tool["input_schema"]}})
    if tools:
        request["tools"] = tools
    choice = body.get("tool_choice", {"type": "auto"})
    if not isinstance(choice, dict):
        raise ConversionError("Invalid tool choice")
    kind = choice.get("type")
    if kind in ("auto", "any", "none"):
        if tools:
            request["tool_choice"] = {"auto": "auto", "any": "required", "none": "none"}[kind]
    elif kind == "tool" and any(t["function"]["name"] == choice.get("name") for t in tools):
        request["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}}
    else:
        raise ConversionError("Invalid tool choice")
    return request


def stop_reason(value):
    reasons = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
    if value not in reasons:
        raise ConversionError("Unsupported upstream finish reason")
    return reasons[value]


def usage(value):
    if not isinstance(value, dict):
        raise ConversionError("Missing upstream token usage")
    output = {}
    for source, target in (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens")):
        count = value.get(source)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ConversionError("Invalid upstream token usage")
        output[target] = count
    return output


def tool_block(call):
    try:
        data = json.loads(call["function"]["arguments"])
        if not isinstance(data, dict) or not all(isinstance(call.get(k), str) and call[k] for k in ("id",)) or not isinstance(call["function"]["name"], str):
            raise ValueError()
        return {"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": data}
    except (KeyError, TypeError, ValueError):
        raise ConversionError("Malformed upstream tool call") from None


def response_to_claude(body, original_model, message_id):
    try:
        choice = body["choices"][0]
        message = choice["message"]
        blocks = []
        if message.get("content"):
            blocks.append({"type": "text", "text": message["content"]})
        blocks.extend(tool_block(call) for call in message.get("tool_calls", []) or [])
        return {"id": message_id, "type": "message", "role": "assistant", "model": original_model,
                "content": blocks or [{"type": "text", "text": ""}],
                "stop_reason": stop_reason(choice["finish_reason"]), "stop_sequence": None,
                "usage": usage(body.get("usage"))}
    except (KeyError, IndexError, TypeError):
        raise ConversionError("Malformed upstream response") from None
