"""Generation: records, metering, the clone-backed tools and the arm adapters.

Importing the package forces the offline DeepEval settings, so they are in place before any module
under it imports DeepEval.
"""

from evals.run import deepeval_env

deepeval_env.configure()
