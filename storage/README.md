# storage/

Local scratch space for the ClipForge containers.

- `storage/temp/` — temporary processing area (mounted at `/data/temp` inside
  the API and worker containers). Files here are deleted after successful
  upload to Google Drive; never treat this as persistent storage.
- The **persistent** storage for the product is Google Drive (folders
  `01_Inbox` … `09_Metadata`), configured in Phase 2.

Named Docker volumes (`mysql_data`, `redis_data`, `temp_data`) hold the actual
runtime data; this directory is reserved for anything you want to bind-mount
from the host (for example a local storage backend during development).
