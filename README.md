# ai-resources

A curated, searchable collection of AI tools, agent skills, repos and reading, plus the small tool that maintains it.

**Just browsing?** Open [resources.md](resources.md). Everything is grouped by category, with a one-line description and tags for each link.

## How it works

- `imports/`: one JSON file per captured post or thread (source, links, categories, tags). These files are the source of truth.
- `categories.json`: the fixed list of top-level categories. Every item has exactly one.
- `kb.py`: a single-file CLI (Python 3, standard library only) that loads everything into a local SQLite database with full-text search.
- `resources.md`: generated from the database with `./kb.py export`.

## Run your own copy

```bash
git clone <this repo> && cd ai-resources
for f in imports/*.json; do ./kb.py import "$f"; done
./kb.py search "html video"
./kb.py list --category agent-skills
./kb.py categories
```

Search uses SQLite FTS5 syntax: `"exact phrase"`, `prefix*`, `OR`, `NOT`, `tags:remotion`, `title:gsap`.

## Adding resources

The intended workflow is to paste a post or list of links into [Claude Code](https://claude.com/claude-code) in this folder. `CLAUDE.md` tells it how to write the import file, pick a category and tags, and run the import. You can also write an import file by hand or use `./kb.py add URL --category <key>`.

Descriptions are short and factual. Claims made in the original posts aren't repeated unless they've been checked.
