# Branch Protection Checklist

Use this checklist when configuring branch protection for the default branch.

## Personal default branch rules

- Require a pull request before merging
- Require linear history
- Block force pushes
- Block deletions

## Personal default required status checks

- `PR shape`
- `Commit shape`
- `Repo quality`

## Optional required status checks

- `Diff coverage`

Only require `Diff coverage` after the repository starts producing LCOV files in CI.

## Optional team-style additions

Add these only if the repository stops being mostly solo development:

- Require approvals before merging
- Dismiss stale approvals when new commits are pushed
- Require conversation resolution before merging
- Require code owner review

## CODEOWNERS note

This repository includes `.github/CODEOWNERS` for future collaboration, but the
personal default ruleset does not require code owner review.
