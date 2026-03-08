# Audiobook Organizer - Development Guide

## Project Overview
Web-based audiobook organizer that scans directories, auto-identifies metadata (title, author, series, year, narrator), and organizes files into Chaptarr/Audiobookshelf-compatible folder structures using a copy+purge model.

## Tech Stack
- **Backend**: Python 3.12, FastAPI, SQLAlchemy (legacy Query API), SQLite, mutagen, httpx
- **Frontend**: React 19, TypeScript, Vite 7, TanStack Query v5, Tailwind CSS v4, Lucide React, React Router DOM v7
- **Container**: Multi-stage Dockerfile (Node 22 Alpine + Python 3.12 Alpine), LinuxServer.io PUID/PGID style, nginx reverse proxy
- **CI/CD**: GitHub Actions -> ghcr.io (`ghcr.io/cruv/audiobookorganizer:latest`)

## Key Directories
```
backend/app/
  main.py              # FastAPI app, logging config, static mount
  database.py          # SQLAlchemy engine + SessionLocal
  config.py            # Settings from env vars
  models/              # SQLAlchemy models (Book, BookFile, Scan, ScannedFolder, UserSetting, LookupCache)
  schemas/             # Pydantic schemas
  routers/
    scans.py           # POST /api/scans, browse endpoint, _run_scan_with_id background task
    books.py           # CRUD, lookup, search, apply-lookup, export, confirm
    organize.py        # Preview + execute organize, purge
    settings.py        # User settings CRUD
  services/
    scanner.py         # _find_audiobook_folders, _process_folder, auto-lookup
    parser.py          # Regex strategies, fuzzy_match, clean_query, auto_match_score
    metadata.py        # mutagen tag reading, read_folder_tags consensus
    lookup.py          # Google Books, OpenLibrary, iTunes APIs + caching + dedup
    organizer.py       # build_output_path, organize_book, token pattern system
frontend/src/
  pages/               # ScanPage, ReviewPage, OrganizePage, PurgePage, SettingsPage
  components/          # BookEditModal, SearchModal, DirectoryBrowser, Toast, etc.
  hooks/               # TanStack Query hooks
  api/client.ts        # API client functions
  types/index.ts       # TypeScript interfaces
```

## Development Rules
- **Docker-only**: NEVER run local dev servers. Always build and deploy as Docker container.
- **Always commit and push**: Every change should be committed and pushed to trigger CI/CD.
- **SQLAlchemy legacy API**: Uses `db.query(Model)` style, NOT `session.execute(select())`. Do NOT use `.unique()` on Query objects.
- **No `.get()` on queries**: Use `db.query(Model).filter(Model.id == id).first()` instead of deprecated `Query.get()`.
- **Background tasks**: The scan runs via FastAPI `BackgroundTasks`. All imports must be inside try/except with logging. DB session (`db = None`) must be declared before try block so error handler can access it.
- **Output patterns**: Configurable tokens like `{Author}/{Series}/Book {SeriesPosition} - {Year} - {Title} {NarratorBraced}`. Empty tokens collapse consecutive dashes.

## Matching Pipeline (how audiobooks are identified)
1. **Folder parsing** (`parser.py`): Multiple regex strategies extract title/author/series from folder names and parent directories
2. **Tag reading** (`metadata.py`): Reads mutagen tags from up to 10 audio files per folder, builds consensus
3. **Merge** (`parser.py:merge_with_tags`): Tags win for author/title when non-generic; boosts confidence on agreement
4. **Auto-lookup** (`scanner.py`): Books with confidence < 0.70 get automatic online lookup via iTunes + Google Books + OpenLibrary
5. **Auto-apply** (`scanner.py`): Best lookup result applied if auto_match_score >= 0.85

## Current Status (Last Updated: 2026-03-08)

### What's Working
- Full scan pipeline: directory walk -> folder parse -> tag read -> DB records
- Review page with confidence badges, source/output path preview, edit modal
- Manual search modal (SearchModal) for custom metadata queries
- Toast notifications on actions
- Directory browser on Scan page
- Export diagnostics button (GET /api/books/export) for matching analysis
- iTunes/Apple Books API + Google Books + OpenLibrary lookups with caching + dedup
- Multi-file tag consensus (reads up to 10 files, most common values)
- Scan logging visible in Docker logs
- Organize (copy) and Purge (delete source) workflows

### Next Steps (Priority Order)
1. **Analyze export data**: User needs to export scan results and share the JSON so matching quality can be evaluated across their 254-book library
2. **Tune parser for real-world patterns**: Based on export analysis, improve regex strategies for patterns seen in actual folder names (Graphic Audio tags, multi-part books like "Part 01", series with bracket notation like "[01]", Horus Heresy primarch novels with "P01." prefix)
3. **Handle multi-part audiobooks**: Many books are split into "Part 1 of 2", "(1 of 3)" etc. These should be grouped as a single book or at least recognized as parts
4. **Improve nested folder detection**: Some structures have franchise/series/subseries/book (e.g. Warhammer 40k -> Gaunt's Ghosts -> [01] First and Only). The parser takes parent[-3] as "author" which may be a franchise name
5. **Auto-lookup integration**: Verify auto-lookup triggers correctly during scan and test with real data
6. **UI polish**: Pagination for large book lists, sort controls, filter by confidence range, bulk operations

### Known Issues
- "Warhammer 40k" and similar franchise names parsed as authors (suspect author detection catches trailing numbers but franchise detection could be smarter)
- Multi-part folders (Part 01, Part 02) create separate book entries instead of being grouped
- Graphic Audio tags in folder names (`[GA]`, `[GraphicAudio]`, `[GraphicAudio-256]`) are cleaned but could be used as edition metadata
- Scan progress bar updates via polling (1.5s interval) - works but could use WebSocket for real-time updates

### Recent Bug Fixes
- Fixed scan background task silently crashing (imports outside try/except, db not available in error handler)
- Fixed `query.unique()` AttributeError (legacy Query API doesn't have `.unique()`)
- Fixed output path generating "Book - - Title" when tokens empty (consecutive dash collapse)
- Fixed tab title showing "frontend" instead of "Audiobook Organizer"
- Fixed Dockerfile build order (source copied before pip install)
- Fixed ghcr.io image name mismatch (no hyphen)

## How to Continue Development
When starting a new session, follow this process:
1. Read this CLAUDE.md to understand current state
2. Check `git log --oneline -10` for recent changes
3. Ask the user what they want to work on, or continue from "Next Steps" above
4. Always commit and push after changes
5. **Update this file** before ending the session with any new context, completed items, or new next steps
