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

## Current Status (Last Updated: 2026-05-15)

### Recent Changes (Session 2026-05-15 part 5, v1.15.0 — PR 4 of multi-PR audit pass)
- **Cover art**:
  - **`cover.jpg` written during organize** (`services/organizer.py:_download_cover_art`): when a book has an applied (or top-ranked non-rejected) candidate with a `cover_url`, the organizer downloads it and writes `<output_dir>/cover.jpg` after the audio files commit. Audiobookshelf, Plex, and Jellyfin auto-detect this filename. Best-effort: failure is logged, not fatal. Capped at 10MB; only writes if no cover already exists.
  - **`BookResponse.cover_url`** (`schemas/book.py`, `routers/books.py`): the list/detail endpoints now include the chosen cover URL. Picks applied candidate first, then highest-ranking non-rejected. `selectinload(Book.candidates)` avoids N+1.
  - **`GET /api/books/{id}/cover`** (`routers/books.py:get_book_cover`): serves the locally-cached `cover.jpg` for organized books. Avoids loading remote CDN URLs in the browser (mixed-content + CSP friendly) and works offline.
  - **Thumbnails on ReviewPage**: each book row gets a 40×56 thumbnail. Tries the local cover first (organized books), falls back to remote URL on error, hides on broken remote.
- 13 new tests covering pick-cover-url priority, download with mocked httpx, no-op when no URL or file already exists, BookResponse.cover_url attachment, and the `/cover` endpoint.

### Recent Changes (Session 2026-05-15 part 4, v1.14.0 — PR 3 of multi-PR audit pass)
- **Frontend performance**:
  - **Code splitting** (`App.tsx`, `vite.config.ts`): post-auth pages (Scan/Review/Organize/Purge/Settings) now lazy-loaded via `React.lazy()` + `Suspense`. Vite `manualChunks` splits React, TanStack Query, and Lucide icons into separate vendor chunks for better long-term caching. Initial paint loads ~50 kB less JS.
  - **Optimistic mutations**: `useConfirmBook`, `useUnconfirmBook`, `useLockBook`, `useUnlockBook` now patch the cached `PaginatedBooks` directly via `queryClient.setQueriesData` instead of invalidating `['books']` and refetching every variant. Every click is instant.
  - **Debounced `usePreviewPattern`**: was firing `/api/settings/preview-pattern` on every keystroke. Now waits 300ms after the user stops typing.
- **UX polish**:
  - **Modal focus trap** (`components/ui/Modal.tsx`): proper Tab/Shift+Tab wraparound inside the dialog, plus restores focus to the opener element on close.
  - **`window.confirm` → `ConfirmDialog`** (`pages/ReviewPage.tsx`): "Reset All Confirmations" now uses the design-system dialog with Escape support, focus trap, and consistent styling.
  - **Nested onClick fix** on Organize/Purge cards: checkbox `onClick={(e) => e.stopPropagation()}` so the outer card click doesn't fire a second toggle and cancel the first.
  - **`exportBooks` checks `resp.ok`**: HTTP errors now throw instead of silently embedding `{"detail":"..."}` in the downloaded export.
  - **Toast a11y + HMR-safe IDs** (`components/Toast.tsx`): wrapper has `aria-live="polite"`, errors have `role="alert"`. ID counter moved to a per-provider `useRef` so HMR no longer produces duplicate React keys.
  - **`useScan` invalidates the scans list + books on completion**: parent list and ReviewPage now refresh automatically when a scan transitions out of `running`.
  - **SearchModal**: result cards disabled (`opacity-50 pointer-events-none`) while a previous apply is in flight, preventing race where two clicks apply two different metadata sets on top.
  - **CandidatesModal per-row busy**: only the row whose mutation is in flight shows the loading state; other rows stay interactive.
  - **`cover_url` onError fallback** (SearchModal, CandidatesModal): broken cover images hide themselves instead of showing the browser's broken-image icon.
- No new tests in this PR (most changes are UI behavior). Existing 158 tests still pass; TS type-check clean; Vite build now produces split chunks (largest non-vendor: ReviewPage at 23.66 kB / 7.03 kB gzipped).

### Recent Changes (Session 2026-05-15 part 3, v1.13.0 — PR 2 of multi-PR audit pass)
- **Backend performance**:
  - **Parallel lookup providers** (`services/lookup.py`): `lookup_book` now runs Audible/Google/OpenLibrary/iTunes via `asyncio.gather`. Total wall-clock is `max(provider_time)` instead of sum — ~2.5x faster lookup phase.
  - **Bounded-concurrency auto-lookup** (`services/scanner.py`): `_auto_lookup_books` now processes up to `AUTO_LOOKUP_CONCURRENCY=5` books in parallel, each with its own `SessionLocal()`. ~5x throughput on the lookup phase.
  - **Shared `httpx.AsyncClient`** (`services/lookup.py`): module-level pool created lazily via `get_http_client()`, closed at FastAPI lifespan shutdown. Connection keepalive amortizes TCP+TLS handshake cost across the whole scan. ~30-50% latency reduction per HTTP call.
  - **DB indexes** (`main.py:_run_migrations`): added `ix_books_is_confirmed`, `ix_books_organize_status`, `ix_books_purge_status`, `ix_books_edition`, `ix_books_title`, `ix_books_author`, `ix_books_created_at`, `ix_lookup_candidates_book_id`, `ix_user_sessions_token`. ReviewPage filter+sort goes from O(N log N) to O(log N + page).
  - **`list_books` separate count query** (`routers/books.py`): count now runs against a lean `Book.id` query with no joinedload + no order_by; the fetch query is built separately with full eager load and sort. ~2x faster pagination on large libraries.
  - **`read_tags` once per file** (`services/metadata.py`, `services/scanner.py`): `read_folder_tags` now accepts an optional `per_file_tags` dict that callers can populate and reuse. `_process_folder` threads it through so each BookFile reuses the same tag dict instead of opening mutagen a second time. ~3-5x faster folder processing on multi-chapter MP3 books.
  - **Docker layer cache** (`Dockerfile`): pip-install layer no longer invalidates on backend code edits. Stub `app/__init__.py` lets pip install dependencies before the real source is copied. Saves 60-90s per backend-only commit in CI.
- **Bug**:
  - **`apply_lookup` now keyed by book identity** (`routers/books.py`): previously it took the most recent 10 cache rows for the provider and applied `results[result_index]`, which could apply one book's lookup result to a different book. Now reconstructs the per-provider query key from THIS book's title+author and finds the exact matching cache row.
- 10 new tests covering shared httpx singleton + idempotent close, parallel-provider timing under mocks, paginated count correctness, and apply_lookup book-identity behavior.

### Recent Changes (Session 2026-05-15 part 2, v1.12.0 — PR 1 of multi-PR audit pass)
- **Critical bug fixes + purge bug + delete-book endpoint** (branch `claude/naughty-driscoll-a6ebe8`):
  - **Lookup cache silent defeat** (`services/lookup.py`): `LookupCache.expires_at` is a naive `DateTime`; comparing to `datetime.now(timezone.utc)` raised `TypeError`, swallowed by `_safe_provider`, so every cache hit became a fresh API call. Normalize naive → aware on read. Re-scans are now ~4x faster.
  - **Purge bug** when files deleted externally (`services/purger.py`, `routers/books.py`, frontend): missing originals no longer block verification or purge — purge gracefully skips deleted files and still marks the book purged. New `purge_book(force=True)` bypasses verification for advanced flows. New `DELETE /api/books/{id}` endpoint removes a book + its `ScannedFolder` (so future scans don't re-import the orphan). Files on disk are NOT touched.
  - **Remove buttons**: `Trash2` icon on every ReviewPage row + small `X` on every PurgePage row. Confirmation dialog explains "files on disk are NOT touched."
  - **OrganizePage stale closure**: poll used `setInterval` with a stale `books` closure; the `pending` filter dropped in-flight books, so the first tick saw an empty `remaining` and falsely declared completion. Rewritten as `useEffect` polling per-book `/api/organize/status/{id}` — closure refreshes every render.
  - **AuthGate fallback**: `/api/auth/status` fetch failures used to fall through to `has_users: false`, showing logged-in users the first-run registration screen. Now shows a "Couldn't reach the server" retry UI.
  - **`_organize_books` per-book error handling** (`routers/organize.py`): each book wrapped in try/except so one failure (permission denied, disk full) doesn't strand the rest in `organize_status="copying"` forever. Failed books transition to `organize_status="failed"`.
  - **Reimport rollback** (`services/reimport.py`): per-folder error path now calls `db.rollback()` before adding the skip-marker `ScannedFolder` — previously the half-written state tripped the `uq_scanned_folder_scan_path` unique constraint, blowing the entire reimport.
  - **`audible_status` validation** (`routers/settings.py`): file existence alone was misleading; now attempts `Authenticator.from_file()` (no network) so a corrupt/truncated auth file reports `connected=False` immediately instead of failing every lookup minutes later.
  - **Rate-limit dict pruning** (`main.py`, `routers/auth.py`): `_api_requests` and `_login_attempts` now prune empty entries — was unbounded growth in memory per unique source IP.
  - **Admin gates** (`routers/auth.py`, `settings.py`, `scans.py`): new `require_admin` FastAPI dependency. Applied to `PUT /api/settings`, all Audible mutations (`/login-url`, `/authorize`, `/disconnect`), and `DELETE /api/scans/{id}`. Settings read endpoints and book-level mutations stay open to all logged-in users (shared-library model).
  - 13 new tests: 4 for `_get_cached` (naive datetime handling, expired cleanup, round-trip), 9 for purge/delete (missing originals, missing destinations, force-purge, DELETE cascade behavior, files-on-disk untouched).

### Recent Changes (Session 2026-05-15)
- **Loose audiobook file detection** (branch `claude/detect-books-outside-folders-KIXwl`):
  - Scanner now treats every `.m4b` file as its own book regardless of how many sit in the same directory (the format is almost always one-file-per-book). Other audio formats (mp3, flac, ...) keep the existing 'folder = book' grouping for multi-file chapter sets — `.mp3` chapter sets are unaffected.
  - **Main use case**: downloads dir full of unrelated single-file `.m4b` books — each now scans as its own book instead of getting lumped together or missed entirely.
  - `parser.py`: added `parse_file_path(file_path)` — strips extension, parses just the filename via the leaf strategies. Intentionally ignores parent directory (loose files commonly sit in generic 'downloads'/'audiobooks' parents that would mislead nested-folder parsing).
  - `scanner.py`: `_find_audiobook_folders` now returns mixed paths (folders + loose file paths). Loose files bypass the "deepest folder wins" filter. `_process_folder` dispatches to new `_process_loose_file` when handed a file path. Folder processor skips `.m4b` files so they aren't double-counted as chapters. `_group_multipart_books` skips loose files so `Part01.m4b` isn't mistaken for a multi-disc set.
  - `ScannedFolder.folder_path` holds the file path itself for loose files; `folder_name` holds the filename. No schema changes — carry-forward, duplicate detection, and UI work unchanged.
  - `LOOSE_FILE_EXTENSIONS = {".m4b"}` — easy to extend if needed.
  - 13 new tests: 5 for `parse_file_path`, 8 for scanner detection (root loose files, multiple unrelated m4bs in downloads dir, mp3 chapter sets, mixed m4b+mp3, nested m4bs, loose-file processing).



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
