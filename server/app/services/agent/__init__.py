"""The agent: a tool-calling loop over a repository, built as a LangGraph graph.

``run_agent`` in :mod:`app.services.agent.runner` is the entry point; the graph is
in ``graph``, the nodes in ``nodes``, the tools in ``tools``, and the limits in
``budgets``.
"""
