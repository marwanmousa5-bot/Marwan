"""The AI service layer (Section 5).

Deliberately isolated from routers and models so that a rule-based MVP
implementation can be replaced by a trained model or a different LLM without
touching the rest of the codebase. Every module here follows the same shape:
gather structured signals with our own logic, then (optionally) use an LLM
only to phrase and rank - never to invent the underlying facts.
"""
