# Supplementary provenance note -- research dataset v1

This note records a fact that `manifest.json` implies but does not itself establish. It
was written after the freeze and is **not** part of the integrity anchor. The manifest
was not modified, because editing it would destroy the property it exists to prove.

## The gap this note closes

`manifest.json` records `git_commit`. A commit SHA identifies what was *committed*; it
does not prove the working tree matched that commit when the freeze ran. If tracked
files had uncommitted modifications at freeze time, the manifest could name commit X
while the code actually in use differed from X.

## What was verified

Immediately after the freeze, on the same working tree:

```
manifest git_commit                          170902c04a40e5ecf9cd90cdca0619a29b35ac04
git rev-parse HEAD                           170902c04a40e5ecf9cd90cdca0619a29b35ac04
git rev-parse --abbrev-ref HEAD              fix/engine-wiring-and-timezone-expiry

git status --porcelain --untracked-files=no   (empty)
git diff HEAD --stat                         (empty)
git status --porcelain                       ?? research/archive/
                                             ?? scripts/
```

Both untracked entries were created by the freeze operation itself. No tracked file
differed from `HEAD`.

**Conclusion:** the available evidence establishes that the working tree was clean with
respect to tracked files at freeze time, so `git_commit` is a valid provenance claim for
this dataset version.

This is an inference from state observed immediately afterward on the same working tree,
not a timestamped record captured at the freeze instant -- git preserves no such record.
Future freezes capture `is_dirty` and `status_porcelain` in the manifest itself, making
this an anchored fact rather than a reconstruction.

## Why the recorded commit is not an ancestor of this branch

The freeze ran while `fix/engine-wiring-and-timezone-expiry` (170902c) was checked out,
so that is what the manifest records. The freeze artifacts were subsequently committed
on a separate branch based on `main` (9d7d59a) to keep the forensic freeze and the
engine runtime fixes as independent change sets.

The manifest was **not** amended to point at a tidier commit. It records the environment
that existed when the dataset was frozen, which is the fact it is supposed to preserve.

The recorded commit identifies the checked-out source state at freeze time independently
of how the engine branch is later integrated. It need not become an ancestor of the
branch containing these archive artifacts, and nothing about this provenance record
requires that. Historical evidence may legitimately reference a commit that is not
reachable from the default branch; the requirement is that the commit object exists, the
manifest names it, and the cleanliness of the tracked tree at that moment is established
above.

One operational consequence: because the manifest names 170902c, that object must remain
reachable for the provenance to be verifiable. Integrating the engine branch by merge or
fast-forward preserves it; squashing or cherry-picking would not, and would require
retaining a ref or tag that does.

## Manifest format

This manifest predates the `manifest_format_version` field and uses format 1: a bare
`git_commit` string and a `schema_sha256` computed over the normalised schema text
rather than the bytes of `schema.sql`. Verifying it requires stripping the trailing
newline from `schema.sql` before hashing.

The freeze tool has since been corrected to declare `manifest_format_version: 2`, record
full git provenance including worktree cleanliness, and hash the schema file as written.
That defines the format a future dataset-freeze implementation should carry forward. The
tool itself remains hardcoded to this dataset, and its success path is unreachable while
this manifest exists -- it is historical tooling, not a general dataset-lifecycle
framework.

## Carried forward

Future freeze tooling records this directly rather than relying on an external note:
`git_is_dirty` and `git_status_porcelain` are captured in the manifest at freeze time,
so cleanliness becomes part of the anchor instead of a reconstruction.
