"""Sidecar-only package initializer for the document-first UAT.

The Codex sidecar imports ``formowl_mail.human_uat_orchestrator`` through the
normal package import path. This intentionally empty initializer prevents the
production package initializer from eagerly importing legacy mail, query, or
tokenizer modules before that submodule is loaded.
"""
