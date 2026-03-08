export interface Scan {
  id: number;
  source_dir: string;
  status: 'running' | 'completed' | 'failed';
  total_folders: number;
  processed_folders: number;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ScannedFolder {
  id: number;
  scan_id: number;
  folder_path: string;
  folder_name: string;
  status: string;
  error_message: string | null;
  created_at: string;
}

export interface ScanDetail extends Scan {
  folders: ScannedFolder[];
}

export interface Book {
  id: number;
  scanned_folder_id: number | null;
  title: string | null;
  author: string | null;
  series: string | null;
  series_position: string | null;
  year: string | null;
  narrator: string | null;
  source: 'parsed' | 'tag' | 'google_books' | 'openlibrary' | 'manual';
  confidence: number;
  is_confirmed: boolean;
  output_path: string | null;
  organize_status: 'pending' | 'copying' | 'copied' | 'failed';
  purge_status: 'not_purged' | 'purged';
  folder_path: string | null;
  folder_name: string | null;
  projected_path: string | null;
  created_at: string;
  updated_at: string;
}

export interface BookFile {
  id: number;
  book_id: number;
  original_path: string;
  filename: string;
  file_size: number;
  file_format: string | null;
  destination_path: string | null;
  copy_status: string;
  tag_title: string | null;
  tag_author: string | null;
  tag_album: string | null;
  tag_year: string | null;
  tag_track: string | null;
  tag_narrator: string | null;
}

export interface BookDetail extends Book {
  files: BookFile[];
}

export interface LookupResult {
  provider: string;
  title: string | null;
  author: string | null;
  series: string | null;
  series_position: string | null;
  year: string | null;
  description: string | null;
  cover_url: string | null;
  confidence: number;
}

export interface OrganizePreviewItem {
  book_id: number;
  title: string | null;
  author: string | null;
  source_path: string;
  destination_path: string;
}

export interface PurgeVerifyItem {
  book_id: number;
  title: string | null;
  author: string | null;
  verified: boolean;
  missing_files: string[];
  total_size: number;
}

export interface PurgeResultItem {
  book_id: number;
  success: boolean;
  files_deleted: number;
  error: string | null;
}

export interface Settings {
  output_pattern: string;
  output_root: string;
  google_books_api_key: string | null;
}

export interface PatternPreview {
  pattern: string;
  preview: string;
}

export interface DirectoryEntry {
  name: string;
  path: string;
  has_children: boolean;
}

export interface BrowseResult {
  current_path: string;
  parent_path: string | null;
  directories: DirectoryEntry[];
}
