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
