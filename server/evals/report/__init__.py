"""The report: tables, statistics and figures built from a run directory's files alone.

Nothing in this package reads the eval database or calls a provider. ``build_report`` is the
entry point; the run's context (corpus counts, files at the base commit, the import graph) is
captured into the run directory when the run is generated.
"""

from evals.report.build import Report, ReportError, build_report

__all__ = ["Report", "ReportError", "build_report"]
