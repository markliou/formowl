# FormOwl System Backbone Agent Goal

## Role

FormOwl System Backbone Agent.

Durable role definition: `docs/agent-roles.md`.

Status: `waiting-for-owner`

## Abstract

This file is the durable goal placeholder for the agent running on the other
machine. The owning agent should fill in its exact objective, status, blockers,
last verified commit, current owner paths, and next action before relying on
session-local state.

The system backbone track exists to build and harden the container-first
product and service skeleton that lets the Knowledge Graph Research Agent's
contracts and algorithms run safely. Its work should preserve governed
task-oriented interfaces and keep raw files, databases, object stores, worker
scratch paths, parser internals, and backend control planes out of
ChatGPT-facing tools.

## Expected Scope

Likely owned by this agent:

- Repository, container, dev-container, compose/runtime, and CI verification
  wiring.
- MCP transport, gateway plumbing, tool schemas, safe error envelopes, and
  session context handling.
- Project MCP and Wiki MCP service boundaries.
- Upload sessions, storage backend registry configuration, object-store
  integration, worker execution boundaries, and database-backed stores.
- Operational audit, logging, configuration loading, migrations, smoke
  harnesses, and production adapter boundaries.
- Retrieval gateway behavior for evidence snippets and raw asset access through
  FormOwl locators and permission checks.

## Required Fill-In

The owning System Backbone Agent should replace this section with:

- Current objective.
- Current status: `active`, `waiting-for-owner`, `blocked`, or `complete`.
- Owner paths for the active slice.
- Acceptance criteria and canonical verification commands.
- Known blockers and cross-agent dependencies.
- Last verified commit and branch.
- Next concrete action.
- Handoff notes for the KG Research Agent.

## Boundary Reminder

The system backbone work must not collapse ingestion, graph governance, user
graph assembly, and wiki projection into one direct pipeline. It should provide
stable infrastructure and service boundaries that allow the KG research layer
to evolve without rewriting service plumbing.
