# CHANGELOG

<!-- version list -->

## Unreleased

### Breaking Changes

- **`SynthesisAgentOutput.sources` removed**: The `sources: list[Source]` field and the `Source`
  model have been deleted from `SynthesisAgentOutput`. RAG sources are now surfaced exclusively
  via `AgentResponseData.sources` at the orchestrator layer. Any consumer that previously
  accessed `synthesis_output.sources` must be updated to read from `AgentResponseData` instead.

## v0.1.2 (2025-10-10)

- Initial Release
