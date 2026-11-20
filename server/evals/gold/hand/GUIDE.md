# Writing the hand set

About 15 questions per repository, in `hand/<corpus entry name>.yaml` (see `example.yaml`).
Write them from the repository at the pinned base commit, not from its README alone.

## What to write

- Roughly 6 architecture questions ("where does X live", "how is Y organised") and 6 flow
  questions ("what happens when Z"), each answerable from files that exist at the base commit.
- 2 to 3 questions the repository cannot answer (`kind: unanswerable`), plausible for the
  domain but about something the code does not do. A good answer abstains. These have no files.
- Do not copy phrasing from the code or from pull requests; ask the way a newcomer would.

## Files

- `required_files`: files a correct answer must name. Keep them few and necessary.
- `acceptable_files`: files that are also fine to cite but are not required. They are not
  scored as misses and not counted as hits.
- `notes`: one or two facts a judge can check the answer against.
- Paths are repo-relative with `/`, as at the base commit.

## Labelling change-set items

Verification applies this rule to every change-set item. "The files the PR changed" is not the
same as "the files that needed to change": incidental refactors and alternative valid
implementations both differ. The rule: an item is *correct* when every gold file is plausibly
required by the description as written; *ambiguous* when the description doesn't pin the change
down (a reasonable developer could change different files); *wrong* when the gold includes files
unrelated to the described change (drive-by refactors) or misses files the description clearly
needs. Ambiguous items are dropped, not scored.
