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
  main.py              # FastAPI app, logging config, static mount, auth middleware
  database.py          # SQLAlchemy engine + SessionLocal
  config.py            # Settings from env vars
  models/              # SQLAlchemy models (Book, BookFile, Scan, ScannedFolder, UserSetting, LookupCache, User, UserSession, Invite)
  schemas/             # Pydantic schemas
  routers/
    auth.py            # Register, login, logout, invites
    scans.py           # POST /api/scans, browse endpoint, _run_scan_with_id background task
    books.py           # CRUD, lookup, search, apply-lookup, export, confirm, paginated
    organize.py        # Preview + execute organize, purge
    settings.py        # User settings CRUD
  services/
    scanner.py         # _find_audiobook_folders, _process_folder, auto-lookup
    parser.py          # Regex strategies, fuzzy_match, clean_query, auto_match_score
    metadata.py        # mutagen tag reading, read_folder_tags consensus
    lookup.py          # Audible, Google Books, OpenLibrary, iTunes APIs + caching + dedup
    organizer.py       # build_output_path, organize_book, token pattern system
frontend/src/
  pages/               # ScanPage, ReviewPage, OrganizePage, PurgePage, SettingsPage, LoginPage, RegisterPage
  components/          # BookEditModal, SearchModal, DirectoryBrowser, Toast, ConfirmDialog, ErrorBoundary, etc.
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

## Current Status (Last Updated: 2026-03-10)

### What's Working
- Full scan pipeline: directory walk → folder parse → tag read → online lookup → DB records
- **Authentication**: Username/password with session cookies (HttpOnly), first user = admin, open registration with toggle, invite system for closed registration
- **Review page**: Confidence badges, source/output path preview, edit modal, sort dropdown, **search**, **filter by confidence/edition/confirmed**, **server-side pagination**
- **Server-side pagination**: Books endpoint returns `{items, total, page, page_size, total_pages}`
- **Edition detection**: Graphic Audio auto-detected from folder path, folder name `(GA)`, tag_author "GraphicAudio", and `[Dramatized Adaptation]` tags
- **4 Lookup Providers**: Audible (0.92), iTunes (0.90), Google Books (0.85), OpenLibrary (0.80) — all with 30-day caching
- **Audible integration**: Uses `audible` Python package with external browser auth flow. Settings page has Connect/Disconnect UI with marketplace selector. Auth persisted to `/app/data/audible_auth.json`
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
- **Error boundaries**: Each route wrapped in ErrorBoundary to prevent full-app crashes
- **ConfirmDialog**: Reusable modal with Escape key, used on ScanPage (delete) and PurgePage (purge)
- **Mobile responsive sidebar**: Hamburger menu on small screens with overlay
- **Escape key**: Closes all modals (BookEditModal, SearchModal, DirectoryBrowser, ConfirmDialog)
- **SourceBadge colors**: audible, itunes, auto:audible, auto:itunes, auto:google_books, auto:openlibrary
- **Improved empty states**: Icons and guidance text on ReviewPage, OrganizePage
- **Invite management**: Admin can generate/revoke invite links, copy to clipboard
- **.dockerignore**: Optimizes Docker build context
- **Enhanced health check**: DB connectivity verification, returns 503 if DB unavailable

### Next Steps (Priority Order)
1. **Re-scan and verify all fixes**: Run a new scan to verify multi-part grouping, dedup detection, and all parser fixes
2. **Test auth flow end-to-end**: First user registration, login/logout, invite generation, closed registration
3. **Test Audible auth flow**: Connect Audible in Settings page, verify search results during scan
4. **WebSocket scan progress**: Replace polling with SSE/WebSocket for real-time scan updates
5. **Bulk operations on ReviewPage**: Select multiple books, bulk confirm/edit/delete

### Known Issues
- First scan with online lookup will be slow (~5-10 min for 254 books × 4 providers). Subsequent scans use cache
- Audible API response structure is based on community docs — field names may differ (now logs warnings on error)
- Duplicate detection only logs warnings — no UI to view/resolve duplicates yet

### Export Data Analysis (254 books, scan 1)
- **146 GA books** (57.5%) — detected by folder path containing "Graphic Audio" (100% coverage)
- **96 had "GraphicAudio" as author** — now rejected, will fall back to folder-path author on re-scan
- **12 had `(GA)`/`(GraphicAudio)` in title** — now cleaned by junk patterns
- **6 Mistborn titles** exist in both GA and standard versions — now distinguishable by `{EditionBracketed}` in output path
- **30+ had publisher as narrator** — now rejected by `clean_narrator()` (Black Library, Heavy Entertainment, etc.)
- **19 had series=author duplication** — now auto-cleared by fuzzy_match dedup
- **11 had empty () in titles** — now cleaned by `_clean_text` and post-merge cleanup
- **12+ had author name in title** — now stripped by word-matching in `merge_with_tags`

### Recent Changes (Session 2026-03-18, v1.5.0)
- **UI/UX Redesign + Huntarr Security Hardening** (commit `aa4f3ee`, tag `v1.5.0`):
  - **Design system**: New `components/ui/` library — Button (5 variants, loading state), Input (labeled, error/hint), Select, Card, Modal (focus trap, escape, ARIA), Badge (unified Confidence/Source/Edition/Status), Toggle (accessible switch), Skeleton (loading placeholders), EmptyState
  - **Layout**: Numbered workflow steps (1-4) with checkmarks for completed steps, Settings separated below divider, Escape key closes mobile sidebar, admin badge on username, ARIA navigation labels
  - **Pages refactored**: All pages use design system primitives for visual consistency. Skeleton loaders, responsive grid filter bar on ReviewPage, icon+text verification status on PurgePage, workflow guidance hints, auto-copy Audible login URL
  - **Auth pages**: Real-time password validation (length + match indicators) on RegisterPage
  - **Component cleanup**: Deleted LookupResults.tsx, ConfidenceBadge.tsx, SourceBadge.tsx (replaced by unified Badge)
  - **Security (Huntarr lessons)**: Auth exempt list now `frozenset` (immutable, exact-match only). Global API rate limiter (120 req/min per IP). `_get_client_ip()` trusts X-Real-IP only from 127.0.0.1. Session cookies get `Secure` flag behind HTTPS. Max 10 sessions per user. Scan input validation: null byte rejection, absolute path required, 4096 char limit. CORS: explicit method/header allowlist in production. Nginx: X-Frame-Options DENY, `frame-ancestors 'none'` in CSP, Cross-Origin-Opener-Policy header

### Previous Changes (Session 2026-03-18)
- **App maturity pass** (v1.0.1 through v1.4.0, 18 changes):
  - **Bug fixes**: `datetime.utcnow()` → `datetime.now(timezone.utc)`, SettingsPage registration toggle type mismatch, metadata silent exceptions now logged, auth middleware caches `has_users` flag, Audible session memory leak (cap + cleanup), export endpoint streams instead of loading all into memory, organize/purge transaction safety with logging
  - **Security**: Login rate limiting (5 attempts/5min per IP, HTTP 429), min password length 8 chars, dependency version ranges pinned with upper bounds
  - **CI/CD**: GitHub Actions now runs ruff lint + pytest + TypeScript type-check before Docker build, Trivy container scan after push
  - **Tests**: 53 tests for parser (clean_query, fuzzy_match, clean_narrator, detect_edition, parse_folder_path, merge_with_tags, auto_match_score), organizer (sanitize_path_component, build_output_path), and auth (password hashing, session tokens)
  - **Multi-part book grouping**: Post-scan step detects sibling Part/Disc/CD folders under same parent, merges BookFiles into single Book record, deletes duplicates
  - **Duplicate detection**: Post-scan step groups by normalized title+author, logs warnings for same-edition duplicates, info for expected multi-edition books
  - **Scan progress**: New `status_detail` field on Scan model with phase-specific messages (discovering, processing, grouping, looking up N/M), displayed on ScanPage
  - **ReviewPage URL sync**: Page, sort, search, and filter state synced to URL search params — browser back/forward restores state
  - **Edition in API client**: `updateBook` type now includes `edition` field so BookEditModal saves correctly
  - **Accessibility**: ARIA roles on ConfirmDialog/BookEditModal, htmlFor/autocomplete on LoginPage, SettingsPage loading spinner
  - **Docker hardening**: Healthcheck (curl /api/health every 30s), memory limits (1G max, 256M reserved)

### Previous Changes (Session 2026-03-10)
- **Production polish** (commit `47176dd`):
  - **Authentication system**: User/UserSession/Invite models with PBKDF2 password hashing. Auth middleware on all `/api/*` routes (exempt: health, auth endpoints). Session cookies (HttpOnly, 7-day expiry). First registered user becomes admin. Open registration with admin toggle. Invite system (7-day expiry tokens) for closed registration
  - **Auth frontend**: LoginPage, RegisterPage, AuthGate in App.tsx. Sidebar shows username + logout. SettingsPage has invite management (generate, list, revoke) and registration toggle
  - **Server-side pagination**: `PaginatedBooksResponse` schema with `{items, total, page, page_size, total_pages}`. Books endpoint accepts `page`, `page_size`, `edition`, `min_confidence`, `max_confidence`, `search` params
  - **ReviewPage rewrite**: Search input (debounced 300ms), filter dropdowns (sort, confidence, edition, confirmed), pagination controls (Previous/Next)
  - **OrganizePage + PurgePage**: Adapted for paginated response (`booksData?.items`), `page_size: 200`
  - **ConfirmDialog component**: Reusable modal with Escape key, AlertTriangle icon
  - **ErrorBoundary component**: Wraps each route, shows error + "Try Again" button
  - **Mobile sidebar**: Hamburger menu on `md:` breakpoint, overlay with slide-in nav
  - **Escape key**: Added to BookEditModal, SearchModal, DirectoryBrowser
  - **SourceBadge**: Added audible/itunes/auto variant colors, strips `auto:` prefix for display
  - **ScanPage**: Confirm dialog before deleting scans with toast feedback
  - **PurgePage**: Replaced inline dialog with ConfirmDialog, added toasts on purge success/error
  - **Empty states**: Icons (FolderSearch, FolderCheck) + guidance text on ReviewPage, OrganizePage
  - **Health check**: DB connectivity check (`SELECT 1`), returns 503 on failure
  - **.dockerignore**: Excludes .git, node_modules, __pycache__, .env, IDE dirs
  - **Audible URL copy button**: Settings page has Copy button next to Open link

### Previous Changes (Session 2026-03-09)
- **Security hardening** (commit `7a27f6f`):
  - Audible auth file: `os.chmod(AUDIBLE_AUTH_FILE, 0o600)` after save — only process owner can read
  - CSRF protection: `session_token` (secrets.token_urlsafe) ties `login-url` → `authorize` requests
  - Response URL validation: whitelist of Amazon domains in `AUDIBLE_ALLOWED_REDIRECT_DOMAINS`
  - Browse endpoint: blocks `/proc`, `/sys`, `/dev`, `/root`, `/config` traversal; resolves symlinks
  - Output path traversal: `os.path.realpath()` check ensures path stays within `output_root`
  - API key masking: `GET /settings` returns `****last4` instead of raw key; `PUT` skips masked values
  - Error sanitization: endpoints return generic messages, log `type(e).__name__` only (no stack traces to client)
  - Nginx: `Content-Security-Policy` (whitelisted img-src for cover images), `Permissions-Policy` headers
  - Lookup providers: `logger.warning()` on failure instead of silent `except: pass`
  - Locale validation on Audible endpoints
  - Memory leak prevention: caps pending login sessions at 10
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
