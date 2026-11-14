# Issues

A to-do list in plain markdown, kept next to the code it's about. It's the same pattern in every repo:

```
issues/
  todo/<slug>.md    open
  done/<slug>.md    finished (moved here with `git mv`, in the same commit as the work)
```

- **One file per issue, named by a short slug** (`power-recovery.md`), not a number, so two agents writing issues at once can't collide.
- **The repo the issue lives in is the one whose code or docs change when it's done.** Chores about the machines it runs on live elsewhere.
- **Anyone can write one:** the owner, Claude Code, any agent. Noticing something isn't the same as being asked to fix it, so write it down and move on.

## Priority

Each issue has a `Priority:` line with one of three values:

| Priority | Means | Limit |
|---|---|---|
| `now` | Being worked on, or next up. If an agent asks "what should I do?", it's one of these. | **At most 3 per repo.** To add one, demote one. |
| `next` | Wanted soon; the pool `now` is refilled from. | none |
| `later` | Real but not soon. Also where new, untriaged issues land. | none |

- **Only the owner promotes to `now`.** Agents file new issues as `later` and may suggest a priority in the Notes.
- **Order inside a tier doesn't matter**, except for `Blocked by:`. If A needs B first, A says `Blocked by: [b](b.md)`. That's the only ordering kept.
- **No separate list files** (`nextup.md`, `backlog.md`). The priority lives in the issue, so closing, renaming or reprioritizing an issue can't leave a stale list behind.
- **Re-rank whenever the owner sits down to plan,** not on a schedule: `now` empty or stale → pull from `next`; `next` long → push some to `later`; `later` stale for months → delete it (git remembers).

### Seeing it

```sh
for p in now next later; do echo "== $p"; grep -l "^Priority: $p" issues/todo/*.md; done   # the board
grep -l '^Priority: now' issues/todo/*.md                # what's on
grep -l 'Needs: you' issues/todo/*.md                    # only a human can do these
grep -L '^Blocked by:' $(grep -l '^Priority: now' issues/todo/*.md)   # on and unblocked
```

## Template

```markdown
# <Title in plain words>

Opened 2026-11-13. Needs: you | agent | either
Priority: now | next | later
Blocked by: [other-issue](other-issue.md)        ← optional

## Why
What's wrong or missing, and what it costs if left alone.

## Done when
- A checkable outcome.
- Another.

## Notes
Steps, options, findings, links. Append as you go.

Resolved: <date, commit or one line on what was done>   ← only once it's in done/
```

`Needs: you` means it requires something an agent can't do (sudo, accounts and credentials, GitHub or AWS settings, a decision). Issues are public in this repo, so keep names, hosts and secrets out of them.
