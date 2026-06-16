# formowl

<!-- Future agents: continue building from the files listed in SPEC.md section 13. Do not create parallel replacement files unless the specification is updated first. -->

formowl is a source-preserving knowledge management system built around two decoupled MCP servers:

- Project MCP
- Wiki MCP

Project MCP retrieves project execution context from systems such as OpenProject.

Wiki MCP generates and manages markdown/wiki knowledge artifacts.

Both MCPs interoperate through `@formowl/contract`.

FormOwl is container-first. Development, testing, and deployment should run from containers so the project does not depend on host-installed runtimes.

The primary implementation languages are Python and Rust. Python is the readable orchestration and debugging layer. Rust owns heavy computing, security-sensitive logic, parsers, validation, integrity checks, and any functionality whose Python implementation would expose strange or hard-to-maintain syntax.

Rust core functionality should be exposed to Python through stable bindings.
