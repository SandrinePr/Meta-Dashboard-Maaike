# HAMSTER seed

`hamster_redrock.json.gz` is the Free-tier bootstrap for Red Rock posts when the live SQLite file is empty (no Render disk).

- No Meta tokens or API keys
- Restored automatically on boot via `maaike.hamster_seed.restore_hamster_seed_if_empty`
- Separate from optional `MAAIKE_PERSIST_*` remote backup (GitHub Contents URL for private `hamster-persist`). Seed runs only when posts are still empty after remote restore.

