# Drive + Sheets → static website

**Public template** — who owns this GitHub repo does not matter. Copy it into **your** Pages host.

**Pages requirement:** the host repo **must** be named **`owner.github.io`**. That is how GitHub serves `https://owner.github.io/`. Other repo names (project Pages) are not supported; CI rejects them.

That `owner.github.io` copy builds and hosts the site. No second “content” repo. **No `DEPLOY_TOKEN`.**

Sheet/Drive → Publish button → Action on `owner.github.io` → files on **`main` root** → GitHub Pages.

**Owners stay out of GitHub day-to-day:** edit the Sheet + Drive folder, click Publish. No repo config file. A contributor can handle design changes in the hosting repo.

**Setup:** [`GOOGLE_SHEETS_SETUP.md`](GOOGLE_SHEETS_SETUP.md) · **Planners:** [`ARCHITECTURE.md`](ARCHITECTURE.md)

## Setup

### 1. Hosting repo (`owner.github.io` required)

1. Create **`owner.github.io`** (or rename a template-generated repo to that exact name)
2. Copy this public template into it
3. **Settings → Pages → Deploy from a branch → Branch: `main` → Folder: `/` (root)**
4. CI checks the name + Pages settings and **fails** if either is wrong

### 2. Google Spreadsheet + Publish button

Follow [`GOOGLE_SHEETS_SETUP.md`](GOOGLE_SHEETS_SETUP.md).

- Tab name: **`your website content`**
- Headers: `title`, `description`, `image`, `section`, `order`, `published`
- Settings tab **`settings`**: `key` / `value` for `site_title`, `site_tagline`, `image_max_width`, `image_quality`
- Share sheet + Drive files: **Anyone with the link → Viewer**

### 3. Owner fine-grained PAT (`GH_PAT`)

Created by the **owner** of `owner.github.io`:

1. Fine-grained PAT → **only** that hosting repo
2. Permission: **Actions: Read and write** (+ Metadata)
3. Store in Apps Script Script properties as `GH_PAT`
4. `GH_REPO` = `https://github.com/owner/owner.github.io`

Never commit the PAT. There is no deploy PAT / `DEPLOY_TOKEN`.

### 4. Publish

**Import/Export → Publish website** (or the sheet button) → Actions tab on the hosting repo → when green, open `https://owner.github.io/`.

## Local build

```bash
pip install -r requirements.txt
python scripts/build.py
```

Open `site/index.html`. `site/` is gitignored; CI publishes to repo root.

## Flow

```text
Google Drive + Sheet (Publish)
        → repository_dispatch (rebuild-site)
        → Action on owner.github.io
        → check name + Pages (main /)
        → build site/ → copy to repo root → commit main
        → GitHub Pages
```
