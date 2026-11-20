# Writing the explain questions

Each repository gets about 25 explain questions (the `explain` count in its `corpus.yaml`
question mix), in `hand/<corpus entry name>.yaml` (see `example.yaml`). A coding agent writes
them from the repository at the pinned base commit, not from its README alone: it reads the code
that exists at that commit and writes only what that code supports.

## What to write

Each entry has `kind: explain`, a `question`, a `reference_answer` and `required_files`.

- **Question.** Phrase it the way a newcomer to the project would ask. Do not copy function,
  class, file or variable names from the code, so that keyword search gets no free ride. Ask about
  behaviour and structure: "how does X get from A to B", "where is Y decided", "what stops Z".
- **Reference answer.** A few sentences saying what a correct answer contains: the mechanism, the
  main steps and the part each plays. State only what the required files show. Do not pad, and do
  not guess about code you did not read.
- **Required files.** The files a correct answer must name. Keep them few and necessary.
- **Acceptable files.** Files that are also fine to cite but not required. They are not scored as
  misses and not counted as hits.
- **Notes.** Optional: one or two facts a judge can check the answer against.
- Paths are repo-relative with `/`, as at the base commit.

Spread the questions across the repository: different directories, a mix of single-file and
multi-file answers, and a mix of "how does it work" and "where does it live". The older
`architecture` and `flow` kinds still load, and `unanswerable` items (no files, tagged
`unanswerable`) are left out of a build unless asked for.

## After writing

1. **Independent check.** Run `python -m evals gold check --repo NAME`. A different model with no
   memory of how the questions were written reads each question, its reference answer and the
   text of its files at the base commit, and returns `supported`, `partly_supported` or
   `unsupported` with the claim at fault. `unsupported` items are dropped by the next
   `gold build`. `partly_supported` items are kept and listed: fix the reference answer or the
   files (an edited item is checked again), or delete the item.
2. **Optional human spot-check.** Read about 15 questions across the three repositories and
   confirm the reference answer is right and the question does not leak the code's names.

## Labelling change-set items

Verification applies this rule to every change-set item. "The files the PR changed" is not the
same as "the files that needed to change": incidental refactors and alternative valid
implementations both differ. The rule: an item is *correct* when every gold file is plausibly
required by the description as written; *ambiguous* when the description doesn't pin the change
down (a reasonable developer could change different files); *wrong* when the gold includes files
unrelated to the described change (drive-by refactors) or misses files the description clearly
needs. Ambiguous items are dropped, not scored.
