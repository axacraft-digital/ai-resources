#!/usr/bin/env python3
"""kb — a personal, searchable resource database (SQLite + FTS5).

Usage:
  kb.py add URL --category C [--title T] [--desc D] [--tags a,b] [--note N] [--source ID]
  kb.py source --platform x --author @who [--url U] [--text "post text"]
  kb.py import FILE.json          # bulk import (see imports/*.json for the shape)
  kb.py search QUERY [--tag t] [--limit N]
  kb.py list [--category c] [--tag t] [--source ID] [--limit N]
  kb.py tags
  kb.py categories
  kb.py show ID
  kb.py export [--out resources.md]

Categories are fixed and live in categories.json; every item gets exactly one.
Search uses SQLite FTS5 syntax: words, "exact phrases", prefix*, OR, NOT,
and column filters like  tags:remotion  or  title:gsap.
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).with_name("resources.db")
CATEGORIES = json.loads(Path(__file__).with_name("categories.json").read_text())

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id         INTEGER PRIMARY KEY,
    platform   TEXT,            -- x, hn, reddit, newsletter, ...
    author     TEXT,
    url        TEXT,
    text       TEXT,            -- the original post, for context and search
    added_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY,
    url         TEXT NOT NULL UNIQUE,
    title       TEXT,
    description TEXT,
    category    TEXT,           -- a key from categories.json
    tags        TEXT,           -- space-separated, lowercase
    note        TEXT,           -- your own commentary
    source_id   INTEGER REFERENCES sources(id),
    added_at    TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, description, tags, note, url,
    content='items', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, title, description, tags, note, url)
    VALUES (new.id, new.title, new.description, new.tags, new.note, new.url);
END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, description, tags, note, url)
    VALUES ('delete', old.id, old.title, old.description, old.tags, old.note, old.url);
END;
CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, description, tags, note, url)
    VALUES ('delete', old.id, old.title, old.description, old.tags, old.note, old.url);
    INSERT INTO items_fts(rowid, title, description, tags, note, url)
    VALUES (new.id, new.title, new.description, new.tags, new.note, new.url);
END;
"""


def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    if "category" not in {r["name"] for r in db.execute("PRAGMA table_info(items)")}:
        db.execute("ALTER TABLE items ADD COLUMN category TEXT")
    return db


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm_tags(tags):
    if isinstance(tags, str):
        tags = tags.replace(",", " ").split()
    return " ".join(sorted({t.strip().lower() for t in tags or [] if t.strip()}))


def norm_url(url):
    url = url.strip().rstrip("/")
    if url.startswith("http://github.com"):
        url = "https://" + url[len("http://"):]
    return url


def add_source(db, platform=None, author=None, url=None, text=None):
    cur = db.execute(
        "INSERT INTO sources(platform, author, url, text, added_at) VALUES (?,?,?,?,?)",
        (platform, author, url, text, now()),
    )
    return cur.lastrowid


def check_category(category):
    if category is not None and category not in CATEGORIES:
        sys.exit(f"Unknown category {category!r}. Choose one of: {', '.join(CATEGORIES)}")


def add_item(db, url, title=None, description=None, tags=None, note=None, source_id=None, category=None):
    """Insert, or merge into the existing row if the URL is already saved."""
    check_category(category)
    url = norm_url(url)
    tags = norm_tags(tags)
    existing = db.execute("SELECT * FROM items WHERE url = ?", (url,)).fetchone()
    if existing:
        merged = norm_tags((existing["tags"] or "").split() + tags.split())
        db.execute(
            """UPDATE items SET title = COALESCE(title, ?), description = COALESCE(description, ?),
               tags = ?, note = COALESCE(note, ?), source_id = COALESCE(source_id, ?),
               category = COALESCE(?, category) WHERE id = ?""",
            (title, description, merged, note, source_id, category, existing["id"]),
        )
        return existing["id"], False
    cur = db.execute(
        "INSERT INTO items(url, title, description, category, tags, note, source_id, added_at) VALUES (?,?,?,?,?,?,?,?)",
        (url, title, description, category, tags, note, source_id, now()),
    )
    return cur.lastrowid, True


def print_rows(rows):
    if not rows:
        print("No results.")
        return
    for r in rows:
        print(f"[{r['id']}] {r['title'] or r['url']}")
        print(f"     {r['url']}")
        if r["description"]:
            print(f"     {r['description']}")
        meta = [CATEGORIES.get(r["category"], "Uncategorized")]
        if r["tags"]:
            meta.append(f"#{' #'.join(r['tags'].split())}")
        print(f"     {'  ·  '.join(meta)}")
        print()


def cmd_add(db, a):
    item_id, created = add_item(db, a.url, a.title, a.desc, a.tags, a.note, a.source, a.category)
    print(f"{'Added' if created else 'Updated'} item {item_id}")


def cmd_source(db, a):
    print(f"Source {add_source(db, a.platform, a.author, a.url, a.text)}")


def cmd_import(db, a):
    data = json.loads(Path(a.file).read_text())
    src = data.get("source")
    source_id = None
    if src:
        row = db.execute(
            "SELECT id FROM sources WHERE author IS ? AND text IS ?", (src.get("author"), src.get("text"))
        ).fetchone()
        source_id = row["id"] if row else add_source(db, **src)
    shared_tags = data.get("tags", [])
    added = updated = 0
    for it in data["items"]:
        _, created = add_item(
            db, it["url"], it.get("title"), it.get("description"),
            list(shared_tags) + list(it.get("tags", [])), it.get("note"), source_id,
            it.get("category", data.get("category")),
        )
        added += created
        updated += not created
    print(f"Imported {added} new, {updated} merged (source id {source_id}).")


def cmd_search(db, a):
    sql = """SELECT items.* FROM items_fts JOIN items ON items.id = items_fts.rowid
             WHERE items_fts MATCH ?"""
    params = [a.query]
    if a.tag:
        sql += " AND (' ' || items.tags || ' ') LIKE ?"
        params.append(f"% {a.tag.lower()} %")
    if a.category:
        sql += " AND items.category = ?"
        params.append(a.category)
    sql += " ORDER BY bm25(items_fts, 10.0, 3.0, 5.0, 2.0, 1.0) LIMIT ?"
    params.append(a.limit)
    try:
        print_rows(db.execute(sql, params).fetchall())
    except sqlite3.OperationalError as e:
        sys.exit(f"Bad search syntax: {e}. Wrap phrases with special characters in double quotes.")


def cmd_list(db, a):
    sql, params = "SELECT * FROM items WHERE 1=1", []
    if a.tag:
        sql += " AND (' ' || tags || ' ') LIKE ?"
        params.append(f"% {a.tag.lower()} %")
    if a.category:
        sql += " AND category = ?"
        params.append(a.category)
    if a.source:
        sql += " AND source_id = ?"
        params.append(a.source)
    sql += " ORDER BY added_at DESC, id DESC LIMIT ?"
    params.append(a.limit)
    print_rows(db.execute(sql, params).fetchall())


def cmd_tags(db, a):
    counts = {}
    for (tags,) in db.execute("SELECT tags FROM items"):
        for t in (tags or "").split():
            counts[t] = counts.get(t, 0) + 1
    for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{n:4}  {t}")


def cmd_categories(db, a):
    counts = dict(db.execute("SELECT COALESCE(category, ''), count(*) FROM items GROUP BY 1").fetchall())
    for key, label in CATEGORIES.items():
        print(f"{counts.get(key, 0):4}  {key:<18} {label}")
    if counts.get(""):
        print(f"{counts['']:4}  {'(uncategorized)':<18}")


def cmd_show(db, a):
    r = db.execute("SELECT * FROM items WHERE id = ?", (a.id,)).fetchone()
    if not r:
        sys.exit("Not found.")
    print_rows([r])
    if r["note"]:
        print(f"Note: {r['note']}\n")
    if r["source_id"]:
        s = db.execute("SELECT * FROM sources WHERE id = ?", (r["source_id"],)).fetchone()
        print(f"Source #{s['id']}: {s['platform']} {s['author'] or ''} {s['url'] or ''}".rstrip())


def cmd_export(db, a):
    lines = ["# Resources", ""]
    for key, label in list(CATEGORIES.items()) + [(None, "Uncategorized")]:
        rows = db.execute(
            "SELECT * FROM items WHERE category IS ? ORDER BY title COLLATE NOCASE", (key,)
        ).fetchall()
        if not rows:
            continue
        lines += [f"## {label}", ""]
        for r in rows:
            tags = f" — {' '.join('#' + t for t in r['tags'].split())}" if r["tags"] else ""
            desc = f": {r['description']}" if r["description"] else ""
            lines.append(f"- [{r['title'] or r['url']}]({r['url']}){desc}{tags}")
        lines.append("")
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"Wrote {a.out}")


def main():
    p = argparse.ArgumentParser(description="Personal resource database")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add"); s.add_argument("url"); s.add_argument("--category", required=True)
    s.add_argument("--title"); s.add_argument("--desc")
    s.add_argument("--tags"); s.add_argument("--note"); s.add_argument("--source", type=int)
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("source"); s.add_argument("--platform"); s.add_argument("--author")
    s.add_argument("--url"); s.add_argument("--text"); s.set_defaults(fn=cmd_source)

    s = sub.add_parser("import"); s.add_argument("file"); s.set_defaults(fn=cmd_import)

    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--tag"); s.add_argument("--category")
    s.add_argument("--limit", type=int, default=20); s.set_defaults(fn=cmd_search)

    s = sub.add_parser("list"); s.add_argument("--tag"); s.add_argument("--category")
    s.add_argument("--source", type=int)
    s.add_argument("--limit", type=int, default=50); s.set_defaults(fn=cmd_list)

    sub.add_parser("tags").set_defaults(fn=cmd_tags)
    sub.add_parser("categories").set_defaults(fn=cmd_categories)

    s = sub.add_parser("show"); s.add_argument("id", type=int); s.set_defaults(fn=cmd_show)

    s = sub.add_parser("export"); s.add_argument("--out", default="resources.md"); s.set_defaults(fn=cmd_export)

    a = p.parse_args()
    db = connect()
    with db:
        a.fn(db, a)


if __name__ == "__main__":
    main()
