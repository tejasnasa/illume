# Illume Documentation

This directory is the written tour of Illume: what the system does, how each part works, why it
was built the way it was, and what to do when something breaks. It is written for someone who has never opened the repository before, and it assumes no familiarity with the internal vocabulary. Every term is either explained where it first appears, or collected in the glossary at the end of this page.

If you only read one document, read [architecture.md](architecture.md). It gives you the shape of
the whole system in about fifteen minutes, and every other document here hangs off it.

## How to read this

Pick the path that matches what you are trying to do.

| If you want to…                                                | Start here                                                       |
| -------------------------------------------------------------- | ---------------------------------------------------------------- |
| Understand what Illume is and how the pieces fit together       | [architecture.md](architecture.md)                               |
| Get it running on your machine                                  | [../README.md](../README.md)                                     |
| Understand the full analysis pipeline                           | [pipeline/ingestion.md](pipeline/ingestion.md)                   |
| Understand how a repository stays up to date on its own         | [pipeline/sync.md](pipeline/sync.md)                             |
| Understand how the LLM artefacts are produced                   | [pipeline/generation.md](pipeline/generation.md)                 |
| Understand the RAG chat and how retrieval works                 | [pipeline/retrieval.md](pipeline/retrieval.md)                   |
| Understand the dependency graph and the 3D view                  | [pipeline/graph.md](pipeline/graph.md)                           |
| Understand ownership, knowledge silos, and criticality           | [pipeline/git-intelligence.md](pipeline/git-intelligence.md)     |
| Call the HTTP API or wire up a client                           | [api.md](api.md) · [websockets.md](websockets.md)                |
| Work on the Next.js application                                 | [frontend.md](frontend.md)                                       |
| Change the database schema                                      | [data-model.md](data-model.md)                                   |
| Deploy or operate a running instance                            | [deployment.md](deployment.md)                                   |
| Run, write, or debug the test suites                            | [testing.md](testing.md)                                         |
| Review the design decisions and their trade-offs                | [architecture.md](architecture.md#design-decisions-and-trade-offs)              |

Each pipeline document ends with a **Troubleshooting** section describing the failure signatures
for that stage and what they mean, so a symptom can be traced without reading the whole system.

## The documents

### Foundations

- **[architecture.md](architecture.md)** — The system in one document: the two applications, the
  request and job flows, the async/sync split, the data lifecycle through the pipeline, and the
  design decisions behind it all, including the trade-offs that were deliberately accepted.

- **[data-model.md](data-model.md)** — The database schema: every table, its columns,
  relationships, and constraints, plus how migrations are written and the invariants the schema
  relies on.

### The pipeline

The analysis pipeline is the heart of the product. These six documents follow it end to end.

- **[pipeline/ingestion.md](pipeline/ingestion.md)** — The full analysis run: cloning, parsing,
  dependency resolution, git history mining, criticality scoring, and the LLM phase. Covers how
  stages are overlapped, why certain stages must run in a particular order, how failures are
  retried, and how progress reaches the browser.

- **[pipeline/git-intelligence.md](pipeline/git-intelligence.md)** — The git-history stages of the
  run above: ownership mining, knowledge silos, test detection, and the criticality score built from
  them and from dependency fan-in.

- **[pipeline/sync.md](pipeline/sync.md)** — Automatic background updates. How a due repository is
  claimed, how a change is detected cheaply, how only the changed files are reprocessed, and how
  the two commit watermarks let a partially failed update resume instead of restarting.

- **[pipeline/generation.md](pipeline/generation.md)** — The LLM-written artefacts: the glossary,
  the annotated reading order, and the architecture brief. Covers the provider abstraction, how a
  user's own API key is threaded through, and how the system degrades when a model call fails.

- **[pipeline/retrieval.md](pipeline/retrieval.md)** — The RAG chat. How source is turned into
  embeddable chunks, how a question is answered from them, how the result set is diversified, and
  where the design currently falls short.

- **[pipeline/graph.md](pipeline/graph.md)** — The dependency graph that powers the reading order
  and the 3D visualisation: how edges are derived and collapsed, how re-export files are resolved,
  and how the client renders it.

### Interfaces

- **[api.md](api.md)** — The HTTP API: every endpoint grouped by router, the authentication each
  one requires, the identifier conventions, and the error semantics.

- **[websockets.md](websockets.md)** — The live progress stream: the channel naming, the frame
  format, and the stage/phase contract a client renders from.

- **[exports.md](exports.md)** — The compact text export of a repository analysis, its section
  format, and what it is for.

- **[frontend.md](frontend.md)** — The Next.js application: routing, the server/client component
  split, the three data-fetching strategies and why all three exist, and the WebGL rendering
  constraints.

### Supporting systems

- **[auth.md](auth.md)** — Authentication and authorisation: the JWT cookie, the middleware gate,
  password handling, GitHub OAuth, and how per-user data isolation is enforced.

- **[deployment.md](deployment.md)** — Building and running Illume in production: the container
  image, the three production processes, the CI/CD workflows, and the state that must survive a
  deploy.

- **[testing.md](testing.md)** — The three test suites, what each layer is for, how to run them,
  and the conventions to follow when adding a test.

## Conventions in this documentation

A few conventions keep the documents consistent and trustworthy:

- **Claims are tied to code.** Where a behaviour matters, the document names the module or function
  that implements it, so it can be checked rather than believed.
- **Limitations are stated plainly.** Where a feature is incomplete, approximated, or known to be
  wrong, the document says so instead of describing the intended behaviour. A document that only
  describes the happy path is not useful for debugging.
- **Numbers carry their context.** Limits, thresholds, and caps are given with the module that
  defines them, because most of them are constants that can change.
- **Diagrams are Mermaid.** Flow and structure diagrams use Mermaid fenced blocks, so GitHub and
  most editors render them as real diagrams. Directory trees stay as plain text, because a rendered
  graph reads worse than an indented listing for a file tree.
- **Configuration lives with the behaviour it controls.** Environment variables and tunable constants
  are documented in the document that explains what they do — the sync intervals in
  [pipeline/sync.md](pipeline/sync.md), the generation credentials in
  [pipeline/generation.md](pipeline/generation.md), the production env file in
  [deployment.md](deployment.md) — rather than in a central reference that would duplicate all of them
  and go stale on its own.

## Glossary

Terms used throughout these documents. Several of them mean something more specific inside Illume
than they do in general use.

| Term                       | Meaning in Illume                                                                                                                                          |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Ingest**                 | A full analysis of a repository from scratch. Triggered when a repository is added, or by an explicit re-ingest.                                             |
| **Sync**                   | An incremental update of an already-ingested repository, run automatically on a schedule. Reuses the ingest pipeline but processes only what changed.        |
| **Snapshot**               | The pair of branch and commit SHA that an analysis reflects. A repository has two: one for deterministic data, one for LLM artefacts.                       |
| **Watermark**              | A stored commit SHA recording how current a piece of derived data is. Used to decide whether a sync needs to do anything.                                   |
| **Stage**                  | One named unit of work inside the pipeline (clone, parse, embed, …). Stages emit progress frames and are timed individually.                                |
| **Phase**                  | The lifecycle marker on a progress frame: `started`, `progress`, `done`, or `failed`. The client renders node states from this rather than from event names.  |
| **Symbol**                 | A function, class, or method extracted from source by the parser. The unit the glossary, embeddings, and symbol-level graph are built on.                  |
| **Criticality**            | A three-level classification (critical / caution / safe) assigned to each file from fan-in, path sensitivity, staleness, and test presence.                |
| **Fan-in / fan-out**       | How many other files depend on this one (fan-in) and how many it depends on (fan-out). Persisted at ingest.                                                 |
| **Barrel**                 | A file that only re-exports from others (`index.ts`, `__init__.py`). It has no symbols of its own, so graph edges are resolved through it to a real target. |
| **Reading order**          | The generated, topologically sorted sequence of files a newcomer should read, with a short annotation on each.                                              |
| **BYOK**                   | Bring Your Own Key. The model where a user supplies their own LLM provider credentials instead of spending the operator's.                                 |
| **Free tier**              | The operator-funded allowance a user gets before BYOK is required: one ingestion and a small number of chat questions.                                      |
| **Embedding**              | A vector representation of a text chunk, stored in Postgres via pgvector and searched by cosine distance for RAG retrieval.                                 |
