from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from relai_simulator.adapter_contract import (
    AgentAdapter,
    AgentTurnResult,
    ToolCallRecord,
    ToolResultRecord,
)


def _load_agent_module():
    from dota2_coach import agent as agent_module

    return agent_module


class ProjectAgentAdapter:
    def __init__(self) -> None:
        agent_module = _load_agent_module()
        self._agent_module = agent_module
        self._graph = agent_module.graph
        self.agent_or_tools = agent_module.tools
        self._messages: list[Any] = [SystemMessage(content=self._build_system_prompt())]

    def _build_system_prompt(self) -> str:
        prompt = self._agent_module._BASE_SYSTEM_PROMPT
        raw_context = os.getenv("DOTA2_COACH_DRAFT_CONTEXT_JSON", "").strip()
        if not raw_context:
            return prompt

        try:
            draft_context = json.loads(raw_context)
        except json.JSONDecodeError as error:
            raise ValueError(
                "DOTA2_COACH_DRAFT_CONTEXT_JSON must be valid JSON."
            ) from error

        if not isinstance(draft_context, dict):
            raise ValueError(
                "DOTA2_COACH_DRAFT_CONTEXT_JSON must decode to a JSON object."
            )

        return prompt + "\n\n" + self._agent_module._draft_context_block(draft_context)

    async def run_turn(self, user_message: str) -> AgentTurnResult:
        prior_messages = list(self._messages)
        invoked_messages = prior_messages + [HumanMessage(content=user_message)]
        result = await asyncio.to_thread(self._graph.invoke, {"messages": invoked_messages})
        output_messages = list(result.get("messages", invoked_messages))
        new_messages = output_messages[len(prior_messages) :]
        self._messages = output_messages

        assistant_message = _extract_assistant_message(new_messages, output_messages)
        tool_calls, tool_results = _extract_tool_records(new_messages)

        return AgentTurnResult(
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            tool_results=tool_results,
        )


def build_agent_adapter() -> AgentAdapter:
    return ProjectAgentAdapter()


def _extract_assistant_message(
    new_messages: list[Any], output_messages: list[Any]
) -> str | None:
    for message in reversed(new_messages):
        if isinstance(message, AIMessage):
            text = _message_text(message.content)
            if text is not None:
                return text

    for message in reversed(output_messages):
        if isinstance(message, AIMessage):
            text = _message_text(message.content)
            if text is not None:
                return text

    return None


def _extract_tool_records(
    messages: list[Any],
) -> tuple[list[ToolCallRecord], list[ToolResultRecord]]:
    tool_calls: list[ToolCallRecord] = []
    tool_results: list[ToolResultRecord] = []

    for message in messages:
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", []) or []:
                tool_calls.append(
                    ToolCallRecord(
                        name=str(call.get("name", "tool")),
                        arguments=call.get("args", {}),
                        call_id=_optional_string(call.get("id")),
                    )
                )
        elif isinstance(message, ToolMessage):
            tool_results.append(
                ToolResultRecord(
                    name=_tool_message_name(message),
                    result=_message_text(message.content) or _json_safe(message.content),
                    call_id=_optional_string(getattr(message, "tool_call_id", None)),
                )
            )

    return tool_calls, tool_results


def _tool_message_name(message: ToolMessage) -> str:
    name = getattr(message, "name", None)
    if isinstance(name, str) and name:
        return name

    additional_kwargs = getattr(message, "additional_kwargs", {})
    if isinstance(additional_kwargs, dict):
        maybe_name = additional_kwargs.get("name")
        if isinstance(maybe_name, str) and maybe_name:
            return maybe_name

    return "tool"


def _message_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
                continue
            if isinstance(item.get("content"), str):
                parts.append(item["content"])
        text = "\n".join(part for part in parts if part.strip())
        return text or None
    return str(content)


def _optional_string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _json_safe(value: Any) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return repr(value)
