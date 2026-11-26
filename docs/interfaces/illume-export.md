# The `.illume` export

The `.illume` file is a compact plain-text summary of one ingested repository, sized to paste into an LLM's context or to read at a glance: identity and stack, the architecture brief, the file dependency edges, the main symbols of the most-imported files, and the risky hotspots. It is produced on demand by [`illume_exporter.py`](../../server/app/services/illume_exporter.py), served by one route, and downloaded from the web client's repository settings and from the mobile app. This page documents the route, the format section by section, every cap, and what the file leaves out.

## Terms used on this page

- **Section**: a block of the file that starts with a line `@@NAME`. There are five, always in the same order.
- **Edge**: here, one ordered pair of files where the first imports the second, after collapsing symbol-level edges.
- **Hotspot**: a file whose criticality label is anything other than `safe`.

## The route

`GET /api/v1/repository/{repo_id}/export/illume` in [`api/v1/repository.py`](../../server/app/api/v1/repository.py), function `export_repository_illume`. `repo_id` is the UUID.

| Status | When                                                                                    |
| ------ | --------------------------------------------------------------------------------------- |
| 200    | `text/plain` body with `Content-Disposition: attachment; filename="{repo.name}.illume"` |
| 400    | the repository's status is not `ready`; the detail names the current status             |
| 404    | not found, not the caller's, or it has no files (`Repository details not found`)        |

Ownership is checked in the query (`Repository.user_id == current_user.id`), so another user's repository returns 404, not 403; `tests/security/test_idor.py` covers this. Nothing is cached: each request rebuilds the text from the database.

### Who calls it

| Caller                                                                                        | How                                                                                                                                                                                                                                      |
| --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`ExportIllumeButton`](../../client/src/components/ExportIllumeButton.tsx), in `RepoSettings` | calls the server action [`exportIllumeAction`](../../client/src/actions/exportIllume.ts), which forwards the cookie and returns the text; the button wraps it in a `Blob` and clicks a temporary download link named `{repoName}.illume` |
| the mobile app, [`src/api/settings.ts`](../../mobile/src/api/settings.ts)                     | `apiGet<string>` on the same path                                                                                                                                                                                                        |

The server action reports any non-2xx response as "Failed to export repository data", so the 400 detail about status does not reach the user.

## The format

An illustrative export of a small repository:

```text
@@META
repo=illume
url=https://github.com/example/illume
branch=main
lang=Python
generated=2026-11-26
files=412 symbols=9120 edges=1384
stack=Python,TypeScript,FastAPI,Next.js,PostgreSQL,Redis,Docker,GitHub Actions
entry=server/app/main.py,client/src/app/layout.tsx

@@ARCH
Illume is split into a FastAPI API and a Celery worker...

@@GRAPH
server/app/api/v1/graph.py -> server/app/services/graph_builder.py [imports:build_graph]
server/app/services/scanner.py -> server/app/services/parser.py [imports:parse_file]
... and 884 more edges

@@SYMBOLS
server/app/core/config.py: cls:Settings
server/app/models/repository.py: cls:Repository fn:...

@@HOTSPOTS
server/app/tasks/ingest.py [critical,fan_in=3,cc=14]
server/app/services/scanner.py [caution,fan_in=6,cc=22]
```

### `@@META`

| Key         | From                                                                                                                                                                                           |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `repo`      | `repositories.name`                                                                                                                                                                            |
| `url`       | `github_url`, or empty                                                                                                                                                                         |
| `branch`    | `default_branch`, or `main`; **not** the ingested branch                                                                                                                                       |
| `lang`      | `primary_language`, or `unknown`                                                                                                                                                               |
| `generated` | today's date in UTC, `YYYY-MM-DD`                                                                                                                                                              |
| `files`     | number of `files` rows                                                                                                                                                                         |
| `symbols`   | number of `ast_symbols` rows of every kind, imports included                                                                                                                                   |
| `edges`     | number of symbol-level edge rows returned by the edge query, before collapsing                                                                                                                 |
| `stack`     | `detected_stack` flattened: the values (or dict keys, or a bare string) of `languages`, `frameworks`, `databases`, `infrastructure` and `ci_cd`, de-duplicated in order and joined with commas |
| `entry`     | `entry_points` joined with commas (a list, or a dict's keys)                                                                                                                                   |

### `@@ARCH`

The stored `architecture_summary`, trimmed, or `No architecture summary generated.` See [the architecture brief](../pipeline/generation.md#the-architecture-brief).

### `@@GRAPH`

1. Edges come from `query_file_edges_async(db, repo_id, include_target_symbol=True)` in [`file_graph.py`](../../server/app/services/file_graph.py), which yields `(dep_type, source_file, target_file, target_symbol_name)` for every dependency whose two ends are in the repository.
2. Rows are grouped by `(source_path, target_path)`, dropping self-edges, with the set of target symbol names collected per `dep_type`.
3. Pairs are sorted by source path then target path, and the first **500** are written, one line each: `source -> target [dep_type:names]`.
4. Within a line, names are sorted and capped at **5**, with `,...` when more were cut. `<anonymous>` is dropped from `imports` annotations; a pair with no names left is written without brackets.
5. When more than 500 pairs exist, a final line reads `... and N more edges`.

The sort is alphabetical, not by importance, so on a large repository the 500 edges are those whose source paths sort first. Since only `imports` edges exist, every annotation is `imports:...`. When an edge passes through a barrel, the target symbol is the barrel's import symbol, so the named symbol is whatever that import is called.

### `@@SYMBOLS`

The **200** files with the highest fan-in, in that order. For each file with any function, class or method symbol, one line: `path: fn:name cls:name meth:name`, sorted by kind then name, capped at **30** with ` ...` when cut. Files with no such symbols are skipped. Kind prefixes: `fn` for `function`, `cls` for `class`, `meth` for `method` (JavaScript-family methods; Python methods are stored as `function`).

### `@@HOTSPOTS`

Every file whose `criticality` is set and is not `safe` (case-insensitive), sorted by fan-in, capped at **50**. One line each: `path [label,fan_in=N,cc=M]`, where `cc` is the highest cyclomatic complexity of any symbol in the file and is omitted when none is recorded.

## Caps

| Cap                | Value | Where                    |
| ------------------ | ----- | ------------------------ |
| edges written      | 500   | `@@GRAPH`, first by path |
| names per edge     | 5     | `@@GRAPH`                |
| files with symbols | 200   | `@@SYMBOLS`, by fan-in   |
| symbols per file   | 30    | `@@SYMBOLS`              |
| hotspots           | 50    | `@@HOTSPOTS`, by fan-in  |

The caps are literals in `generate_illume_file`, not named constants. They bound the file to a few thousand lines regardless of repository size.

## Memory

The exporter projects only the columns it reads: `id`, `path`, `fan_in`, `fan_out` and `criticality` from `files`, and `file_id`, `kind`, `name` and `cyclomatic_complexity` from `ast_symbols`. An earlier version loaded whole `AstSymbol` rows, including `source_code` and `docstring`, and on a 10,000-file repository that single query was the largest object in the API process. The edge query still returns every symbol-level edge row; it is not capped before the 500-pair cut.

## Design trade-offs and limits

- **Text, not JSON.** The format is meant for a model or a person, so it has no schema and no version marker. Anything parsing it must rely on the `@@` headers and line shapes above.
- **Alphabetical edge cut.** Large repositories lose edges by path order, not by importance.
- **The default branch, not the snapshot.** `branch=` shows `default_branch`, which may differ from what was ingested, and there is no commit SHA in the file.
- **No ownership, glossary, reading order or history.** Those exist in the database but are not exported.
- **`edges=` counts the wrong thing.** It is the number of symbol-level rows, not the number of file pairs written under `@@GRAPH`.
- **A swallowed error.** The web client shows a generic failure for a repository that is not ready.

## Related documentation

- [The dependency graph](../graph/dependency-graph.md): the edges this file summarises.
- [Criticality](../pipeline/git-intelligence.md#criticality): where the hotspot labels come from.
- [API reference](../api.md): every route.
- [The MCP server](../mcp/server.md): the live alternative for giving a model this repository's context.
