# Minecraft_plugin_autoupdate_checker - Design Overview

## Purpose
Small GUI tool to detect and manage server plugins per Minecraft server instance, with per-server plugin DBs and a master settings DB.

## High-level components
- `PluginDatabase` (app.py)
  - Master DB: settings, servers, legacy plugins
  - Per-server DB: plugins table (migrated from master when server is opened)
  - Responsibilities: schema init, migrations, CRUD for servers/plugins
- `PluginManagerApp` (Tk GUI in app.py)
  - Main UI: server selector, plugin list, actions
  - Server Manager dialog: create/update/delete servers
  - Synchronization: selected server id stored in settings; opening a server opens its DB

## Key behaviors / invariants
- `selected_server_id` persists in master settings and determines `server_connection`.
- Per-server DB files are stored under `APP_DIR/servers/server_<id>.sqlite` and must contain `plugins` table.
- UI must always reflect DB state: changes in server manager should update main UI even if user closes dialog without explicit Save.

## Problems addressed in recent changes
- Ensured per-server DB schema is initialized (`_init_plugins_schema`) when opening a server DB.
- Fixed selection restoration behavior to avoid overwriting when creating a new server.
- Ensured main UI server combobox is populated on startup and after dialog close.

## Next refactor steps
1. Split `app.py` into modules: `db.py` (PluginDatabase), `ui.py` (PluginManagerApp), `providers.py` (fetchers), `utils.py` (helpers). This will improve readability and testability.
2. Add unit tests for DB migrations (master->server) and basic CRUD for servers.
3. Centralize settings access and defaults into a single helper class.
4. Add logging to DB write operations (create_server/update_server/delete_server) to aid debugging.

## Manual test plan
- Start app with empty DB -> server manager auto-opens -> create server -> verify main UI combobox populated and server DB file created.
- Create several servers, restart app, ensure selected server persists and plugins table exists for opened server.
- Test new server creation while a server is selected: ensure '新規作成' clears selection and does not overwrite.

## Notes
- Keep UI responsiveness: avoid long DB/blocking ops on main thread; existing code uses threads for network tasks but not for DB migrations — consider moving migrations to background worker if migration may be large.
