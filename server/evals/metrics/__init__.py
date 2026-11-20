"""Pure metric functions over gold items and recorded generations.

Nothing here reads a database or the network. Inputs are gold items, generation records, the
set of files at the base commit and, for trajectories, an import adjacency passed in as a
mapping. Loading those is the report's job.
"""
