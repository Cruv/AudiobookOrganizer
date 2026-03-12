# Audiobook Organizer

A self-hosted web application that scans your audiobook directories, auto-identifies metadata (title, author, series, year, narrator), and organizes files into clean folder structures compatible with Audiobookshelf and Chaptarr. Built with a copy+purge model so your originals are never modified until you're ready.

## Supported Architectures

| Architecture | Available |
| :----------: | :-------: |
| x86-64       | &#10003;  |

## Application Setup

Access the web UI at `http://your-ip:80`.

On first launch, create your admin account &mdash; the first registered user automatically becomes the administrator. Additional users can register openly, or you can disable open registration and use invite links instead.

## Usage

### docker-compose (recommended)

```yaml
services:
  audiobook-organizer:
    image: ghcr.io/cruv/audiobookorganizer:latest
    container_name: audiobook-organizer
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Etc/UTC
      - GOOGLE_BOOKS_API_KEY=your_key_here  #optional
    volumes:
      - /path/to/config:/app/data
      - /path/to/audiobooks:/downloads
      - /path/to/organized:/audiobooks
    ports:
      - 8080:80
    restart: unless-stopped
```

### docker cli

```bash
docker run -d \
  --name=audiobook-organizer \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Etc/UTC \
  -e GOOGLE_BOOKS_API_KEY=your_key_here \
  -p 8080:80 \
  -v /path/to/config:/app/data \
  -v /path/to/audiobooks:/downloads \
  -v /path/to/organized:/audiobooks \
  --restart unless-stopped \
  ghcr.io/cruv/audiobookorganizer:latest
```

## Parameters

### Ports

| Parameter | Function |
| :-----: | --- |
| `80` | Web UI and API |

### Environment Variables

| Parameter | Function |
| :-----: | --- |
| `-e PUID=1000` | for UserID &mdash; see below for explanation |
| `-e PGID=1000` | for GroupID &mdash; see below for explanation |
| `-e TZ=Etc/UTC` | specify a timezone to use, see [list of TZ identifiers](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List) |
| `-e GOOGLE_BOOKS_API_KEY=` | Google Books API key for enhanced metadata lookup (optional) |
| `-e DATABASE_URL=` | SQLite database path override (default: `sqlite:////app/data/audiobook_organizer.db`) |

### Volume Mappings

| Volume | Function |
| :-----: | --- |
| `/app/data` | Application data &mdash; database, Audible auth credentials |
| `/downloads` | Source audiobook directory to scan |
| `/audiobooks` | Output directory for organized audiobooks |

## User / Group Identifiers

When using volumes, permissions issues can arise between the host OS and the container. We avoid this issue by allowing you to specify the user `PUID` and group `PGID`.

Ensure any volume directories on the host are owned by the same user you specify, and any permissions issues will vanish.

In this instance `PUID=1000` and `PGID=1000`. To find yours use `id your_user`:

```bash
id your_user
  uid=1000(your_user) gid=1000(your_user) groups=1000(your_user)
```

## Features

### Scanning & Identification

- **Directory scanning** &mdash; Recursively finds all folders containing audio files (mp3, m4a, m4b, flac, ogg, wma, aac, opus)
- **Multi-strategy folder parsing** &mdash; Multiple regex strategies extract title, author, series, and series position from folder names and parent directory structure
- **Audio tag reading** &mdash; Reads mutagen tags from up to 10 audio files per folder and builds consensus metadata
- **Tag + folder merge** &mdash; Intelligently merges parsed folder data with audio tags, with tags winning for author/title when non-generic
- **Confidence scoring** &mdash; Each book gets a confidence score based on how reliably metadata was identified

### Online Metadata Lookup

- **4 lookup providers** &mdash; Audible (0.92), iTunes (0.90), Google Books (0.85), OpenLibrary (0.80) confidence weights
- **Automatic lookup for all books** &mdash; Every scanned book is searched online across all providers
- **30-day result caching** &mdash; Lookup results cached in the database to speed up subsequent scans
- **Rate limiting** &mdash; 0.3s delay between lookups to respect provider APIs
- **Auto-apply best match** &mdash; Best lookup result applied automatically when match score is high enough
- **Narrator from Audible** &mdash; Audible uniquely provides narrator in search results, applied when book has no narrator

### Audible Integration

- **Audible account linking** &mdash; Connect your Audible account via external browser auth flow
- **Marketplace selector** &mdash; Supports multiple Audible marketplaces (US, UK, DE, FR, etc.)
- **Persistent auth** &mdash; Audible credentials persisted securely with restrictive file permissions
- **Enhanced metadata** &mdash; Audible provides narrator, series info, and cover art in search results

### Graphic Audio Detection

- **Edition detection** &mdash; Automatically identifies Graphic Audio editions from folder path, folder name `(GA)` markers, tag author being "GraphicAudio", and `[Dramatized Adaptation]` in tags
- **Author fix** &mdash; "GraphicAudio" rejected as author, falls back to real author from folder path
- **Series dedup** &mdash; Series matching author name auto-cleared; GA- prefix stripped from series names
- **Narrator normalization** &mdash; Rejects publishers as narrator, strips role descriptions, normalizes GA cast lists to "Full Cast"

### Review & Editing

- **Confidence badges** &mdash; Color-coded badges showing how reliably each book was identified
- **Source badges** &mdash; Shows where metadata came from (folder, tags, audible, itunes, google_books, openlibrary)
- **Edition badges** &mdash; Visual indicator for Graphic Audio and other editions
- **Inline path preview** &mdash; See source path and projected output path for each book
- **Edit modal** &mdash; Manually edit title, author, series, year, narrator, and other metadata
- **Search modal** &mdash; Search online providers manually for any book
- **Confirm individual books** &mdash; Mark books as reviewed and ready for organizing
- **Batch confirm** &mdash; Confirm all high-confidence books (80%+) in one click
- **Export diagnostics** &mdash; Download JSON export of all book data for analysis

### Search & Filtering

- **Text search** &mdash; Search by title or author with debounced input (300ms)
- **Confidence filter** &mdash; Filter by high (80%+), medium (50-80%), or low (<50%) confidence
- **Edition filter** &mdash; Filter by Graphic Audio or standard editions
- **Confirmed filter** &mdash; Filter by confirmed or unconfirmed status
- **Sort options** &mdash; Sort by confidence (low/high), title (A-Z), or author (A-Z)
- **Server-side pagination** &mdash; Handles large libraries efficiently with paginated results

### Organize & Purge

- **Configurable output patterns** &mdash; Tokens like `{Author}/{Series}/Book {SeriesPosition} - {Year} - {Title} {NarratorBraced} {EditionBracketed}` with smart collapse of empty tokens
- **Copy model** &mdash; Files are copied to the output directory, originals untouched
- **Verify before purge** &mdash; Verification step confirms all files were copied before allowing deletion
- **Selective purge** &mdash; Choose which books to purge, with confirmation dialog

### User Accounts & Security

- **Username/password authentication** &mdash; Session-based auth with HttpOnly cookies (7-day expiry)
- **First user is admin** &mdash; The first registered account automatically becomes the administrator
- **Open registration** &mdash; Enabled by default, allows anyone to create an account
- **Registration toggle** &mdash; Admin can disable open registration from Settings
- **Invite system** &mdash; When registration is closed, admin can generate invite links (7-day expiry) for new users
- **Invite management** &mdash; Admin can view, copy, and revoke invite links
- **Secure password storage** &mdash; PBKDF2-SHA256 with random salt
- **Path traversal protection** &mdash; Browse endpoint blocks sensitive directories, output path validated with `realpath`
- **API key masking** &mdash; Settings endpoint returns masked keys, never exposes raw values
- **Error sanitization** &mdash; Generic error messages to client, detailed logs server-side only
- **Content Security Policy** &mdash; Nginx headers restrict script and image sources

### General

- **Mobile responsive** &mdash; Hamburger menu sidebar on small screens
- **Error boundaries** &mdash; Each page wrapped to prevent full-app crashes
- **Confirmation dialogs** &mdash; Dangerous actions (delete scan, purge files) require confirmation
- **Toast notifications** &mdash; Success/error feedback on all actions
- **Escape key** &mdash; Closes all modals and dialogs
- **Directory browser** &mdash; Browse server directories when setting up a scan
- **Health check** &mdash; Built-in Docker health check with DB connectivity verification
- **Dark UI** &mdash; Dark theme with CSS custom properties

## Building from Source

```bash
git clone https://github.com/Cruv/AudiobookOrganizer.git
cd AudiobookOrganizer
docker build -t audiobook-organizer .
```

## Architecture

```
backend/app/
  main.py              # FastAPI app, auth middleware, static mount
  database.py          # SQLAlchemy engine + SessionLocal
  config.py            # Settings from environment variables
  models/              # SQLAlchemy models
  schemas/             # Pydantic request/response schemas
  routers/             # API endpoints (auth, scans, books, organize, settings)
  services/            # Business logic (scanner, parser, metadata, lookup, organizer)
frontend/src/
  pages/               # React page components
  components/          # Shared UI components
  hooks/               # TanStack Query hooks
  api/                 # API client functions
```

| Component | Technology |
| :-------: | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy, SQLite |
| Frontend | React 19, TypeScript, Vite 7, TanStack Query v5, Tailwind CSS v4 |
| Container | Multi-stage Dockerfile (Node 22 Alpine + Python 3.12 Alpine), nginx reverse proxy |
| CI/CD | GitHub Actions &rarr; ghcr.io |

## API Rate Limits

| Provider | Confidence | Rate Limit |
| :------: | :--------: | :--------: |
| Audible | 0.92 | 0.3s between requests |
| iTunes | 0.90 | 0.3s between requests |
| Google Books | 0.85 | 0.3s between requests |
| OpenLibrary | 0.80 | 0.3s between requests |

## License

MIT
