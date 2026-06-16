# Architecture

<!-- Future agents: continue building the system architecture documentation in this file. Do not create another architecture document unless SPEC.md is updated first. -->

FormOwl uses a container-first architecture.

The canonical development, test, and deployment environment is a container. Host-installed runtimes are optional conveniences, not required assumptions.

## Language Boundaries

Python is the default language for MCP orchestration, adapters, workflow glue, review flows, test fixtures, and day-to-day debugging.

Rust owns heavy computing, safety-sensitive logic, parsers, canonical serializers, validation cores, hashing, integrity checks, concurrent processing, large raw-data transforms, and any feature whose Python implementation would expose strange or hard-to-maintain syntax.

Rust core functionality should be exposed to Python through stable bindings. Normal contributors should interact with clear Python APIs unless they are working on a core algorithm, safety boundary, or binding implementation.

## Syntax Shielding

When Python code would require unusual metaprogramming, deeply nested decorators, generated code, fragile regular expressions, complex DSLs, or unsafe dynamic evaluation, the complexity belongs behind a Rust core API.
