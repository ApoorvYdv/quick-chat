# Run Migration Script

This script provides a **single entry point to manage Alembic migrations** across multiple migration environments.

Currently supported environments:

- `config`
- `agency`

The script ensures migrations run in the **correct dependency order** when running across all environments.

---

# Migration Order

When running migrations for all environments:

```
config → agency
```

When running **downgrades**, the order is automatically reversed:

```
agency → config
```

This ensures dependency safety between schemas.

---

# File Structure

Example expected structure:

```
migrations/
│
├── run_migrations.py
│
├── config/
│   ├── alembic.ini
│   └── versions/
│
└── agency/
    ├── alembic.ini
    └── versions/
```

Each migration environment has its **own Alembic configuration**.

---

# Usage Procedure

Install Python 3.12.4 using pyenv and instruct the project to use it:

```bash
pyenv install 3.12.4
pyenv local 3.12.4
```

Create a virtual environment and install dependencies using **uv**:

```bash
uv venv
source .venv/bin/activate
uv sync
```

Now in the virtual environment, run the following command:

```bash
migrate <command> [options]
```

or run

```bash
python src/court_cms_api/migrations/run_migrations.py <command> [options].
```

---

# Commands

### Create a Revision

Create a new migration revision.

```
migrate revision -t config -m "add users table"
```

With autogenerate:

```
migrate revision -t config -m "add users table" --autogenerate
```

---

### Upgrade

Upgrade database to latest migration.

```
migrate upgrade
```

Upgrade specific environment:

```
migrate upgrade -t agency
```

Upgrade to a specific revision:

```
migrate upgrade -r <revision_id>
```

---

### Downgrade

Downgrade one revision:

```
migrate downgrade -r -1
```

Downgrade specific environment:

```
migrate downgrade -t config -r -1
```

---

# Arguments

| Argument          | Description                                          |
| ----------------- | ---------------------------------------------------- |
| `command`         | Alembic command (`revision`, `upgrade`, `downgrade`) |
| `-t / --target`   | Migration environment (`config`, `agency`, `all`)    |
| `-m / --message`  | Migration message (for revision)                     |
| `--autogenerate`  | Enable Alembic autogeneration                        |
| `-r / --revision` | Target revision (`head`, `-1`, revision id)          |

Default target is **all environments**.

---

# Examples

### Create migration for config

```
migrate revision -t config -m "add config table" --autogenerate
```

---

### Upgrade all environments

```
migrate upgrade
```

---

### Upgrade only agency

```
migrate upgrade -t agency
```

---

### Downgrade one revision

```
migrate downgrade -r -1
```

---

# What the Script Does

The script internally runs commands like:

```
alembic -c config/alembic.ini upgrade head
```

or

```
alembic -c agency/alembic.ini revision --autogenerate -m "message"
```

This avoids manually switching between Alembic environments.

---