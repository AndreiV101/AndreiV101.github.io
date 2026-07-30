#!/usr/bin/env python3
"""Enforce web-hosting repo naming and GitHub Pages (main + root)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def fail(msg: str) -> None:
    print(f"::error::{msg}")
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def github_get(path: str, token: str) -> dict | None:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "template-drive-to-website-host-check",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            return None
        fail(f"GitHub API {path} failed ({exc.code}): {body[:500]}")
    return None


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not repository or "/" not in repository:
        fail("GITHUB_REPOSITORY must be set as owner/repo")
    if not token:
        fail("GITHUB_TOKEN is required to check Pages settings")

    owner, repo = repository.split("/", 1)
    expected = f"{owner}.github.io"
    if repo.lower() != expected.lower():
        fail(
            f"Repo must be named '{expected}' (got '{repo}'). "
            "GitHub user/org Pages require owner.github.io. "
            "Copy the public template into that hosting repo "
            "(the template repo's owner does not matter)."
        )
    print(f"OK naming: {repository}")

    pages = github_get(f"/repos/{owner}/{repo}/pages", token)
    if pages is None:
        fail(
            "GitHub Pages is not enabled. "
            "Settings → Pages → Build and deployment → Source: Deploy from a branch → "
            "Branch: main → folder: / (root)."
        )

    source = pages.get("source") or {}
    branch = (source.get("branch") or "").strip()
    path = source.get("path") or "/"
    # API may return "/" or "/docs"
    if branch != "main":
        fail(
            f"Pages must deploy from branch 'main' (got '{branch or '(empty)'}'). "
            "Settings → Pages → Source: Deploy from a branch → main → / (root)."
        )
    if path not in ("/", ""):
        fail(
            f"Pages must use folder '/' (repo root), not '{path}'. "
            "Settings → Pages → Source: Deploy from a branch → main → / (root)."
        )

    print(f"OK Pages: branch=main path={path or '/'}")
    html_url = pages.get("html_url") or f"https://{repo}/"
    print(f"Pages URL: {html_url}")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"pages_url={html_url}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
