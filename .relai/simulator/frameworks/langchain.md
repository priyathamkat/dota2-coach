# LangChain And LangGraph Reference

Read this when the project uses LangChain agents, LangChain tools, or LangGraph
graphs that call LangChain tools.

## Adapter Notes

- LangGraph compiled graphs and LangChain agents may expose blocking sync
  invocation APIs. In async simulator code, call blocking graph or agent
  invocations with `asyncio.to_thread(...)`.
- If a graph or agent uses locally reachable tools, expose the mutable tool list
  from `agent_or_tools` when practical so `relai.MockApplication` can apply
  tool-name mocks before the run.
- Record LangChain `AIMessage.tool_calls` as RELAI tool call records and
  `ToolMessage` values as RELAI tool result records.

## Tools And Mocks

- `@tool` commonly exports a `StructuredTool` object, not the original Python
  callable.
- Locally reachable LangChain `StructuredTool` objects can be mocked through
  `relai.MockApplication` when the adapter returns the tool list or framework
  object exposing a mutable `tools` list as `agent_or_tools`.
- Mark hosted/provider-side tools or remote graph services that cannot be
  replaced in local Python as `final_policy: "cannot_mock"`.

## Component Targets

- LangChain `StructuredTool` component targets are supported through the tool
  protocol.
- Use `FixedComponentInput(kwargs={...})` with keys matching the tool argument
  schema.
- Do not use positional `args` for `StructuredTool` component targets.
- In `.relai/learning-env-context.json`, write `input_guidance` for
  `StructuredTool` components in terms of named schema arguments.
