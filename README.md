# formowl

<!-- Future agents: continue building from the files listed in SPEC.md section 13. Do not create parallel replacement files unless the specification is updated first. -->

formowl is a source-preserving knowledge management system built around two decoupled MCP servers:

- Project MCP
- Wiki MCP

Project MCP retrieves project execution context from systems such as OpenProject.

Wiki MCP generates and manages markdown/wiki knowledge artifacts.

Both MCPs interoperate through `@formowl/contract`.
