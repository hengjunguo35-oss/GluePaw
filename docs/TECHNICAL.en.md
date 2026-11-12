# GluePaw Technical Documentation

> **AI translation notice**
> This English version was produced by **machine translation (AI)** and has not been
> proofread by a native speaker. Terminology and nuance may differ from the original.
> The Chinese document [TECHNICAL.md](TECHNICAL.md) is the authoritative source;
> if the two disagree, the Chinese version wins.

This document is for developers who want to read or modify the source code.
For user-facing instructions see [README](../README.md); for the privacy design see
[PRIVACY.md](PRIVACY.md).

## 1. Overview

GluePaw is a PySide6 desktop application made of three parts:

1. **Capture layer** — watches the system clipboard and classifies the risk level of
   each piece of content.
2. **Storage layer** — normal content is encrypted into SQLite; sensitive content only
   ever lives in memory.
3. **Presentation layer** — a portrait popup with search, favorites, multi-select,
   always-on-top mode, and light/dark themes.

The design deliberately stays "single process + single database": no background
service, no network, no inter-process communication.

## 2. Architecture

```
                    ┌─────────────────────────────┐
   system clipboard │  app.py  Vault              │
        ───────────▶│  · dataChanged → capture     │
                    │  · 1s tick → sweep           │
                    │  · hotkey queue polling      │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │  repository.py               │
                    │  · risk verdict → placement  │
                    │  · favorite / sensitive /    │
                    │    delete state machine      │
                    │  · merged memory + DB view   │
                    └───────┬───────────┬──────────┘
                            │           │
              ┌─────────────▼──┐   ┌────▼─────────────┐
              │ ephemeral.py   │   │ store.py          │
              │ memory + timer │   │ SQLite + ciphertext│
              └─────────────┬──┘   └────┬─────────────┘
                            │           │
                            └─────┬─────┘
                                  ▼
                         vaultcrypto.py
                 Fernet encryption / HMAC blind index / keys
```

## 3. Module responsibilities

| File | Responsibility | Key points |
| --- | --- | --- |
| `main.py` | Entry point | single-instance lock, logging, initial theme |
| `app.py` | Wiring and scheduling | clipboard listener, tray, hotkey polling, cleanup timers |
| `config.py` | Paths and defaults | `%LOCALAPPDATA%\GluePaw` |
| `vaultcrypto.py` | Cryptography | DPAPI-protected master key, Fernet, blind index |
| `store.py` | Persistence | schema, deduplicating upsert, retention purge |
| `ephemeral.py` | In-memory staging | session cipher, monotonic timers |
| `repository.py` | Business state machine | every privacy rule lives here |
| `sensitive.py` | Content classification | three-level verdict + Luhn / ID checksum |
| `hotkey_win.py` | Global hotkey | dedicated thread + message loop + queue |
| `theme.py` | Theming | two palettes + `@token` QSS template |
| `icons.py` | Icons | all drawn with QPainter, no emoji dependency |
| `ui_main.py` | Main window | cards, multi-select, pinning, search highlighting |
| `ui_settings.py` | Settings page | privacy, cleanup, appearance |

## 4. Data model

```sql
CREATE TABLE items (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  content              BLOB    NOT NULL,   -- Fernet ciphertext
  blind                TEXT    NOT NULL,   -- HMAC blind index, unique
  sensitive            INTEGER NOT NULL,   -- 0/1
  favorite_at          REAL,               -- NULL = not favorited
  sensitive_expires_at REAL,               -- wall-clock; NULL = no countdown
  ttl_snapshot         REAL,               -- retention at capture time
  auto_clear_months    INTEGER,            -- retention cycle at capture time; NULL = never
  source_app           TEXT,               -- reserved
  size                 INTEGER NOT NULL,
  created_at           REAL NOT NULL,
  last_used_at         REAL NOT NULL,
  use_count            INTEGER NOT NULL DEFAULT 1
);
```

### Why "snapshots" are stored

`ttl_snapshot` / `auto_clear_months` record the settings **at the moment the item was
captured**. If the user later changes the retention from 3 minutes to 10 minutes, items
already counting down are not extended — behavior stays predictable, matching the
product rule "the settings at capture time apply".

### Deduplication

`blind` is an HMAC-SHA256 blind index with a unique constraint. Copying the same content
again:

- existing row → update `last_used_at`, `use_count += 1`
- sensitive content → restart the countdown instead of creating a duplicate

## 5. Core state machine

A record has exactly two possible homes: `mem` (memory) and `db` (database).

| Current state | Event | Result |
| --- | --- | --- |
| sensitive · not favorited · counting down | timer expires | delete + clear the matching system clipboard |
| sensitive · not favorited | favorite | encrypt into DB, countdown keeps running |
| sensitive · favorited · counting down | unfavorite | back to memory, **inherit remaining time** |
| sensitive · favorited · expired | unfavorite | **delete immediately** (second confirmation) |
| sensitive · favorited | timer expires | not deleted, only marked expired |
| normal · not favorited | scheduled cleanup | purged according to the item's own snapshot |
| any · favorited | scheduled cleanup | exempt |
| privacy mode turned off | — | all memory items migrated to DB, countdowns cancelled |
| normal → sensitive (privacy on) | manual toggle | moved into memory, re-timed with current settings |
| normal → sensitive (privacy off) | manual toggle | flag only, no countdown |

Implemented in `repository.py`: `capture` / `favorite` / `unfavorite` /
`set_sensitive` / `set_privacy`.

## 6. Encryption and keys

```
user password (Windows logon)
        │ DPAPI
        ▼
   key.bin (32-byte master key; the file itself is DPAPI ciphertext)
        │
        ├── Fernet(AES-128-CBC + HMAC-SHA256)  →  content column
        └── HMAC-SHA256(derived index key)     →  blind column
```

- **Master key**: `os.urandom(32)`, generated on first run; wrapped with
  `CryptProtectData` on Windows.
- **Content encryption**: Fernet with a random IV and built-in integrity check.
- **Blind index**: `HMAC(key, content)`, irreversible and resistant to dictionary attacks.
- **Session cipher**: `SessionCipher` generates a random key per process start and is used
  only for the in-memory staging area.

## 7. Threading model

- **Main thread**: Qt event loop; handles UI, clipboard and SQLite.
- **Hotkey thread**: blocks in `RegisterHotKey` + `GetMessage`; on `WM_HOTKEY` it pushes
  an event into a `queue.Queue`, which the main thread polls with a 60 ms `QTimer`.

The database is only touched from the main thread, so no extra locking is needed; the
clipboard's `dataChanged` signal also fires on the main thread.

## 8. UI structure

```
MainWindow (QWidget, frameless, 9:16)
├── header_bar: search / gear / multi-select / pin / close
├── tab_bar: History | Favorites
├── QStackedWidget
│   ├── list page: QScrollArea → grouped by day → ClipCard × N
│   └── settings page: SettingsPage
└── footer_widget / selection_bar (mutually exclusive)
```

### ClipCard

- Layout: the preview text occupies its own row; the second row holds status and actions.
- Rich text: while searching, matched fragments are wrapped in `<span>` with a highlight
  background; masked items are never rendered as rich text.
- Shadow: `QGraphicsDropShadowEffect`, color follows the theme.
- Select mode: a checkbox appears on the left and clicking anywhere toggles selection.

### Always-on-top

Toggling `Qt.WindowStaysOnTopHint` requires recreating the native window, so
`set_pinned()` saves the position, changes the flags, then calls `show()` again. While
pinned, auto-hide-on-blur is disabled and confirmation dialogs are made topmost too, so
they never end up behind the main window.

## 9. Theme system

`theme.py` keeps two dictionaries, `LIGHT` and `DARK`. The QSS template uses `@token`
placeholders that are substituted at runtime:

```css
QFrame#Card { background: @surface; border: 1px solid @border; }
```

Switching the theme regenerates the whole QSS, calls `setStyleSheet`, and rebuilds the
cards (their shadow colors differ).

The theme source has three modes: follow system (`QStyleHints.colorScheme()`, with a
registry fallback), force light, force dark — persisted in `settings.theme_mode`.

## 10. Search and highlighting

The current implementation filters **in memory**: `store.list_items()` decrypts every
record, and `Repository.list_items()` merges memory items before doing a substring check.

That is fast enough for thousands to tens of thousands of rows. Beyond that, consider:

- lazy decryption / pagination
- SQLite FTS5 (note: Chinese word segmentation needs trigram or a custom tokenizer)
- a blind-index token table (exact word match only, no substring)

Highlighting: matches are wrapped in `<span style="background-color:...">`; the text is
HTML-escaped first and newlines become `<br>`.

## 11. Testing

- `selftest.py` — pure logic, no GUI. Covers sensitive classification, encryption,
  deduplication, the favorite state machine, privacy-mode migration, retention cleanup,
  and search.
- `smoketest.py` — assembles the whole app under `QT_QPA_PLATFORM=offscreen`, opens the
  settings page and refreshes the list, verifying the Qt layer raises no exceptions.

## 12. Extension points

### Platform support

`hotkey_win.py` is Windows-only. macOS can use `pynput` or a `Quartz` event tap; Linux
X11 can use `pynput`, while Wayland requires
`org.freedesktop.portal.GlobalShortcuts`. Clipboard watching already relies on Qt's
`dataChanged`, so that part is portable.

### Images / rich text

`items.kind` is currently fixed to text. When extending:

- store images as encrypted files or BLOBs, with only references in the database
- render previews per type
- enforce a separate size limit

### AI retrieval (not implemented)

The recommended route is "local retrieval + model answer" rather than sending the whole
history to an API:

1. run local keyword/vector retrieval to get candidate items
2. filter out sensitive items and everything still in memory
3. put only the few matched fragments into the prompt
4. require the model to cite item numbers that the user can click to copy

This preserves the privacy boundary and keeps token cost low.

## 13. Known technical debt

- The hotkey thread relies on `PostThreadMessage` to exit; in rare cases a thread may linger.
- `setWindowFlags` recreates the window and may cause a slight flicker.
- With very many cards (near 300), shadows and rich text slow rendering down.
- No crash-recovery test for `instance.lock`.
- Platform checks are scattered across modules; extracting a `platform/` package would help.
