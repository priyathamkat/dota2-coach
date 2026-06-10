# RELAI Simulator SDK Reference

Use this reference instead of reading RELAI SDK source while scaffolding a
project simulator.

## Learning Environments

- Load a Python learning environment with `relai.load_learning_environment(path)`.
- Agent environments use `FixedInput` or `PersonaInput`.
- Component environments use `ComponentTarget(import_path="pkg.mod:func")`
  plus `FixedComponentInput` or `GeneratedComponentInput`.
- Every `RELAIEnvironment`, `CodeEvaluator`, and `LLMJudgeEvaluator` needs a
  short `description`.

## Framework References

After identifying the project framework, read a matching file under
`.relai/simulator/frameworks/` before writing framework-specific adapter,
tool, mock, or component-target logic. Skip framework files that do not match
the project.

## Generic Runner Flow

The CLI-owned runner already handles this flow:

```python
environment = relai.load_learning_environment(learning_env_path)
with relai.TranscriptWriter.from_environment(environment, base_dir=project_root) as transcript:
    if isinstance(environment.target, relai.ComponentTarget):
        result = await relai.run_component_environment(environment, transcript)
    else:
        # The generic runner calls relai_simulator.adapter.build_agent_adapter().
        ...
    global_evaluators = relai.filter_global_evaluators_for_environment(
        relai.load_global_evaluators(project_root),
        environment,
        project_root=project_root,
    )
    evaluators = relai.combine_evaluators(
        environment.evaluators,
        global_evaluators,
    )
    await relai.run_evaluators(
        evaluators,
        result,
        transcript_writer=transcript,
        continue_on_error=True,
    )
    result = transcript.to_simulation_result(
        final_output=result.final_output,
        stop_reason=result.stop_reason,
        metadata=result.metadata,
    )
relai.write_simulation_result_json(result, result_json_path)
```

## Adapter Contract

Implement `.relai/simulator/src/relai_simulator/adapter.py`.

`build_agent_adapter()` must return an object with:

- `agent_or_tools`: framework agent, mutable tool list, or `None`.
- `run_turn(user_message)`: sync or async method.

`run_turn` may return:

- `AgentTurnResult(assistant_message=..., metadata={...})`
- a plain string
- a dict with `assistant_message` or `final_output`
- an object with `assistant_message` or `final_output`

For blocking sync agent calls, make `run_turn` async and use
`await asyncio.to_thread(sync_call, ...)`.

## Mocks And Transcripts

- The generic runner enters `relai.MockApplication(environment.mocks)` before
  building the adapter.
- Import-path mocks support dotted attributes after the colon, such as
  `pkg.module:Class.method`, so multi-agent orchestrator subagent methods can
  be patched as component boundaries.
- If `agent_or_tools` is not `None`, the runner calls
  `mock_app.apply_tool_mocks(agent_or_tools)`.
- The runner records user messages, agent messages, adapter tool call/result
  records, observed RELAI mock calls, errors, run end, evaluator events, and
  result JSON.

## Dependency Edits

Do not add `relai` or other RELAI SDK dependencies. The CLI owns
SDK installation. If the project package must be importable, add the editable
project install inside the `BEGIN PROJECT DEPENDENCY INSTALL` section of
`.relai/simulator/install.sh`.
