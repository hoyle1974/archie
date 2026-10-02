# Archie

Archie (from *archive*) keeps a local copy of your work (Gmail, Calendar, Drive, GitHub
and Jira), remembers people and open items for you, and answers in plain English. Every
fact comes with a source, and nothing is made up: anything Archie can't verify against
your own data is dropped.

- **Design:** [docs/DESIGN.md](docs/DESIGN.md)
- **What it's for:** [docs/VIGNETTES.md](docs/VIGNETTES.md)
- **Map of the code:** [okf/](okf/index.md)

## Daily use

```
archie                     # open Archie; leave the window open, it syncs every 15 minutes
archie ask "…"             # ask anything from a shell
```

Things to ask (there's nothing else to memorize):

| You want | Ask |
|---|---|
| Prep for a meeting | "prep me for my 2pm" · "what's my next meeting about?" |
| Who someone is | "who is Priya?" · "what's my history with Alex?" |
| What you owe | "what do I owe people?" · "what am I waiting on?" |
| Update an item | "done with Sarah's question" · "snooze that till Monday" · "that's not a loop" |
| Focus | "what should I work on next?" |
| Your record | "what did I get done this week?" · "what did I ship this quarter?" |
| Meeting notes | "notes from the design review: …" |
| Time away | "catch me up since Monday" |
| Handover | "write a handover for the redis migration" |
| Fix Archie | "the Friday sync is a standup" · "Al R. is Alex Rivera" · "Priya is the PM for auth" |

Add `--sources` to see where each `[n]` came from (`--paths` also shows the file). In the app, sources are always shown.

## Setup

```
uv sync                                         # once, in this folder
uv run archie admin init                        # creates ~/.archie (never overwrites)
$EDITOR ~/.archie/me.yaml                       # your names, emails, GitHub/Jira ids
uv run archie admin connect google --client client.json   # Gmail, Calendar, Drive (read-only)
uv run archie admin connect jira --site https://you.atlassian.net --email you@work.com
```

Turn sources on in `~/.archie/config.yaml`:

```yaml
connectors:
  gmail: {enabled: true}
  calendar: {enabled: true}
  drive: {enabled: true}
  github: {enabled: true}     # uses your logged-in `gh` CLI
  jira: {enabled: true, site: https://you.atlassian.net, email: you@work.com}
```

**First launch:** macOS may ask whether `archie` can use a Keychain item ("archie",
"google-token"). Choose **Always Allow**. Until you answer, syncing waits silently,
because only the program that saved the token is trusted automatically.

Check your setup any time with `archie admin doctor`.

Maintenance (rarely needed): `archie admin sync | rederive | reindex | status`.

## Where things live

Everything is plain files in `~/.archie/` (safe to put in git, since the index is ignored):

| Folder | Contents |
|---|---|
| `sources/` | raw copies of each source (Archie writes these) |
| `people/` | a dossier per person |
| `meetings/` | a note per meeting |
| `loops/` | a file per open item |
| `briefings/` | saved meeting briefings |
| `journal/weekly/` | weekly accomplishments, written Fridays at 3 PM |
| `projects/` | handover documents |

Write anything you like in those notes. Archie only touches text between
`<!-- archie:auto -->` markers. Tokens live in the macOS Keychain, never in these files.
`archie.db` is only a search index: delete it any time and run `archie admin reindex`.

## Development

```
uv run pytest            # unit tests + one end-to-end test per vignette
```

Before every commit: update `okf/` for what changed (the pre-commit hook checks it) and
refresh graphify. See [CLAUDE.md](CLAUDE.md).
