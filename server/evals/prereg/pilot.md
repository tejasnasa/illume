# Design freeze

Status: DRAFT. Commit this file unchanged before the first paid run; the commit is the timestamp.

This file fixes the evaluation's design before any result exists, so the results cannot shape
the design. Claims are scoped to the repositories in `corpus.yaml` at the freezing commit and say
nothing about repositories in general.

## Corpus

Three repositories, one per era of AI-assisted coding:

- **before AI:** mostly built before late 2022;
- **early AI:** mostly built during 2023–2024;
- **latest AI:** created since May 2026.

All three share one language. Each is frozen at the base commit recorded in `corpus.yaml`.

## Questions

60 per repository, in two kinds. The mix per repository is recorded in `corpus.yaml`.

- **Change questions:** mined from pull requests merged after the base commit, blind variant
  only. The answer key is the PR's changed files that existed at the base commit, plus its title
  and description as the reference answer.
- **Explain questions:** written by a coding agent from the repository at the base commit, each
  with a reference answer and required files. A different model checks every one against the
  code; unsupported ones are dropped before any arm runs.

## Arms

`classic`, `hybrid`, `hybrid_rerank`, `hybrid_hyde`, `hybrid_multiquery`, `structural`,
`structural_-cochange`, `structural_rerank`, `agent`, and `auto` (composed from one route decision
per question). Every arm answers every question.

## Metrics

1. **File recall:** the share of required files in the `Files:` list the answer ends with.
   File precision and the format-failure rate are reported beside it.
2. **Correctness:** DeepEval G-Eval against the reference answer, with fixed steps and a 0–3
   rubric.
3. **Faithfulness:** DeepEval Faithfulness against the cited evidence, with ambiguous claims
   penalised.
4. **Answer relevancy:** DeepEval Answer Relevancy.
5. **Cost:** metered dollars per answer.
6. **Speed:** seconds per answer, and tool steps for the agent arms.

The judge model, its snapshot and the DeepEval version are recorded in the manifest. Scores from
any other judge or DeepEval version are never mixed with these.

## Reporting

- **Tables:** one arms × metrics table per repository, plus an overall one. Each cell is the mean
  with a 95% bootstrap interval, resampling questions within each repository.
- **Head-to-head comparisons:** each one is the mean per-question paired difference with a 95%
  bootstrap interval, for file recall, correctness and cost, overall and per repository. The
  comparisons are fixed here:
  - every arm against the arm it builds on (`hybrid` vs `classic`, `hybrid_rerank` vs `hybrid`,
    `hybrid_hyde` vs `hybrid`, `hybrid_multiquery` vs `hybrid`, `structural` vs `hybrid`,
    `structural_rerank` vs `structural`);
  - `structural` vs `structural_-cochange`;
  - `agent` vs `structural_rerank`;
  - `auto` vs `agent`.

  Any other comparison is labelled exploratory.
- **Wording:** a difference whose interval excludes zero is stated as "on these repositories, A
  scored higher than B". Any other difference is stated as "not resolved at this sample size".
- **Era comparison:** differences between the repositories, including the codebase-style
  measurements, are described as observations, not causes.
- **Judge check:** the judge is checked against 30 hand-scored answers. If agreement is poor, the
  judged columns are labelled exploratory.

## Exclusions

- **Errors:** a generation or judgment that ended in an error is excluded from that cell and
  listed in the report, with the error rate per arm.
- **Format failures:** an answer with no `Files:` list scores 0 file recall and is counted, not
  excluded.
- **Budget stop:** questions an arm did not reach before a budget stop are listed. Nothing is
  imputed.
- **No other exclusions:** no question is removed after seeing results.

## Amendments

Each amendment is dated and appended; the text above it is left as frozen. An amendment made
after any result exists says so.

### 2026-11-22: corpus languages and size

Made before any ingestion, generation or judgment has run, so no result informed it.

- **Languages.** The corpus is two Python repositories (before AI, early AI) and one TypeScript
  repository (latest AI), replacing "All three share one language". One TypeScript repository
  keeps the results from describing Python alone. Language and era coincide for that
  repository, so any difference involving it is reported as an observation about that
  repository, not as an effect of its language or its era.
- **Size.** The before-AI repository has 187 code files at its base commit, 129 of them outside
  tests, under the 200-file guide in `corpus.yaml`. It is kept because the files are large: about
  400k tokens of non-test code, more than the `agent` arm's 300k input cap, so every arm still
  has to search rather than read the whole repository. The report states both figures.
- **Training cutoff.** Every repository's change questions come from pull requests merged before
  the generator's training cutoff, apart from a handful in the before-AI repository. All arms
  share one answering model, so remembered changes would favour every arm alike; the
  post-cutoff questions are still reported apart, as the corpus file already provides.

### 2026-11-26: judge, faithfulness method, empty answers and the `Files:` parser

Made after the full run's 1,800 answers were generated and after the 30 pilot answers
(`pilot_v2`) were judged, but before any full-run answer was judged. The generated answers were
read while building these rules (the empty-answer count, the parser's stray entries); no judged
full-run score existed.

- **Judge.** `anthropic/claude-haiku-5.5` through OpenRouter's batch API
  (`anthropic/claude-haiku-5.5:batch`, the same model at half the price, answered within 24
  hours), with JSON-schema structured output and DeepEval 4.3.2. It replaces the default judge
  named in the plan because of cost. It is from a different family than the generator. Every
  full-run judgment comes from this judge; the live-API pilot judgments are kept apart and never
  mixed in. On the 30 pilot answers the batch and live judgments of the same model agreed closely
  on the means (correctness 0.644 against 0.622, faithfulness 0.786 against 0.795, relevancy
  0.885 against 0.876), with per-answer differences consistent with ordinary judge noise.
- **Faithfulness method.** "Against the cited evidence" is applied as follows. Each claim is
  checked against the evidence text itself, passed verbatim, rather than against the judge's
  restatement of it (DeepEval's stock metric restates the context first, which on code dropped
  the code and marked true claims unsupported). The evidence has a 24,000-character budget, shared
  so that a short piece hands its unused share to the others. An answer that cites nothing is held
  to the context it was shown, its final candidates in rank order, so an arm that never cites is
  not scored 0 by construction. All three were found and fixed on the pilot, before the full run
  was judged.
- **Empty answers.** An answer that came back empty because the generator spent its whole output
  limit on reasoning was retried once with unchanged settings: 11 answers, 10 recovered (per arm:
  `hybrid` 2, `hybrid_rerank` 2, `structural_rerank` 2, `auto` 2, `classic` 1,
  `hybrid_multiquery` 1, `structural_-cochange` 1). The one that stayed empty scores 0
  correctness and 0 file recall, and has no faithfulness or relevancy score: with no claims
  DeepEval would give it 1.0 on both, which says nothing about the answer. It is left out of
  those two cells and listed, as errors are.
- **The `Files:` parser.** A list item whose path candidate has no directory separator and no
  extension (a word of prose such as "the" or "not", or a symbol name) is no longer read as a
  path; a few well-known extensionless file names such as `Makefile` still are. On the full run
  this removes 1,551 such entries from 591 of the 1,800 answers and no entry naming a real file,
  so file recall is unchanged and only precision moves. The rule is applied to every arm alike,
  at report time.
- **Metric scope.** All three judged metrics on all 1,620 generated answers; `auto` copies the
  grade of the arm it routed to.
