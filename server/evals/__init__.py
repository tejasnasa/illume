"""Evaluation harness for Illume.

Importing this package has no side effects. Only ``evals.__main__`` imports
``evals.settings``, which rewrites the process environment to point at the isolated eval
stack; every other module takes what it needs as parameters.
"""
