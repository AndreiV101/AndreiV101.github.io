# Architecture (for Cursor planners)

Use this file when planning changes in repos created from this template.
Source of truth for data flow, spreadsheet schema, config, build output, and **where the live site is hosted**.

## Purpose

**This public template’s GitHub owner does not matter.** Anyone copies it into their own web host.

**Hard requirement for serving Pages:** the live site must run in a repo named **`owner.github.io`** (user or org). Project Pages (`owner/some-other-repo`) are not supported. CI fails if the name is wrong.

**Copy this template into the web hosting repo** (`owner.github.io`). That copy **is** the website host. There is no intermediate content repo and **no `DEPLOY_TOKEN`**.

Static website generated from:

1. **Google Spreadsheet** (public) — page copy / metadata + **Publish** button (Apps Script)
2. **Google Drive files** (public) — photos referenced by the sheet
3. **GitHub Action in the hosting repo** — fetch → resize → write `site/` → publish to **repo root on `main`**
4. **GitHub Pages** — Deploy from branch **`main`**, folder **`/` (root)**

**Primary publish path:** editor clicks **Publish website** → Apps Script `repository_dispatch` → Action builds and commits published files on `main`.

No runtime backend. No Google API keys for Sheet/Drive read. Public share links only.

**Minimal hosting repo (non-technical owners):** day-to-day work is Sheet + Drive only. No `config.json`, no Actions secrets for content. Brand / tagline / image resize live in the spreadsheet **Settings** tab. A technical contributor can own design/template edits in `owner.github.io`.

Human steps + Apps Script: [`GOOGLE_SHEETS_SETUP.md`](GOOGLE_SHEETS_SETUP.md) · script source: [`google-apps-script/Code.gs`](google-apps-script/Code.gs)

## One-repo model (template → hosting repo)

| Piece | Role |
|------|------|
| **`owner.github.io`** (template copied in) | Build scripts + published site root + Pages host |
| **Apps Script `GH_PAT`** | Fine-grained PAT from the **hosting repo owner**, scoped to that repo only (Actions R/W) |

```text
Editors / uploaders
  ├─ Google Drive  (images, Anyone-with-link)
  └─ Google Sheet  (rows + Apps Script button)
           │
           │  click "Publish website"
           ▼
  Apps Script  →  GitHub API repository_dispatch (event: rebuild-site)
           │         (GH_PAT — owner fine-grained, hosting repo only)
           ▼
  owner.github.io  GitHub Action (.github/workflows/build.yml)
           │
           ├─ scripts/check_host_repo.py
           │     require name owner.github.io
           │     require Pages: branch main, path /
           │
           ▼
  scripts/build.py → site/
           │
           ▼
  Copy site/ → repo root (index.html, assets/, images/, data.json)
           │
           ▼
  Commit + push on main  (GITHUB_TOKEN contents:write)
           │
           ▼
  GitHub Pages (main / root) → https://owner.github.io/
```

### One PAT only (`GH_PAT`)

| Token | Stored in | Targets | Fine-grained permission |
|-------|-----------|---------|-------------------------|
| **`GH_PAT`** | Apps Script Script properties | **Hosting** repo only (`owner/owner.github.io`) | **Actions: Read and write** (+ Metadata R) |

Created by the **owner** of the hosting repo. **No `DEPLOY_TOKEN`.** Never commit PATs. Never use Codespaces secrets for Actions.

### Hosting checks (enforced in CI)

`scripts/check_host_repo.py` **requires** (hard fail otherwise):

1. Repo name is exactly `{owner}.github.io` (required to serve user/org Pages at `https://owner.github.io/`)
2. Pages enabled with source branch **`main`** and folder **`/`**

The public template repo itself is not a Pages host; only copies named `owner.github.io` are.

## Rebuild triggers

| Trigger | When to use |
|---------|-------------|
| **Google Sheet button / Import/Export menu** (primary) | After editing Sheet or Drive content |
| `repository_dispatch` type `rebuild-site` | What Apps Script sends |
| Manual `workflow_dispatch` | Backup from GitHub Actions UI |
| Push to `main` touching build config/scripts | After template/code changes |

## Google Spreadsheet configuration

### Access

- Share: **Anyone with the link → Viewer** (required for public CSV export fallback)
- Publish-from-sheet sends `spreadsheet_id` / `sheet_gid` / Settings / optional inline CSV — **no `config.json`**
- Content tab name default: **`your website content`** (`CONTENT_SHEET_NAME`)
- Settings tab name default: **`settings`** (`SETTINGS_SHEET_NAME`) — `key` / `value` rows

### Header row (required shape)

| Column        | Required | Meaning |
|---------------|----------|---------|
| `title`       | yes*     | Item heading. Fallback aliases: `name` |
| `description` | no       | Caption / body. Aliases: `caption`, `body` |
| `image`       | yes**    | Drive file id **or** share/download URL. Aliases: `image_id`, `drive_id`, `photo` |
| `section`     | no       | `featured` (hero) or `gallery` (default) |
| `order`       | no       | Integer sort key (lower first). Default `9999` |
| `published`   | no       | `yes`/`y`/`true`/`1`/`published` or empty = show. `no` = skip |

\* If missing, builder uses `Item N`.  
\*\* Rows without a resolvable image still emit text-only items; gallery cards without `image_src` are omitted from the grid.

### Settings tab (`settings`)

| key | value (example) | Meaning |
|-----|-----------------|---------|
| `site_title` | Photo Journal | Brand / hero brand text |
| `site_tagline` | Stories from the field | Hero headline |
| `image_max_width` | 1400 | Resize max width px |
| `image_quality` | 82 | JPEG quality |

Header aliases: `key`/`setting`/`name` + `value`/`val`. Missing tab → builder defaults. Publish sends `settings_json` (+ `settings_gid` for CSV fallback).

### `section` rules

| Value       | Placement |
|-------------|-----------|
| `featured`  | First featured row → hero full-bleed image; its `description` → lede under hero |
| `gallery`   | Remaining published rows with images → gallery figures |
| (other/empty) | Treated as `gallery` |

### `image` cell formats accepted

Drive file id from raw id, `/file/d/{id}/...`, `open?id=`, `uc?id=`, `thumbnail?id=`, `lh3.googleusercontent.com/d/{id}`. Non-Drive `http(s)` URLs kept as remote `src`.

Each Drive file: **Anyone with the link → Viewer**.

## Repo configuration

**Keep the hosting repo minimal.** Site brand + image resize settings live in the spreadsheet **Settings** tab — not a repo file, not required Actions vars. Builder defaults apply when the tab is missing. Optional env overrides below are for contributors / edge cases only.

### Env / secrets (Actions) — optional

| Name | Kind | Maps to |
|------|------|---------|
| `SPREADSHEET_ID` | Var/secret optional | content fetch fallback (manual/push) |
| `SPREADSHEET_URL` | Var/secret optional | parses id + optional `gid` |
| `SHEET_GID` | Var optional | content tab gid fallback |
| `SETTINGS_GID` | Var optional | Settings tab gid fallback |
| `SITE_TITLE` / `SITE_TAGLINE` | Var optional | brand overrides (prefer Settings tab) |
| `IMAGE_MAX_WIDTH` / `IMAGE_QUALITY` | Var optional | image overrides (prefer Settings tab) |

**Do not** create `DEPLOY_TOKEN`, `DEPLOY_REPO`, or cross-repo deploy secrets.

### Pages hosting checklist

1. Copy this template into **`owner.github.io`** (or create that repo from the template)
2. **Settings → Pages → Deploy from a branch → `main` → `/` (root)**
3. Owner creates fine-grained PAT (Actions R/W on that repo only) → Apps Script `GH_PAT`
4. Apps Script `GH_REPO` = `https://github.com/owner/owner.github.io`

## Code map

| Path | Role |
|------|------|
| `scripts/build.py` | Builder: Sheet CSV / dispatch CSV, Drive download, resize, HTML emit → `site/` |
| `scripts/check_host_repo.py` | CI: enforce `owner.github.io` + Pages `main` `/` |
| `.github/workflows/build.yml` | Check → build → publish `site/` to root → commit on `main` |
| `google-apps-script/Code.gs` | Sheet button/menu (copy into Apps Script) |
| `index.html`, `assets/`, `images/`, `data.json` | **Published** Pages files at repo root (written by CI; not in the bare template) |
| `site/` | Local/CI build output (gitignored) |

## Invariants for planners

1. Reads stay public-link based — no Google service-account for Sheet/Drive reads unless asked.
2. Primary publish is Sheet Apps Script (`rebuild-site`), not cron.
3. Spreadsheet schema is the contract; aliases live in `scripts/build.py`.
4. Prefer editing templates inside `scripts/build.py` over hand-editing published root files long-term.
5. **Hosting repo = template copy** — never reintroduce an intermediate repo or `DEPLOY_TOKEN`.
6. **`GH_PAT` = hosting owner fine-grained, that repo only.**
7. CI must keep naming + Pages (`main` + `/`) checks.

## Local build

```bash
pip install -r requirements.txt
python scripts/build.py
USE_SAMPLE=1 python scripts/build.py
```

Open `site/index.html`. CI copies `site/` to repo root for Pages.
