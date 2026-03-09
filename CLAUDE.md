# Audiobook Organizer - Development Guide

## Project Overview
Web-based audiobook organizer that scans directories, auto-identifies metadata (title, author, series, year, narrator), and organizes files into Chaptarr/Audiobookshelf-compatible folder structures using a copy+purge model.

## Tech Stack
- **Backend**: Python 3.12, FastAPI, SQLAlchemy (legacy Query API), SQLite, mutagen, httpx, audible
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
    lookup.py          # Audible, Google Books, OpenLibrary, iTunes APIs + caching + dedup
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
- **Output patterns**: Configurable tokens like `{Author}/{Series}/Book {SeriesPosition} - {Year} - {Title} {NarratorBraced} {EditionBracketed}`. Empty tokens collapse consecutive dashes and empty brackets/parens/braces.

## Matching Pipeline (how audiobooks are identified)
1. **Folder parsing** (`parser.py`): Multiple regex strategies extract title/author/series from folder names and parent directories
2. **Tag reading** (`metadata.py`): Reads mutagen tags from up to 10 audio files per folder, builds consensus
3. **Edition detection** (`parser.py:detect_edition`): Detects Graphic Audio editions from folder path, folder name markers `(GA)`, tag_author being "GraphicAudio", or `[Dramatized Adaptation]` in tags
4. **Merge** (`parser.py:merge_with_tags`): Tags win for author/title when non-generic; GraphicAudio rejected as author; boosts confidence on agreement
5. **Narrator cleanup** (`parser.py:clean_narrator`): Rejects publishers as narrator, strips role descriptions, normalizes GA casts
6. **Auto-lookup** (`scanner.py`): ALL books get online lookup via Audible + iTunes + Google Books + OpenLibrary (threshold = 1.0)
7. **Auto-apply** (`scanner.py`): Best lookup result applied if auto_match_score >= 0.85. Narrator applied from lookup results

## Current Status (Last Updated: 2026-03-09)

### What's Working
- Full scan pipeline: directory walk → folder parse → tag read → online lookup → DB records
- **Review page**: Confidence badges, source/output path preview, edit modal, **sort dropdown** (title, author, confidence)
- **Edition detection**: Graphic Audio auto-detected from folder path, folder name `(GA)`, tag_author "GraphicAudio", and `[Dramatized Adaptation]` tags
- **4 Lookup Providers**: Audible (0.92), iTunes (0.90), Google Books (0.85), OpenLibrary (0.80) — all with 30-day caching
- **Audible integration**: Uses `audible` Python package with external browser auth flow. Settings page has Connect/Disconnect UI with marketplace selector. Auth persisted to `/config/audible_auth.json`
- **Online lookup for ALL books**: Threshold raised to 1.0 — every book gets searched online during scan. 0.3s rate limiting between lookups. Narrator applied from online results
- **Narrator from Audible**: LookupResult now includes narrator field. Audible uniquely provides narrator in search results. Applied during auto-lookup when book has no narrator
- **GA author fix**: "GraphicAudio" rejected as author, falls back to folder path author
- **Narrator normalization**: `clean_narrator()` rejects publishers, strips role descriptions, normalizes GA casts
- **Series dedup**: Series matching author name auto-cleared; GA- prefix stripped
- **Author-in-title stripping**: Author name appended to title end auto-removed
- **Franchise author detection**: "Warhammer", "Horus Heresy", "Stormlight", etc. caught by suspect patterns
- Manual search modal (SearchModal) for custom metadata queries
- Toast notifications on actions
- Directory browser on Scan page
- Export diagnostics button with edition field
- Multi-file tag consensus (reads up to 10 files)
- Organize (copy) and Purge (delete source) workflows
- Browser HTTP cache fix: `cache: 'no-store'` on fetch + nginx

### Next Steps (Priority Order)
1. **Re-scan and verify all fixes**: Run a new scan to verify all parser fixes, online lookup, and Audible integration
2. **Test Audible auth flow**: Connect Audible in Settings page, verify search results during scan
3. **Handle multi-part audiobooks**: 34 GA entries split into Part 01, Part 02. Title falls back to parent but books still create separate entries. Need grouping logic
4. **UI polish**: Pagination for large book lists, filter by confidence/edition, bulk operations
5. **Scattered GA copies**: 9 GA copies of Mistborn/Stormlight outside `/Graphic Audio Collection/`

### Known Issues
- Multi-part folders (Part 01, Part 02) create separate book entries instead of being grouped (34 entries, all GA)
- First scan with online lookup will be slow (~5-10 min for 254 books × 4 providers). Subsequent scans use cache
- Audible API response structure is based on community docs — field names may differ, silently returns empty on error
- 9 "scattered" GA copies outside main collection creating duplicates
- Scan progress bar via polling (1.5s interval) doesn't show lookup phase progress

### Export Data Analysis (254 books, scan 1)
- **146 GA books** (57.5%) — detected by folder path containing "Graphic Audio" (100% coverage)
- **96 had "GraphicAudio" as author** — now rejected, will fall back to folder-path author on re-scan
- **12 had `(GA)`/`(GraphicAudio)` in title** — now cleaned by junk patterns
- **6 Mistborn titles** exist in both GA and standard versions — now distinguishable by `{EditionBracketed}` in output path
- **30+ had publisher as narrator** — now rejected by `clean_narrator()` (Black Library, Heavy Entertainment, etc.)
- **19 had series=author duplication** — now auto-cleared by fuzzy_match dedup
- **11 had empty () in titles** — now cleaned by `_clean_text` and post-merge cleanup
- **12+ had author name in title** — now stripped by word-matching in `merge_with_tags`

### Recent Changes (Session 2026-03-09)
- **Audible + Sort + Online Lookup** (commit `cd0301a`):
  - `search_audible()` in lookup.py: Uses `audible` Python package, confidence 0.92, extracts narrator/series/cover
  - Audible auth flow: `from_login_external()` with browser URL callback, persisted to /config/audible_auth.json
  - New endpoints: `GET /api/settings/audible/status`, `POST .../login-url`, `POST .../authorize`, `DELETE .../disconnect`
  - Settings page: Audible connection UI with marketplace selector, step-by-step auth instructions
  - Sort dropdown on ReviewPage: title, author, confidence (low/high)
  - `AUTO_LOOKUP_CONFIDENCE_THRESHOLD = 1.0` — all books searched online
  - Narrator field added to `LookupResult` schema (backend + frontend)
  - Narrator applied from lookup results in `_auto_lookup_books()`
  - Confidence now uses `max(local, online)` instead of `+0.20` bump
  - Rate limiting: 0.3s delay between book lookups
  - Progress logging: "Auto-lookup N/M: query" in Docker logs
  - `Book.source` type relaxed to `string` for `auto:audible` etc.

### Previous Changes (Session 2026-03-08)
- **Batch parser fixes** (commit `782db59`):
  - `clean_narrator()`: Rejects publishers (Black Library, Heavy Entertainment, etc.) as narrator, extracts real name from GA bracket patterns, strips "as Character" role descriptions, strips trailing `;` `.` punctuation, normalizes long GA cast lists to "Full Cast"
  - `GA_SERIES_PREFIX`: Strips "GA - " prefix from series names
  - Series=author dedup: Clears series when it fuzzy-matches author name
  - Author-in-title stripping: Removes author name from end of title ("Ashes of Man Christopher Ruocchio" → "Ashes of Man")
  - Part XX title fallback: When leaf folder is "Part 01" etc., uses parent folder as title
  - `PRIMARCH_PREFIX_PATTERN`: Strips "P01.", "P02." prefix from titles
  - Empty parens/brackets cleanup in `_clean_text` and post-merge
  - Added "audiobooks" and franchise names (Warhammer, Horus Heresy, Stormlight, Cosmere, Forgotten Realms, Dragonlance, Star Wars, Star Trek, Deathlands, Outlanders) to `SUSPECT_AUTHOR_PATTERNS`
  - Expanded `MULTI_PART_PATTERN` for "(Part 1 and 2)" and "(Parts 02)" variants
  - `PUBLISHER_NARRATOR_PATTERNS` constant for narrator validation
- **Earlier session fixes**:
  - Fixed "(Part X of Y)" title mangling, bracket position extraction `[04]`
  - GA narrator normalization (now superseded by `clean_narrator()`)
  - Fixed stale ReviewPage (browser HTTP cache) via `cache: 'no-store'`
  - GA bracket author extraction: "GraphicAudio [Author Name]" → real author
  - Range pattern skip: "Book 1-7" no longer parsed as position 1
  - Nested folder confidence lowered when author is suspect
  - Title-is-author detection using word subset check
  - "(N of M)" multi-part pattern (without "Part" keyword)
  - Tag author vs title rejection (mislabeled tags)
  - Added anthology/omnibus/boxset to suspect patterns
  - Added edition field, `detect_edition()`, `{EditionBracketed}` token

## How to Continue Development
When starting a new session, follow this process:
1. Read this CLAUDE.md to understand current state
2. Check `git log --oneline -10` for recent changes
3. Ask the user what they want to work on, or continue from "Next Steps" above
4. Always commit and push after changes
5. **Update this file** before ending the session with any new context, completed items, or new next steps
