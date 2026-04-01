# EAGLE

## Target

- App: Eagle for macOS
- Verified app bundle: `/Applications/Eagle.app`
- Verified local API base: `http://localhost:41595`

## Why this harness uses the older local API

Eagle's current public docs include a newer `/api/v2/...` Web API, but the
installed Eagle build on this machine responded successfully to the earlier
local endpoints:

- `GET /api/application/info`
- `GET /api/library/info`
- `GET /api/folder/list`
- `GET /api/item/list`

The same build returned `404 method not allowed` for `/api/v2/...` requests.
This harness therefore targets the verified local API first and keeps a `raw`
command for future expansion.

## Supported endpoint families

### Application

- `GET /api/application/info`

### Library

- `GET /api/library/info`
- `GET /api/library/history`
- `POST /api/library/switch`
- `GET /api/library/icon`

### Folder

- `GET /api/folder/list`
- `GET /api/folder/listRecent`
- `POST /api/folder/create`
- `POST /api/folder/rename`
- `POST /api/folder/update`

### Item

- `GET /api/item/list`
- `GET /api/item/info`
- `GET /api/item/thumbnail`
- `POST /api/item/update`
- `POST /api/item/addFromPath`
- `POST /api/item/addFromPaths`
- `POST /api/item/addFromURL`
- `POST /api/item/addFromURLs`
- `POST /api/item/addBookmark`
- `POST /api/item/moveToTrash`
- `POST /api/item/refreshPalette`
- `POST /api/item/refreshThumbnail`

## Design notes

- The CLI defaults to a REPL when launched without a subcommand.
- `--json` prints raw response objects for agent-friendly consumption.
- `raw request` provides escape hatches for endpoints not yet wrapped.
- Mutable commands are explicit and never run automatically during tests.
