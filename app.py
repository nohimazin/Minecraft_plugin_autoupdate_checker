from __future__ import annotations

import base64
import csv
import json
import hashlib
import os
import queue
import re
import shutil
import sqlite3
import threading
import traceback
import concurrent.futures
import urllib.parse
import urllib.request
import webbrowser
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
import tkinter as tk
from tkinter import BOTH, BOTTOM, END, LEFT, RIGHT, X, Y, DoubleVar, Tk, StringVar, filedialog, messagebox, simpledialog, ttk

try:
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


APP_TITLE = "Minecraft Plugin Auto Update Checker"
APP_DIR = Path.home() / ".minecraft_plugin_autoupdate_checker"
DB_PATH = APP_DIR / "plugin-manager.sqlite"
MODRINTH_SEARCH_URL = "https://api.modrinth.com/v2/search"
MODRINTH_VERSIONS_URL = "https://api.modrinth.com/v2/project/{project_id}/version"
MODRINTH_PROJECT_PAGE_URL = "https://modrinth.com/plugin/{project_id}"
MODRINTH_VERSION_PAGE_URL = "https://modrinth.com/plugin/{project_id}/version/{version_id}"
USER_AGENT = "MinecraftPluginAutoUpdateChecker/1.0"
MODRINTH_PROJECT_URL = "https://api.modrinth.com/v2/project/{project_id}"
HANGAR_PROJECTS_URL = "https://hangar.papermc.io/api/v1/projects"
HANGAR_PROJECT_URL = "https://hangar.papermc.io/api/v1/projects/{owner}/{slug}"
HANGAR_PROJECT_VERSIONS_URL = "https://hangar.papermc.io/api/v1/projects/{owner}/{slug}/versions"
HANGAR_PROJECT_PAGE_URL = "https://hangar.papermc.io/{owner}/{slug}"
HANGAR_VERSION_PAGE_URL = "https://hangar.papermc.io/{owner}/{slug}/versions/{version_id}"
GITHUB_REPO_URL = "https://api.github.com/repos/{owner}/{repo}"
GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
GITHUB_RELEASES_URL = "https://api.github.com/repos/{owner}/{repo}/releases"
GITHUB_PROJECT_PAGE_URL = "https://github.com/{owner}/{repo}"
SPIGET_RESOURCE_URL = "https://api.spiget.org/v2/resources/{id}"
SPIGET_VERSIONS_URL = "https://api.spiget.org/v2/resources/{id}/versions"
SPIGET_DOWNLOAD_URL = "https://api.spiget.org/v2/resources/{id}/download?version={version_id}"
SPIGET_PROJECT_PAGE_URL = "https://spiget.org/resource/{id}"
SPIGITMC_PROJECT_PAGE_URL = "https://www.spigotmc.org/resources/{id}/"
SPIGET_ICON_BASE_URL = "https://www.spigotmc.org/"
SERVER_SOFTWARE_OPTIONS = ["自動", "Paper", "Spigot", "Bukkit", "Purpur"]
SERVER_SOFTWARE_LOADERS = {
    "paper": ["paper", "spigot", "bukkit"],
    "spigot": ["spigot", "bukkit"],
    "bukkit": ["bukkit"],
    "purpur": ["purpur", "paper", "spigot", "bukkit"],
}
MODRINTH_PLUGIN_CATEGORIES = ["bukkit", "paper", "spigot", "bungeecord", "waterfall", "velocity", "purpur", "folia"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_filename(value: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*]+", "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or "plugin"


def normalize_server_software(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"", "auto", "自動"}:
        return ""
    return normalized


def loader_candidates_for_software(value: str) -> list[str]:
    normalized = normalize_server_software(value)
    if not normalized:
        return []
    return SERVER_SOFTWARE_LOADERS.get(normalized, [normalized])


class Tooltip:
    """Simple tooltip for a Tk widget."""
    def __init__(self, widget, text: str, delay: int = 500) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id: str | None = None
        self.tipwindow: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, event=None) -> None:
        self._unschedule()
        try:
            self._after_id = self.widget.after(self.delay, self._show)
        except Exception:
            self._after_id = None

    def _unschedule(self) -> None:
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self, event=None) -> None:
        if self.tipwindow or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 1
            tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            label = tk.Label(tw, text=self.text, justify='left', background='#ffffe0', relief='solid', borderwidth=1)
            label.pack(ipadx=6, ipady=3)
            self.tipwindow = tw
        except Exception:
            self.tipwindow = None

    def _hide(self, event=None) -> None:
        self._unschedule()
        if self.tipwindow:
            try:
                self.tipwindow.destroy()
            except Exception:
                pass
            self.tipwindow = None


def _attach_tooltip(widget, text: str) -> None:
    if widget is None or not text:
        return
    try:
        if getattr(widget, "_tooltip_text", "") == text:
            return
    except Exception:
        pass
    try:
        Tooltip(widget, text)
        widget._tooltip_text = text
    except Exception:
        pass


def extract_modrinth_project_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    parsed = urllib.parse.urlparse(text)
    path = parsed.path.strip("/")
    if parsed.netloc and "modrinth.com" in parsed.netloc.lower() and path:
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"plugin", "mod", "project"}:
            candidate = parts[1]
            if re.fullmatch(r"[A-Za-z0-9-]+", candidate):
                return candidate

    match = re.search(r"modrinth\.com/(?:plugin|mod|project)/([A-Za-z0-9-]+)", text)
    if match:
        return match.group(1)

    match = re.search(r"api\.modrinth\.com/v2/project/([A-Za-z0-9-]+)", text)
    if match:
        return match.group(1)

    if re.fullmatch(r"[A-Za-z0-9-]+", text):
        return text

    return ""


def extract_hangar_project_ref(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    parsed = urllib.parse.urlparse(text)
    path = parsed.path.strip("/")
    if parsed.netloc and "hangar.papermc.io" in parsed.netloc.lower() and path:
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2:
            if parts[0] == "api" and len(parts) >= 5 and parts[1] == "v1" and parts[2] == "projects":
                owner = parts[3]
                slug = parts[4]
                if owner and slug:
                    return f"{owner}/{slug}"
            if parts[0] not in {"api", "authors", "staff", "paper", "velocity", "waterfall"}:
                owner = parts[0]
                slug = parts[1]
                if owner and slug:
                    return f"{owner}/{slug}"

    match = re.search(r"hangar\.papermc\.io/(?:api/v1/projects/)?([^/?#]+)/([^/?#]+)", text)
    if match:
        return f"{match.group(1)}/{match.group(2)}"

    if re.fullmatch(r"[^/\s]+/[^/\s]+", text):
        return text

    return ""


def extract_github_repo_ref(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    parsed = urllib.parse.urlparse(text)
    path = parsed.path.strip("/")
    if parsed.netloc and "github.com" in parsed.netloc.lower() and path:
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] not in {"settings", "topics", "features", "pricing", "contact"}:
            owner = parts[0]
            repo = parts[1]
            if repo.lower() == "releases" and len(parts) >= 3:
                repo = parts[1]
            if owner and repo:
                return f"{owner}/{repo}"

    match = re.search(r"github\.com/([^/?#]+)/([^/?#]+)", text)
    if match:
        owner = match.group(1)
        repo = match.group(2)
        if repo.lower() == "releases" and "/releases/" in text:
            repo = match.group(2)
        return f"{owner}/{repo}"

    match = re.search(r"api\.github\.com/repos/([^/?#]+)/([^/?#]+)", text)
    if match:
        return f"{match.group(1)}/{match.group(2)}"

    if re.fullmatch(r"[^/\s]+/[^/\s]+", text):
        return text

    return ""


def version_key(version: str) -> tuple:
    if not version:
        return (), 0, ""

    match = re.match(r"^\D*(\d+(?:\.\d+)*)", version)
    numeric = tuple(int(part) for part in match.group(1).split(".")) if match else ()
    suffix = version[match.end():].lower().strip("-_. +") if match else version.lower().strip("-_. +")

    if not suffix:
        rank = 0
    elif any(token in suffix for token in ("alpha", "beta", "snapshot", "pre", "rc")):
        rank = -1
    else:
        rank = 1

    return numeric, rank, suffix


def compare_versions(left: str, right: str) -> int:
    left_key = version_key(left)
    right_key = version_key(right)
    if left_key > right_key:
        return 1
    if left_key < right_key:
        return -1
    return 0


def extract_version_from_filename(file_name: str) -> tuple[str, str]:
    stem = Path(file_name).stem
    patterns = [
        re.compile(r"^(?P<name>.+?)[\s._-]+v?(?P<version>\d+(?:\.\d+){1,5}(?:[-+][0-9A-Za-z._-]+)?)$", re.IGNORECASE),
        re.compile(r"^(?P<name>.+?)[\s._-]+v?(?P<version>\d+(?:\.\d+){1,5})$", re.IGNORECASE),
        re.compile(r"^(?P<name>.+?)[\s._-]+(?P<version>[0-9A-Za-z][0-9A-Za-z._-]*\d[0-9A-Za-z._-]*)$", re.IGNORECASE),
    ]

    for pattern in patterns:
        match = pattern.match(stem)
        if match:
            name = match.group("name").strip(" -_.")
            version = match.group("version").strip(" -_.")
            return name or stem, version

    return stem, ""


def extract_jar_names_from_listing(listing_text: str) -> list[str]:
    jar_names: list[str] = []
    seen: set[str] = set()
    for raw_line in listing_text.splitlines():
        line = raw_line.strip().strip('"')
        if not line:
            continue

        if line.startswith("total "):
            continue

        candidates: list[str] = []
        if re.match(r"^[bcdlps-][rwx-]{9}\s", line):
            parts = line.split(maxsplit=8)
            if len(parts) >= 9:
                candidates.append(parts[8])
        else:
            # ls output can be column-aligned; a single line may contain multiple file names.
            # Collect every .jar token on the line instead of only the trailing one.
            candidates.extend(re.findall(r"(?<!\S)([^\s]+?\.jar)(?=\s|$)", line, re.IGNORECASE))

        for candidate in candidates:
            candidate = Path(candidate.rstrip("/")).name
            if not candidate.lower().endswith(".jar"):
                continue
            if candidate not in seen:
                seen.add(candidate)
                jar_names.append(candidate)

    return jar_names


def plugin_query_candidates(plugin_name: str, file_name: str | None = None) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        normalized = re.sub(r"[\W_]+", " ", value).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            candidates.append(normalized)

    # Primary forms
    add(plugin_name)
    if file_name:
        add(Path(file_name).stem)

    # Remove common platform suffixes like -bukkit, -paper, -spigot, -geyser etc.
    stripped = re.sub(r"(?i)(?:-?(?:bukkit|paper|spigot|legacy|plugin|platform|server-side|serverside|geyser|floodgate|paper-plugin))+$", "", plugin_name)
    add(stripped)

    # Strip trailing version tokens
    stripped = re.sub(r"(?i)[\s._-]v?\d+(?:\.\d+){1,5}(?:[-+][0-9A-Za-z._-]+)?$", "", plugin_name)
    add(stripped)

    if file_name:
        stripped_file = re.sub(r"(?i)[\s._-]v?\d+(?:\.\d+){1,5}(?:[-+][0-9A-Za-z._-]+)?$", "", Path(file_name).stem)
        add(stripped_file)

    # Generate slug-like and tokenized variants to match Modrinth search behavior
    def slugify(v: str) -> str:
        s = re.sub(r"[^0-9A-Za-z]+", "-", v).strip("-_")
        return s

    for base in list(candidates):
        add(slugify(base))
        add(base.replace(" ", "-"))
        # add individual tokens (e.g., "GeyserMC" -> "Geyser", "MC")
        for token in re.split(r"[\s._-]+", base):
            if token:
                add(token)

    return candidates


def strip_platform_suffixes(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    text = Path(text).stem
    text = re.sub(r"(?i)(?:-?(?:bukkit|paper|spigot|legacy|plugin|platform|server-side|serverside|geyser|floodgate|paper-plugin))+$", "", text)
    text = re.sub(r"(?i)[\s._-]v?\d+(?:\.\d+){1,5}(?:[-+][0-9A-Za-z._-]+)?$", "", text)
    return text.strip(" -_.")


def normalize_modrinth_lookup(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", (value or "").lower())


def http_json(url: str, params: dict[str, object] | None = None) -> dict:
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def download_file(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def search_modrinth_plugin(query: str) -> dict | None:
    def search_once(term: str) -> list[dict]:
        params: dict[str, object] = {
            "query": term,
            "limit": 10,
            "facets": json.dumps([[f"categories:{category}" for category in MODRINTH_PLUGIN_CATEGORIES]]),
        }
        data = http_json(MODRINTH_SEARCH_URL, params)
        hits = data.get("hits", [])
        return [
            hit
            for hit in hits
            if set(str(category).lower() for category in hit.get("categories", [])) & set(MODRINTH_PLUGIN_CATEGORIES)
        ]

    def run_search_pass(base_query: str) -> dict | None:
        # Search only within Modrinth plugin projects.
        for term in plugin_query_candidates(base_query):
            term_exact = normalize_modrinth_lookup(term)
            try:
                hits = search_once(term)
            except Exception:
                continue

            for hit in hits:
                title = normalize_modrinth_lookup(str(hit.get("title", "")))
                slug = normalize_modrinth_lookup(str(hit.get("slug", "")))
                if term_exact and (title == term_exact or slug == term_exact):
                    return hit

        return None

    hit = run_search_pass(query)
    if hit:
        return hit

    stripped_query = strip_platform_suffixes(query)
    if stripped_query and normalize_modrinth_lookup(stripped_query) != normalize_modrinth_lookup(query):
        hit = run_search_pass(stripped_query)
        if hit:
            return hit

    return None


MODRINTH_VERSION_CHANNEL_LABELS = {
    "release": "安定版のみ",
    "beta": "ベータ版も取得",
    "alpha": "アルファ版も取得",
}


def normalize_modrinth_version_channel(value: str) -> str:
    text = (value or "").strip().lower()
    if text in MODRINTH_VERSION_CHANNEL_LABELS:
        return text
    for key, label in MODRINTH_VERSION_CHANNEL_LABELS.items():
        if text == label.lower():
            return key
    return "release"


def modrinth_version_channel_label(value: str) -> str:
    channel = normalize_modrinth_version_channel(value)
    return MODRINTH_VERSION_CHANNEL_LABELS.get(channel, MODRINTH_VERSION_CHANNEL_LABELS["release"])


def _modrinth_is_plugin_loader_version(item: dict) -> bool:
    loaders = {str(loader).lower() for loader in (item.get("loaders") or []) if str(loader).strip()}
    if not loaders:
        return True
    plugin_loaders = {"bukkit", "paper", "spigot", "purpur", "folia", "velocity", "waterfall", "bungeecord"}
    fabric_like_loaders = {"fabric", "quilt", "forge", "neoforge", "liteloader"}
    if loaders & plugin_loaders:
        return True
    if loaders & fabric_like_loaders:
        return False
    return True


def _modrinth_loader_hints_from_text(text: str) -> list[str]:
    lowered = (text or "").lower()
    hints: list[str] = []
    mapping = {
        "bukkit": ("bukkit",),
        "paper": ("paper",),
        "spigot": ("spigot",),
        "purpur": ("purpur",),
        "folia": ("folia",),
        "velocity": ("velocity",),
        "waterfall": ("waterfall",),
        "bungeecord": ("bungeecord", "bungee"),
        "fabric": ("fabric",),
        "quilt": ("quilt",),
        "forge": ("forge",),
        "neoforge": ("neoforge",),
    }
    for loader, tokens in mapping.items():
        if any(token in lowered for token in tokens) and loader not in hints:
            hints.append(loader)
    return hints


def _best_loader_rank(item_loaders: list[str], preferred_loaders: list[str]) -> int:
    if not preferred_loaders:
        return 0
    loader_set = {str(loader).lower() for loader in item_loaders if str(loader).strip()}
    for index, loader in enumerate(preferred_loaders):
        if loader in loader_set:
            return index
    return len(preferred_loaders)


def get_modrinth_release(project_id: str, server_version: str = "", server_software: str = "", version_channel: str = "release", source_title: str = "") -> dict | None:
    versions = http_json(MODRINTH_VERSIONS_URL.format(project_id=project_id))
    if not versions:
        return None

    allowed_types = allowed_modrinth_version_types(version_channel)
    versions = [item for item in versions if str(item.get("version_type") or "release").lower() in allowed_types]
    if not versions:
        return None

    target_version = (server_version or "").strip()
    target_loaders = loader_candidates_for_software(server_software)
    inferred_loaders = _modrinth_loader_hints_from_text(source_title)
    if not target_loaders and inferred_loaders:
        target_loaders = list(inferred_loaders)

    def version_matches(item: dict) -> bool:
        item_loaders = [str(loader).lower() for loader in (item.get("loaders") or [])]
        item_game_versions = {str(version).strip() for version in (item.get("game_versions") or [])}

        if target_loaders and not any(loader in target_loaders for loader in item_loaders):
            return False
        if target_version and target_version not in item_game_versions:
            return False
        return True

    matched_versions = [item for item in versions if version_matches(item)]
    if not matched_versions and not target_version and target_loaders:
        matched_versions = [item for item in versions if any(loader in target_loaders for loader in [str(x).lower() for x in (item.get("loaders") or [])])]
    if not matched_versions and not target_loaders:
        plugin_pref_versions = [item for item in versions if _modrinth_is_plugin_loader_version(item)]
        matched_versions = plugin_pref_versions or versions
    if not matched_versions:
        return None

    preferred_loaders = target_loaders or _modrinth_loader_hints_from_text(source_title)

    def modrinth_sort_key(item: dict) -> tuple[int, str]:
        item_loaders = [str(loader).lower() for loader in (item.get("loaders") or [])]
        return (-_best_loader_rank(item_loaders, preferred_loaders), str(item.get("date_published", "")))

    latest = max(matched_versions, key=modrinth_sort_key)
    files = latest.get("files", []) or []
    download_url = files[0].get("url", "") if files else ""
    return {
        "project_id": project_id,
        "title": latest.get("name") or latest.get("version_number") or project_id,
        "version": latest.get("version_number") or latest.get("name") or "",
        "version_id": latest.get("id") or "",
        "download_url": download_url,
        "date_published": latest.get("date_published", ""),
        "matched_server_version": target_version,
        "matched_server_software": normalize_server_software(server_software),
    }


def hangar_platform_candidates(server_software: str) -> list[str]:
    normalized = normalize_server_software(server_software)
    if normalized == "purpur":
        return ["PURPUR", "PAPER", "SPIGOT", "BUKKIT"]
    if normalized == "paper":
        return ["PAPER", "SPIGOT", "BUKKIT"]
    if normalized == "spigot":
        return ["SPIGOT", "BUKKIT"]
    if normalized == "bukkit":
        return ["BUKKIT"]
    if normalized == "folia":
        return ["FOLIA", "PAPER", "SPIGOT", "BUKKIT"]
    if normalized == "velocity":
        return ["VELOCITY"]
    if normalized in {"waterfall", "bungeecord"}:
        return ["WATERFALL"]
    return []


def hangar_version_matches_target(target_version: str, candidate: str) -> bool:
    target = (target_version or "").strip()
    spec = (candidate or "").strip()
    if not target or not spec:
        return True
    if "-" in spec:
        start, end = spec.split("-", 1)
        start = start.strip()
        end = end.strip()
        if start and compare_versions(target, start) < 0:
            return False
        if end and compare_versions(target, end) > 0:
            return False
        return True
    return compare_versions(target, spec) == 0


def search_hangar_project(query: str) -> dict | None:
    def search_once(term: str) -> list[dict]:
        params = {"query": term, "limit": 25, "offset": 0}
        data = http_json(HANGAR_PROJECTS_URL, params)
        return data.get("result", []) if isinstance(data, dict) else []

    def run_search_pass(base_query: str) -> dict | None:
        for term in plugin_query_candidates(base_query):
            term_exact = normalize_modrinth_lookup(term)
            try:
                hits = search_once(term)
            except Exception:
                continue

            for hit in hits:
                namespace = hit.get("namespace") or {}
                title = normalize_modrinth_lookup(str(hit.get("name", "")))
                slug = normalize_modrinth_lookup(str(namespace.get("slug", "")))
                owner = normalize_modrinth_lookup(str(namespace.get("owner", "")))
                if term_exact and (title == term_exact or slug == term_exact or owner == term_exact):
                    return {
                        "source_type": "hangar",
                        "source_id": f"{namespace.get('owner', '')}/{namespace.get('slug', '')}".strip("/"),
                        "source_title": hit.get("name") or namespace.get("slug") or term,
                    }

        return None

    hit = run_search_pass(query)
    if hit:
        return hit

    stripped_query = strip_platform_suffixes(query)
    if stripped_query and normalize_modrinth_lookup(stripped_query) != normalize_modrinth_lookup(query):
        hit = run_search_pass(stripped_query)
        if hit:
            return hit

    return None


def get_hangar_release(project_ref: str, server_version: str = "", server_software: str = "") -> dict | None:
    ref = extract_hangar_project_ref(project_ref)
    if not ref:
        return None

    owner, slug = ref.split("/", 1)
    versions: list[dict] = []
    offset = 0
    limit = 100
    while True:
        data = http_json(HANGAR_PROJECT_VERSIONS_URL.format(owner=owner, slug=slug), {"limit": limit, "offset": offset})
        page_versions = data.get("result", []) if isinstance(data, dict) else []
        versions.extend(page_versions)
        pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
        count = int(pagination.get("count", len(versions)) or len(versions))
        offset += limit
        if not page_versions or offset >= count:
            break

    if not versions:
        return None

    target_version = (server_version or "").strip()
    target_platforms = hangar_platform_candidates(server_software)

    def version_matches(item: dict) -> bool:
        platform_dependencies = item.get("platformDependencies") or {}
        if target_platforms:
            if not any(platform in platform_dependencies for platform in target_platforms):
                return False
            if target_version:
                if not any(
                    hangar_version_matches_target(target_version, str(spec))
                    for platform in target_platforms
                    for spec in (platform_dependencies.get(platform) or [])
                ):
                    return False
        elif target_version:
            if not any(
                hangar_version_matches_target(target_version, str(spec))
                for specs in platform_dependencies.values()
                for spec in (specs or [])
            ):
                return False
        return True

    matched_versions = [item for item in versions if version_matches(item)]
    if not matched_versions and not target_version and target_platforms:
        matched_versions = [item for item in versions if any(platform in (item.get("platformDependencies") or {}) for platform in target_platforms)]
    if not matched_versions and not target_version and not target_platforms:
        matched_versions = versions
    if not matched_versions:
        return None

    def hangar_sort_key(item: dict) -> tuple[int, str]:
        platform_dependencies = item.get("platformDependencies") or {}
        if not target_platforms:
            return (0, str(item.get("createdAt", "")))
        for index, platform in enumerate(target_platforms):
            if platform in platform_dependencies:
                return (-index, str(item.get("createdAt", "")))
        return (-(len(target_platforms)), str(item.get("createdAt", "")))

    latest = max(matched_versions, key=hangar_sort_key)
    downloads = latest.get("downloads") or {}
    download_url = ""
    candidate_platforms = target_platforms or list(downloads.keys())
    for platform in candidate_platforms:
        platform_download = downloads.get(platform) or {}
        if isinstance(platform_download, dict):
            download_url = str(platform_download.get("externalUrl") or platform_download.get("downloadUrl") or "")
        if download_url:
            break
    if not download_url:
        for platform_download in downloads.values():
            if isinstance(platform_download, dict):
                download_url = str(platform_download.get("externalUrl") or platform_download.get("downloadUrl") or "")
            if download_url:
                break

    return {
        "project_id": ref,
        "title": latest.get("name") or slug,
        "version": latest.get("name") or slug,
        "version_id": latest.get("id") or "",
        "download_url": download_url,
        "date_published": latest.get("createdAt", ""),
        "matched_server_version": target_version,
        "matched_server_software": normalize_server_software(server_software),
    }


def get_github_release(repo_ref: str, server_version: str = "", server_software: str = "") -> dict | None:
    ref = extract_github_repo_ref(repo_ref)
    if not ref:
        return None

    owner, repo = ref.split("/", 1)
    latest = None
    try:
        latest = http_json(GITHUB_LATEST_RELEASE_URL.format(owner=owner, repo=repo))
    except Exception:
        latest = None
    if not latest:
        try:
            releases = http_json(GITHUB_RELEASES_URL.format(owner=owner, repo=repo), {"per_page": 100})
        except Exception:
            releases = []
        for item in releases or []:
            if not item.get("draft") and not item.get("prerelease"):
                latest = item
                break
    if not latest:
        return None

    assets = latest.get("assets", []) or []
    download_url = ""
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if name.endswith(".jar") and asset.get("browser_download_url"):
            download_url = str(asset.get("browser_download_url") or "")
            break
    if not download_url and assets:
        first_asset = assets[0] or {}
        download_url = str(first_asset.get("browser_download_url") or "")
    if not download_url:
        download_url = str(latest.get("zipball_url") or latest.get("tarball_url") or "")

    return {
        "project_id": ref,
        "title": latest.get("name") or latest.get("tag_name") or repo,
        "version": latest.get("tag_name") or latest.get("name") or "",
        "download_url": download_url,
        "date_published": latest.get("published_at") or latest.get("created_at") or "",
        "matched_server_version": (server_version or "").strip(),
        "matched_server_software": normalize_server_software(server_software),
    }


def extract_spiget_resource_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    parsed = urllib.parse.urlparse(text)
    path = (parsed.path or "").strip("/")

    parts = [part for part in path.split("/") if part]
    for index, part in enumerate(parts):
        if part not in {"resources", "resource", "v2"}:
            continue
        if part == "v2" and index + 2 < len(parts) and parts[index + 1] == "resources":
            candidate = parts[index + 2]
        elif index + 1 < len(parts):
            candidate = parts[index + 1]
        else:
            continue

        if re.fullmatch(r"\d+", candidate):
            return candidate

        dotted = re.search(r"(?:^|\.)(\d+)$", candidate)
        if dotted:
            return dotted.group(1)

    # try matching in plain text for copied URLs and API URLs
    m = re.search(r"(?:spigotmc\.org/resources/|spiget\.org/resource/|api\.spiget\.org/v2/resources/)(?:[^/?#]+[./])?(\d+)", text)
    if m:
        return m.group(1)

    # numeric id fallback
    if re.fullmatch(r"\d+", text):
        return text

    # bare SpigotMC resource refs like "geyserskinmanager.88607"
    bare_dotted = re.search(r"(?:^|\.)(\d+)$", text)
    if bare_dotted:
        return bare_dotted.group(1)

    return ""


def get_spiget_release(resource_ref: str, server_version: str = "", server_software: str = "") -> dict | None:
    ref = extract_spiget_resource_id(resource_ref)
    if not ref:
        return None

    try:
        resource = http_json(SPIGET_RESOURCE_URL.format(id=ref))
    except Exception:
        resource = {}

    try:
        versions = http_json(SPIGET_VERSIONS_URL.format(id=ref))
    except Exception:
        versions = []

    if not versions:
        # if no versions, still return basic resource info
        title = resource.get("name") or resource.get("title") or str(ref)
        return {
            "project_id": ref,
            "title": title,
            "version": "",
            "download_url": SPIGET_DOWNLOAD_URL.format(id=ref, version_id=""),
            "date_published": resource.get("date") or resource.get("createdAt") or "",
            "matched_server_version": (server_version or "").strip(),
            "matched_server_software": normalize_server_software(server_software),
        }

    def sort_key(v: dict) -> object:
        return v.get("releaseDate") or v.get("date") or v.get("timestamp") or v.get("id") or 0

    try:
        latest = max(versions, key=sort_key)
    except Exception:
        latest = versions[-1] if versions else {}

    version_id = latest.get("id") or ""
    version_name = str(latest.get("name") or latest.get("version") or version_id)
    download_url = SPIGET_DOWNLOAD_URL.format(id=ref, version_id=version_id) if version_id else SPIGET_DOWNLOAD_URL.format(id=ref, version_id="")

    title = resource.get("name") or resource.get("title") or str(ref)
    date_published = latest.get("releaseDate") or latest.get("date") or ""

    return {
        "project_id": ref,
        "title": title,
        "version": version_name,
        "version_id": version_id,
        "download_url": download_url,
        "date_published": date_published,
        "matched_server_version": (server_version or "").strip(),
        "matched_server_software": normalize_server_software(server_software),
    }


def allowed_modrinth_version_types(channel: str) -> set[str]:
    normalized = normalize_modrinth_version_channel(channel)
    if normalized == "alpha":
        return {"release", "beta", "alpha"}
    if normalized == "beta":
        return {"release", "beta"}
    return {"release"}


def ensure_modrinth_project_id(value: str) -> str:
    project_id = extract_modrinth_project_id(value)
    return project_id or (value or "").strip()


def format_source_label(source_type: str | None, source_title: str | None, source_id: str | None) -> str:
    """Return a friendly short label for a source. e.g. 'Modrinth', 'Hangar', '手動', or the provided title as fallback."""
    st = (source_type or "").lower() if source_type else ""
    if st == "modrinth":
        return "Modrinth"
    if st == "hangar":
        return "Hangar"
    if st == "github":
        return "GitHub"
    if st == "spiget":
        return "SpigotMC"
    if st == "spigot":
        return "SpigotMC"
    if st in ("manual", "listing") or (source_id and str(source_id).startswith("listing://")):
        return "手動"
    # fallback to visible title if given
    if source_title:
        # if title looks like a project name rather than provider, prefer provider
        if any(tok in str(source_title).lower() for tok in ("modrinth", "hangar", "curseforge", "github")):
            return source_title
        # otherwise show the provider if available in source_type
    if st:
        return st.capitalize()
    if source_title:
        return source_title
    if source_id:
        return str(source_id)
    return "-"


def build_source_url(source_type: str | None, source_id: str | None) -> str:
    """Build a provider homepage URL from source type/id when possible."""
    st = normalize_source_type(source_type)
    sid = str(source_id or "").strip()
    if not sid:
        return ""
    if sid.startswith("http://") or sid.startswith("https://"):
        return sid
    if st == "modrinth":
        proj = ensure_modrinth_project_id(sid)
        return MODRINTH_PROJECT_PAGE_URL.format(project_id=proj) if proj else ""
    if st == "hangar":
        ref = extract_hangar_project_ref(sid)
        if ref:
            owner, slug = ref.split("/", 1)
            return HANGAR_PROJECT_PAGE_URL.format(owner=owner, slug=slug)
        return ""
    if st == "github":
        ref = extract_github_repo_ref(sid)
        if ref:
            owner, repo = ref.split("/", 1)
            return GITHUB_PROJECT_PAGE_URL.format(owner=owner, repo=repo)
        return ""
    if st in {"spiget", "spigot"} and sid:
        return SPIGITMC_PROJECT_PAGE_URL.format(id=sid)
    return ""


def normalize_source_type(value: str | None) -> str:
    st = (value or "").strip().lower()
    if st in {"spigot", "spigotmc", "spiget"}:
        return "spiget"
    if st in {"modrinth", "hangar", "github"}:
        return st
    return st


def row_get(row, key: str, default=None):
    """Safe getter for sqlite3.Row and normal dicts."""
    try:
        # dict-like with get
        return row.get(key, default)
    except Exception:
        # sqlite3.Row or mapping without get
        try:
            return row[key]
        except Exception:
            return default


@dataclass
class PluginEntry:
    plugin_name: str
    current_version: str
    file_name: str
    file_path: str
    source_type: str = ""
    source_id: str = ""
    source_title: str = ""
    latest_version: str = ""
    latest_download_url: str = ""
    update_available: int = 0
    last_checked: str = ""
    last_error: str = ""


@dataclass
class ImportedJarEntry:
    file_name: str
    plugin_name: str
    current_version: str
    file_path: str


def _safe_log(logger: logging.Logger | None, level: int, msg: str, *args) -> None:
    try:
        if logger:
            logger.log(level, msg, *args)
    except Exception:
        pass


def _safe_debug(logger: logging.Logger | None, msg: str, *args) -> None:
    _safe_log(logger, logging.DEBUG, msg, *args)


def _safe_info(logger: logging.Logger | None, msg: str, *args) -> None:
    _safe_log(logger, logging.INFO, msg, *args)


class PluginDatabase:
    def __init__(self, db_path: Path) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        # master connection (stores settings and servers list)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        # server-specific connection (plugins) — opened when a server is selected
        self.server_connection: sqlite3.Connection | None = None
        self.server_db_path: Path | None = None
        self.current_server_id: int = 0

        self._init_schema()
        # migrate existing plugins into per-server DBs if needed later (handled on open_server_db)
        self._migrate_spiget_rows()
        self._deduplicate_listing_plugins()

    def _init_schema(self) -> None:
        """Initialize master database schema (settings, servers, legacy plugins).

        This prepares the master connection used for application settings and the
        servers list. Plugin rows may be migrated into per-server DBs later.
        """
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS plugins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plugin_name TEXT NOT NULL,
                    current_version TEXT NOT NULL DEFAULT '',
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    source_type TEXT NOT NULL DEFAULT '',
                    source_id TEXT NOT NULL DEFAULT '',
                    source_title TEXT NOT NULL DEFAULT '',
                    latest_version TEXT NOT NULL DEFAULT '',
                    latest_version_id TEXT NOT NULL DEFAULT '',
                    server_id INTEGER NOT NULL DEFAULT 0,
                    latest_download_url TEXT NOT NULL DEFAULT '',
                    update_available INTEGER NOT NULL DEFAULT 0,
                    last_checked TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # create servers table
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    server_version TEXT NOT NULL DEFAULT '',
                    server_software TEXT NOT NULL DEFAULT '',
                    plugin_folder TEXT NOT NULL DEFAULT '',
                    modrinth_version_channel TEXT NOT NULL DEFAULT '',
                    db_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            server_cols = [r[1] for r in self.connection.execute("PRAGMA table_info(servers)").fetchall()]
            if "modrinth_version_channel" not in server_cols:
                try:
                    self.connection.execute("ALTER TABLE servers ADD COLUMN modrinth_version_channel TEXT NOT NULL DEFAULT ''")
                except Exception:
                    pass
            # ensure legacy DBs have the latest_version_id and server_id columns
            cols = [r[1] for r in self.connection.execute("PRAGMA table_info(plugins)").fetchall()]
            if "latest_version_id" not in cols:
                try:
                    self.connection.execute("ALTER TABLE plugins ADD COLUMN latest_version_id TEXT NOT NULL DEFAULT ''")
                except Exception:
                    pass
            if "server_id" not in cols:
                try:
                    self.connection.execute("ALTER TABLE plugins ADD COLUMN server_id INTEGER NOT NULL DEFAULT 0")
                except Exception:
                    pass
            self.connection.execute("CREATE INDEX IF NOT EXISTS idx_plugins_name ON plugins(plugin_name)")

    def _init_plugins_schema(self, conn: sqlite3.Connection) -> None:
        """Initialize plugins table/schema on the given connection (used for per-server DBs)."""
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS plugins (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        plugin_name TEXT NOT NULL,
                        current_version TEXT NOT NULL DEFAULT '',
                        file_name TEXT NOT NULL,
                        file_path TEXT NOT NULL UNIQUE,
                        source_type TEXT NOT NULL DEFAULT '',
                        source_id TEXT NOT NULL DEFAULT '',
                        source_title TEXT NOT NULL DEFAULT '',
                        latest_version TEXT NOT NULL DEFAULT '',
                        latest_version_id TEXT NOT NULL DEFAULT '',
                        server_id INTEGER NOT NULL DEFAULT 0,
                        latest_download_url TEXT NOT NULL DEFAULT '',
                        update_available INTEGER NOT NULL DEFAULT 0,
                        last_checked TEXT NOT NULL DEFAULT '',
                        last_error TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                # ensure columns exist for legacy compatibility
                cols = [r[1] for r in conn.execute("PRAGMA table_info(plugins)").fetchall()]
                if "latest_version_id" not in cols:
                    try:
                        conn.execute("ALTER TABLE plugins ADD COLUMN latest_version_id TEXT NOT NULL DEFAULT ''")
                    except Exception:
                        pass
                if "server_id" not in cols:
                    try:
                        conn.execute("ALTER TABLE plugins ADD COLUMN server_id INTEGER NOT NULL DEFAULT 0")
                    except Exception:
                        pass
                try:
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_plugins_name ON plugins(plugin_name)")
                except Exception:
                    pass
        except Exception:
            pass

    # lightweight logger for DB operations
    _logger = logging.getLogger("minecraft_plugin_autoupdate_checker.db")
    logging.basicConfig(level=logging.INFO)
    

    def open_server_db(self, server_id: int) -> None:
        """Open (or create) the per-server sqlite DB for the given server id.
        This will initialize the plugins schema in that DB and move any matching rows
        from the master plugins table if present.
        """
        row = None
        try:
            row = self.connection.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()
        except Exception:
            row = None

        if not row:
            return

        db_path_val = str(row_get(row, "db_path") or "").strip()
        if not db_path_val:
            server_dir = APP_DIR / "servers"
            server_dir.mkdir(parents=True, exist_ok=True)
            db_path = server_dir / f"server_{server_id}.sqlite"
            db_path_val = str(db_path)
            with self.connection:
                self.connection.execute("UPDATE servers SET db_path = ? WHERE id = ?", (db_path_val, server_id))
        else:
            db_path = Path(db_path_val)

        # if already opened and same path, nothing to do
        if self.server_connection and self.server_db_path and Path(db_path) == Path(self.server_db_path):
            return

        # close previous
        try:
            if self.server_connection:
                self.server_connection.close()
        except Exception:
            pass

        # open new server DB
        server_db_path = Path(db_path)
        server_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(server_db_path)
        conn.row_factory = sqlite3.Row
        self.server_connection = conn
        self.server_db_path = server_db_path
        self.current_server_id = server_id
        # ensure plugins schema exists in server DB
        try:
            self._init_plugins_schema(conn)
        except Exception:
            pass
        try:
            self._logger.debug("Opened server DB %s for server_id=%s", server_db_path, server_id)
        except Exception:
            pass

        # migrate rows from master plugins that belong to this server (server_id matches) OR global (server_id==0)
        try:
            master_rows = list(self.connection.execute("SELECT * FROM plugins WHERE server_id = ? OR server_id = 0", (server_id,)).fetchall())
            if master_rows:
                with conn:
                    for r in master_rows:
                        cols = [c[0] for c in self.connection.execute("PRAGMA table_info(plugins)").fetchall()]
                        values = [r[c] if c in r.keys() else None for c in cols]
                        placeholders = ",".join("?" for _ in cols)
                        conn.execute(f"INSERT OR REPLACE INTO plugins({', '.join(cols)}) VALUES({placeholders})", values)
                # delete migrated rows from master
                ids = [str(int(r["id"])) for r in master_rows if r.get("id")]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    with self.connection:
                        self.connection.execute(f"DELETE FROM plugins WHERE id IN ({placeholders})", ids)
        except Exception:
            pass

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def upsert_local_plugins(self, entries: list[PluginEntry]) -> None:
        conn = self.server_connection
        if not conn:
            return
        inserted = 0
        updated = 0
        with conn:
            for entry in entries:
                created_at = now_iso()
                existing = conn.execute(
                    "SELECT id FROM plugins WHERE file_path = ?",
                    (entry.file_path,),
                ).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE plugins
                        SET plugin_name = ?, current_version = ?, file_name = ?, updated_at = ?
                        WHERE file_path = ?
                        """,
                        (entry.plugin_name, entry.current_version, entry.file_name, created_at, entry.file_path),
                    )
                    updated += 1
                    _safe_debug(self._logger, "upsert_local_plugins: updated %s", entry.file_path)
                else:
                    # include server_id when inserting into a server DB
                    if self.current_server_id:
                        conn.execute(
                            """
                            INSERT INTO plugins(
                                plugin_name, current_version, file_name, file_path, server_id,
                                source_type, source_id, source_title,
                                latest_version, latest_download_url, update_available,
                                last_checked, last_error, created_at, updated_at
                            ) VALUES(?, ?, ?, ?, ?, '', '', '', '', '', 0, '', '', ?, ?)
                            """,
                            (
                                entry.plugin_name,
                                entry.current_version,
                                entry.file_name,
                                entry.file_path,
                                int(self.current_server_id),
                                created_at,
                                created_at,
                            ),
                        )
                        inserted += 1
                        _safe_debug(self._logger, "upsert_local_plugins: inserted %s", entry.file_path)
                    else:
                        conn.execute(
                            """
                            INSERT INTO plugins(
                                plugin_name, current_version, file_name, file_path,
                                source_type, source_id, source_title,
                                latest_version, latest_download_url, update_available,
                                last_checked, last_error, created_at, updated_at
                            ) VALUES(?, ?, ?, ?, '', '', '', '', '', 0, '', '', ?, ?)
                            """,
                            (
                                entry.plugin_name,
                                entry.current_version,
                                entry.file_name,
                                entry.file_path,
                                created_at,
                                created_at,
                            ),
                        )
                        inserted += 1
                        _safe_debug(self._logger, "upsert_local_plugins: inserted %s", entry.file_path)
        _safe_info(self._logger, "upsert_local_plugins: inserted=%s updated=%s total=%s", inserted, updated, len(entries))

    def upsert_imported_jars(self, jar_names: list[str]) -> int:
        conn = self.server_connection
        if not conn:
            return 0
        entries: list[PluginEntry] = []
        for jar_name in jar_names:
            plugin_name, version = extract_version_from_filename(jar_name)
            entries.append(
                PluginEntry(
                    plugin_name=plugin_name,
                    current_version=version,
                    file_name=jar_name,
                    file_path=f"listing://{jar_name}",
                )
            )

        self.upsert_local_plugins(entries)
        _safe_info(self._logger, "upsert_imported_jars: imported=%s", len(entries))
        return len(entries)

    def _deduplicate_listing_plugins(self) -> None:
        conn = self.server_connection or self.connection
        duplicates = conn.execute(
            """
            SELECT file_name, current_version, MIN(id) AS keep_id, GROUP_CONCAT(id) AS ids, COUNT(*) AS count
            FROM plugins
            WHERE file_path LIKE 'listing://%'
            GROUP BY file_name, current_version
            HAVING COUNT(*) > 1
            """
        ).fetchall()

        if not duplicates:
            return

        with conn:
            for row in duplicates:
                keep_id = int(row["keep_id"])
                ids = [int(value) for value in str(row["ids"]).split(",") if value]
                delete_ids = [value for value in ids if value != keep_id]
                if delete_ids:
                    placeholders = ",".join("?" for _ in delete_ids)
                    conn.execute(f"DELETE FROM plugins WHERE id IN ({placeholders})", delete_ids)

    def _migrate_spiget_rows(self) -> None:
        rows = self.connection.execute(
            """
            SELECT id, plugin_name, source_type, source_id, source_title
            FROM plugins
            WHERE source_id LIKE '%spigotmc.org/%' OR source_id LIKE '%spiget.org/%' OR source_title LIKE '%spigotmc.org/%'
            """
        ).fetchall()

        if not rows:
            return

        with self.connection:
            for row in rows:
                resource_id = extract_spiget_resource_id(str(row["source_id"] or row["source_title"] or ""))
                if not resource_id:
                    continue
                self.connection.execute(
                    """
                    UPDATE plugins
                    SET source_type = 'spiget', source_id = ?, source_title = COALESCE(NULLIF(source_title, ''), plugin_name), updated_at = ?
                    WHERE id = ?
                    """,
                    (resource_id, now_iso(), row["id"]),
                )

    def list_plugins(self) -> list[sqlite3.Row]:
        conn = self.server_connection
        if not conn:
            return []
        return list(conn.execute("SELECT * FROM plugins ORDER BY plugin_name COLLATE NOCASE"))

    def list_plugins_search(self, search: str | None = None) -> list[sqlite3.Row]:
        """List plugins, optionally filtering by a search string matching name, file or source."""
        conn = self.server_connection
        if not conn:
            return []
        base_sql = "SELECT * FROM plugins"
        params: list[object] = []
        if search and search.strip():
            term = f"%{search.strip()}%"
            where = " WHERE (plugin_name LIKE ? OR file_name LIKE ? OR source_title LIKE ? OR source_id LIKE ?) "
            params = [term, term, term, term]
            sql = base_sql + where + " ORDER BY plugin_name COLLATE NOCASE"
            return list(conn.execute(sql, params))
        return list(conn.execute(base_sql + " ORDER BY plugin_name COLLATE NOCASE"))

    # Servers API
    def list_servers(self) -> list[sqlite3.Row]:
        return list(self.connection.execute("SELECT * FROM servers ORDER BY name COLLATE NOCASE"))

    def _normalize_server_input(
        self,
        name: str,
        server_version: str = "",
        server_software: str = "",
        plugin_folder: str = "",
        modrinth_version_channel: str = "",
    ) -> tuple[str, str, str, str, str]:
        """Normalize and trim server fields before insert/update."""
        return (
            str(name or "").strip() or "Default",
            str(server_version or "").strip(),
            str(server_software or "").strip(),
            str(plugin_folder or "").strip(),
            str(modrinth_version_channel or "").strip(),
        )

    def create_server(
        self,
        name: str,
        server_version: str = "",
        server_software: str = "",
        plugin_folder: str = "",
        modrinth_version_channel: str = "",
    ) -> int:
        name, server_version, server_software, plugin_folder, modrinth_version_channel = self._normalize_server_input(
            name,
            server_version,
            server_software,
            plugin_folder,
            modrinth_version_channel,
        )
        now = now_iso()
        with self.connection:
            cur = self.connection.execute(
                "INSERT INTO servers(name, server_version, server_software, plugin_folder, modrinth_version_channel, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (name, server_version, server_software, plugin_folder, modrinth_version_channel, now, now),
            )
            server_id = int(cur.lastrowid)
            _safe_debug(self._logger, "create_server: id=%s name=%s version=%s software=%s folder=%s", server_id, name, server_version, server_software, plugin_folder)
            return server_id

    def get_server(self, server_id: int) -> sqlite3.Row | None:
        try:
            return self.connection.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()
        except Exception:
            return None

    def update_server(
        self,
        server_id: int,
        name: str,
        server_version: str,
        server_software: str,
        plugin_folder: str,
        modrinth_version_channel: str = "",
    ) -> None:
        name, server_version, server_software, plugin_folder, modrinth_version_channel = self._normalize_server_input(
            name,
            server_version,
            server_software,
            plugin_folder,
            modrinth_version_channel,
        )
        now = now_iso()
        with self.connection:
            self.connection.execute(
                "UPDATE servers SET name = ?, server_version = ?, server_software = ?, plugin_folder = ?, modrinth_version_channel = ?, updated_at = ? WHERE id = ?",
                (name, server_version, server_software, plugin_folder, modrinth_version_channel, now, server_id),
            )
            _safe_debug(self._logger, "update_server: id=%s name=%s version=%s software=%s folder=%s", server_id, name, server_version, server_software, plugin_folder)

    def delete_server(self, server_id: int) -> None:
        # attempt to remove associated server DB file if present
        try:
            row = self.connection.execute("SELECT db_path FROM servers WHERE id = ?", (server_id,)).fetchone()
            db_path_val = str(row["db_path"] or "") if row else ""
            if db_path_val:
                try:
                    p = Path(db_path_val)
                    # if this is the currently opened server DB, close connection first
                    try:
                        if getattr(self, "server_db_path", None) and Path(self.server_db_path) == p and self.server_connection:
                            try:
                                self.server_connection.close()
                            except Exception:
                                pass
                            self.server_connection = None
                            self.server_db_path = None
                            self.current_server_id = 0
                    except Exception:
                        pass
                    if p.exists():
                        try:
                            p.unlink()
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        with self.connection:
            self.connection.execute("DELETE FROM servers WHERE id = ?", (server_id,))
            _safe_debug(self._logger, "delete_server: id=%s", server_id)

    def update_plugin_remote(
        self,
        file_path: str,
        source_type: str,
        source_id: str,
        source_title: str,
        latest_version: str,
        latest_version_id: str,
        latest_download_url: str,
        update_available: int,
        last_checked: str,
        last_error: str,
    ) -> None:
        conn = self.server_connection
        if not conn:
            return
        with conn:
            conn.execute(
                """
                UPDATE plugins
                SET source_type = ?, source_id = ?, source_title = ?, latest_version = ?,
                    latest_version_id = ?, latest_download_url = ?, update_available = ?, last_checked = ?, last_error = ?,
                    updated_at = ?
                WHERE file_path = ?
                """,
                (
                    source_type,
                    source_id,
                    source_title,
                    latest_version,
                    latest_version_id,
                    latest_download_url,
                    update_available,
                    last_checked,
                    last_error,
                    now_iso(),
                    file_path,
                ),
            )
        _safe_debug(self._logger, "update_plugin_remote: %s -> %s", file_path, latest_version)

    def get_plugin_by_path(self, file_path: str) -> sqlite3.Row | None:
        conn = self.server_connection
        if not conn:
            return None
        return conn.execute("SELECT * FROM plugins WHERE file_path = ?", (file_path,)).fetchone()

    def delete_plugin_by_path(self, file_path: str) -> None:
        conn = self.server_connection
        if not conn:
            return
        with conn:
            conn.execute("DELETE FROM plugins WHERE file_path = ?", (file_path,))
        _safe_debug(self._logger, "delete_plugin_by_path: %s", file_path)

class IconManager:
    def __init__(self, app: "PluginManagerApp") -> None:
        self.app = app
        self.cache_dir = APP_DIR / "icons"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.memory: dict[str, "tkinter.PhotoImage"] = {}
        self.pil = PIL_AVAILABLE

    def _key_for_row(self, row) -> str:
        # use source_id if available, else file_path
        sid = row_get(row, "source_id") or row_get(row, "file_path") or row_get(row, "file_name") or row_get(row, "plugin_name")
        raw = str(sid)
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()

    def get_icon_for_row(self, row) -> object:
        """Return a PhotoImage if available; otherwise return a placeholder and start async fetch."""
        key = self._key_for_row(row)
        if key in self.memory:
            return self.memory[key]

        # try to find cached file (support several extensions)
        for ext in (".png", ".gif", ".jpeg", ".jpg", ".webp"):
            path = self.cache_dir / f"{key}{ext}"
            if path.exists():
                try:
                    if self.pil:
                        pil_img = Image.open(path).convert("RGBA")
                        pil_img = pil_img.resize((24, 24), Image.LANCZOS)
                        img = ImageTk.PhotoImage(pil_img)
                    else:
                        if ext.lower() in (".png", ".gif"):
                            img = __import__("tkinter").PhotoImage(file=str(path))
                        else:
                            raise RuntimeError("Unsupported image format without Pillow: " + ext)
                    self.app._log(f"Icon loaded from cache: {path}")
                    self.memory[key] = img
                    return img
                except Exception:
                    self.app._log(f"Failed to load cached icon {path}: {traceback.format_exc()}".splitlines()[0])
                    break

        # not cached: return placeholder and start async fetch
        placeholder = self._make_placeholder(row)
        self.memory[key] = placeholder

        # start background fetch
        threading.Thread(target=self._fetch_icon_background, args=(key, row), daemon=True).start()
        return placeholder

    def _fetch_icon_background(self, key: str, row) -> None:
        try:
            source_type = row_get(row, "source_type")
            source_id = str(row_get(row, "source_id") or "")
            icon_url = None
            normalized_source_type = normalize_source_type(source_type)

            if normalized_source_type == "modrinth" and source_id:
                try:
                    project_id = ensure_modrinth_project_id(source_id)
                    data = http_json(MODRINTH_PROJECT_URL.format(project_id=project_id))
                    icon_url = data.get("icon_url") or data.get("icon") or None
                except Exception:
                    icon_url = None
            elif normalized_source_type == "hangar" and source_id:
                try:
                    project_ref = extract_hangar_project_ref(source_id)
                    if project_ref:
                        owner, slug = project_ref.split("/", 1)
                        data = http_json(HANGAR_PROJECT_URL.format(owner=owner, slug=slug))
                        icon_url = data.get("avatarUrl") or data.get("avatar_url") or None
                except Exception:
                    icon_url = None
            elif normalized_source_type == "github" and source_id:
                try:
                    repo_ref = extract_github_repo_ref(source_id)
                    if repo_ref:
                        owner, repo = repo_ref.split("/", 1)
                        data = http_json(GITHUB_REPO_URL.format(owner=owner, repo=repo))
                        owner_info = data.get("owner") or {}
                        icon_url = owner_info.get("avatar_url") or data.get("avatar_url") or None
                except Exception:
                    icon_url = None
            elif normalized_source_type == "spiget" and source_id:
                try:
                    res = http_json(SPIGET_RESOURCE_URL.format(id=source_id))
                    icon = res.get("icon") or {}
                    if isinstance(icon, dict):
                        icon_url = icon.get("url") or icon.get("imageUrl") or icon.get("iconUrl") or None
                        icon_data = icon.get("data") or ""
                    else:
                        icon_url = res.get("image") or res.get("avatar") or res.get("iconUrl") or res.get("imageUrl") or None
                        icon_data = ""

                    if not icon_url and icon_data:
                        try:
                            raw_bytes = base64.b64decode(icon_data)
                            target = self.cache_dir / f"{key}.png"
                            target.write_bytes(raw_bytes)
                            self.app._log(f"Icon extracted from Spiget payload for {key} -> {target}")
                            self.app.task_queue.put(("icon_updated", key))
                            return
                        except Exception:
                            icon_url = None
                    if icon_url:
                        icon_url = urllib.parse.urljoin(SPIGET_ICON_BASE_URL, str(icon_url))
                        # Spiget's icon URL often ends in .jpg while the payload is actually PNG.
                        # Keep the fetched bytes, but normalize the cache extension to .png when the
                        # response is PNG-like so non-Pillow environments can load it.
                        parsed_icon_path = urllib.parse.urlparse(icon_url).path.lower()
                        if parsed_icon_path.endswith(".jpg") or parsed_icon_path.endswith(".jpeg"):
                            try:
                                req = urllib.request.Request(icon_url, headers={"User-Agent": USER_AGENT})
                                with urllib.request.urlopen(req, timeout=20) as resp:
                                    payload = resp.read()
                                if payload.startswith(b"\x89PNG\r\n\x1a\n"):
                                    target = self.cache_dir / f"{key}.png"
                                else:
                                    target = self.cache_dir / f"{key}{Path(parsed_icon_path).suffix or '.jpg'}"
                                target.write_bytes(payload)
                                self.app._log(f"Icon downloaded for {key}: {icon_url} -> {target}")
                                self.app.task_queue.put(("icon_updated", key))
                                return
                            except Exception:
                                icon_url = None
                except Exception:
                    icon_url = None
            if not icon_url:
                try:
                    hit = search_modrinth_plugin(row_get(row, "plugin_name") or row_get(row, "file_name") or "")
                    if hit and hit.get("project_id"):
                        data = http_json(MODRINTH_PROJECT_URL.format(project_id=hit["project_id"]))
                        icon_url = data.get("icon_url") or data.get("icon") or None
                    if not icon_url:
                        hit = search_hangar_project(row_get(row, "plugin_name") or row_get(row, "file_name") or "")
                        if hit and hit.get("source_id"):
                            owner, slug = str(hit["source_id"]).split("/", 1)
                            data = http_json(HANGAR_PROJECT_URL.format(owner=owner, slug=slug))
                            icon_url = data.get("avatarUrl") or data.get("avatar_url") or None
                except Exception:
                    icon_url = None

            if not icon_url:
                # log that we couldn't find an icon URL for this row
                try:
                    self.app._log(f"No icon URL for {key} (plugin: {row_get(row, 'plugin_name')})")
                except Exception:
                    pass
                return

            parsed = urllib.parse.urlparse(icon_url)
            ext = Path(parsed.path).suffix or ".png"
            target = self.cache_dir / f"{key}{ext}"
            # download
            req = urllib.request.Request(icon_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp, target.open("wb") as fh:
                fh.write(resp.read())
            # notify app to refresh UI; the actual PhotoImage load happens on the main thread
            self.app._log(f"Icon downloaded for {key}: {icon_url} -> {target}")
            self.app.task_queue.put(("icon_updated", key))
        except Exception:
            try:
                self.app._log(f"Icon fetch failed for {key}: {traceback.format_exc()}".splitlines()[0])
            except Exception:
                pass
            return

    def _make_placeholder(self, row) -> object:
        # simple colored square placeholder
        name = row_get(row, "plugin_name") or row_get(row, "file_name") or "?"
        h = abs(hash(name)) % 0xFFFFFF
        r = (h >> 16) & 0xFF
        g = (h >> 8) & 0xFF
        b = h & 0xFF
        color = f"#{r:02x}{g:02x}{b:02x}"
        img = __import__("tkinter").PhotoImage(width=24, height=24)
        # fill with color
        pixels = [color] * 24
        for y in range(24):
            img.put("{" + " ".join(pixels) + "}", to=(0, y))
        return img


def scan_plugin_folder(folder: Path) -> list[PluginEntry]:
    entries: list[PluginEntry] = []
    for file_path in sorted(folder.glob("*.jar")):
        plugin_name, version = extract_version_from_filename(file_path.name)
        entries.append(
            PluginEntry(
                plugin_name=plugin_name,
                current_version=version,
                file_name=file_path.name,
                file_path=str(file_path.resolve()),
            )
        )
    return entries


class PluginManagerApp(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x720")
        self.minsize(1060, 640)

        self.database = PluginDatabase(DB_PATH)
        # selected server id (0 == global)
        try:
            sel = int(self.database.get_setting("selected_server_id", "0") or "0")
        except Exception:
            sel = 0
        self.selected_server_id = tk.IntVar(value=sel)
        self.plugin_folder = StringVar(value=self.database.get_setting("plugin_folder", ""))
        self.server_version = StringVar(value=self.database.get_setting("server_version", ""))
        self.server_software = StringVar(value=self.database.get_setting("server_software", ""))
        # concurrency workers setting (defaults to min(8, cpu*2))
        default_workers = min(8, max(2, (os.cpu_count() or 2) * 2))
        try:
            saved_workers = int(self.database.get_setting("concurrency_workers", str(default_workers)))
        except Exception:
            saved_workers = default_workers
        self.concurrency_workers = tk.IntVar(value=saved_workers)
        self.status_text = StringVar(value=f"DB: {DB_PATH}")
        self.busy_text = StringVar(value="待機中")
        self.db_count_text = StringVar(value="DB件数: 0")
        self.progress_text = StringVar(value="進捗: 待機中")
        self.progress_value = DoubleVar(value=0)
        self.progress_total = 1
        self.task_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.icon_manager = IconManager(self)
        self.selected_file_path: str | None = None
        self.row_index: dict[str, sqlite3.Row] = {}
        self.tree_item_to_path: dict[str, str] = {}
        self.search_text = StringVar(value="")
        self._search_after_id = None
        self._reload_after_id = None
        self._last_reload_time = 0.0
        self._server_settings_after_id = None

        self._build_ui()
        # make sure initial UI is rendered before doing heavier work
        try:
            self.update_idletasks()
        except Exception:
            pass
        self._setup_context_menu_bindings()
        self._save_server_settings()
        self.after(100, self._poll_task_queue)
        # Defer the initial full reload so the window becomes responsive immediately.
        self.after(200, self.reload_tree)
        if self.plugin_folder.get():
            self._log(f"前回のプラグインフォルダを読み込みました: {self.plugin_folder.get()}")

        # If there are no servers in the DB, prompt the user to add one by
        # automatically opening the server manager after the main window shows.
        try:
            servers = self.database.list_servers()
            if not servers:
                def _prompt_create_server():
                    try:
                        messagebox.showinfo("サーバー未登録", "サーバーが登録されていません。サーバー管理で新しいサーバーを追加してください。", parent=self)
                    except Exception:
                        try:
                            messagebox.showinfo("サーバー未登録", "サーバーが登録されていません。サーバー管理で新しいサーバーを追加してください。")
                        except Exception:
                            pass
                    try:
                        self._open_server_manager()
                    except Exception:
                        pass

                self.after(300, _prompt_create_server)
        except Exception:
            pass

        # selected server id (0 == global)
        try:
            sel = int(self.database.get_setting("selected_server_id", "0") or "0")
        except Exception:
            sel = 0
        self.selected_server_id = tk.IntVar(value=sel)
        try:
            if sel:
                self.database.open_server_db(sel)
        except Exception:
            pass

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=BOTH, expand=True)

        style = ttk.Style(self)
        try:
            if os.name == "nt":
                ui_font = ("Yu Gothic UI", 10)
                heading_font = ("Yu Gothic UI", 10, "bold")
            else:
                ui_font = ("Sans", 10)
                heading_font = ("Sans", 10, "bold")

            style.configure("Treeview", rowheight=34, font=ui_font)
            style.configure("Treeview.Heading", font=heading_font)
        except Exception:
            pass

        top = ttk.Frame(outer)
        top.pack(fill=X)

        folder_frame = ttk.LabelFrame(top, text="プラグインフォルダ")
        folder_frame.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))

        plugin_folder_entry = ttk.Entry(folder_frame, textvariable=self.plugin_folder)
        plugin_folder_entry.pack(side=LEFT, fill=X, expand=True, padx=8, pady=8)
        choose_btn = ttk.Button(folder_frame, text="選択", command=self.choose_folder)
        choose_btn.pack(side=LEFT, padx=(0, 8), pady=8)
        scan_btn = ttk.Button(folder_frame, text="スキャン", command=self.scan_folder)
        scan_btn.pack(side=LEFT, padx=(0, 8), pady=8)
        try:
            Tooltip(plugin_folder_entry, "プラグインが置かれたフォルダのパス。\nスキャンでこのフォルダ内の .jar を登録します。")
            Tooltip(choose_btn, "プラグインフォルダを選択します。")
            Tooltip(scan_btn, "選択したフォルダ内の .jar を検出してDBに登録します。")
        except Exception:
            pass

        server_frame = ttk.LabelFrame(top, text="サーバー設定")
        server_frame.pack(side=LEFT, fill=X, expand=True)
        # server selector
        ttk.Label(server_frame, text="サーバー").pack(side=LEFT, padx=(8, 4), pady=8)
        self._server_combo_var = StringVar(value="")
        self._server_name_list: list[str] = []
        self._server_id_list: list[int] = []
        self._server_combo_widget = ttk.Combobox(server_frame, textvariable=self._server_combo_var, state="readonly", width=18)
        self._server_combo_widget.pack(side=LEFT, padx=(0, 8), pady=8)
        self._server_combo_widget.bind("<<ComboboxSelected>>", lambda event: self._on_server_combo_changed())
        manage_btn = ttk.Button(server_frame, text="サーバー管理", command=lambda: self._open_server_manager())
        manage_btn.pack(side=LEFT, padx=(0, 8), pady=8)
        _attach_tooltip(self._server_combo_widget, "操作対象のサーバーを選択します。")
        _attach_tooltip(manage_btn, "サーバーの追加・編集・削除を開きます。")

        # populate server list in main UI now
        try:
            self._load_servers_to_ui()
        except Exception:
            pass

        # バージョン/ソフトはサーバー管理ダイアログで設定します（トップ画面には表示しない）

        # Concurrency control for update checks
        ttk.Label(server_frame, text="並列ワーカー").pack(side=LEFT, padx=(0, 4), pady=8)
        try:
            spin = tk.Spinbox(server_frame, from_=1, to=32, width=3, textvariable=self.concurrency_workers)
        except Exception:
            spin = tk.Entry(server_frame, width=3, textvariable=self.concurrency_workers)
        spin.pack(side=LEFT, padx=(0, 10), pady=8)
        try:
            Tooltip(spin, "更新確認で同時に実行するワーカー数。\n値を大きくすると処理は速くなりますが、\n同時接続が増えるため公開APIへの負荷が高まり、\nアクセス制限（ブロック）される可能性があります。\n安全な目安: 4〜8")
        except Exception:
            pass

        self.server_version.trace_add("write", lambda *args: self._schedule_server_settings_save())
        self.server_software.trace_add("write", lambda *args: self._schedule_server_settings_save())
        self.concurrency_workers.trace_add("write", lambda *args: self._schedule_server_settings_save())

        listing_frame = ttk.LabelFrame(outer, text="一覧から取り込み")
        listing_frame.pack(fill=X, pady=(10, 0))

        listing_top = ttk.Frame(listing_frame)
        listing_top.pack(fill=X, padx=8, pady=(8, 6))

        listing_left = ttk.Frame(listing_top)
        listing_left.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(listing_left, text="ls等の出力を貼り付け: ").pack(side=LEFT, padx=(0, 4))
        file_from_btn = ttk.Button(listing_left, text="ファイルから読込", command=self.load_listing_file)
        file_from_btn.pack(side=LEFT, padx=(0, 8))
        import_btn = ttk.Button(listing_left, text="取り込み", command=self.import_listing_text)
        import_btn.pack(side=LEFT)

        add_from_url_btn = ttk.Button(listing_top, text="配布元URLでプラグインを追加", command=self._add_plugin_from_source_url)
        add_from_url_btn.pack(side=RIGHT)
        import_tsv_btn = ttk.Button(listing_top, text="TSVから取り込み", command=self.import_plugins_from_tsv)
        import_tsv_btn.pack(side=RIGHT, padx=(0, 8))
        _attach_tooltip(file_from_btn, "ローカルの一覧テキストから .jar 名を取り込む")
        _attach_tooltip(import_btn, "貼り付けた一覧から .jar をDBに登録する")
        _attach_tooltip(import_tsv_btn, "TSV(UTF-16/UTF-8)からプラグイン一覧を取り込みます")
        _attach_tooltip(add_from_url_btn, "配布元のURLや project ref からプラグインを手動追加する")

        self.listing_text = __import__("tkinter").Text(listing_frame, height=4, wrap="none")
        self.listing_text.pack(fill=X, padx=8, pady=(0, 8))
        _attach_tooltip(self.listing_text, "ls 等の出力を貼り付ける領域。\nここから .jar 名を抽出して登録します。")

        progress_frame = ttk.LabelFrame(outer, text="進捗")
        progress_frame.pack(fill=X, pady=(10, 0))
        ttk.Label(progress_frame, textvariable=self.progress_text, anchor="w").pack(fill=X, padx=8, pady=(6, 0))
        self.progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", variable=self.progress_value)
        self.progress_bar.pack(fill=X, padx=8, pady=(4, 8))

        main_area = ttk.PanedWindow(outer, orient="vertical")
        main_area.pack(fill=BOTH, expand=True, pady=(10, 8))

        upper_area = ttk.Frame(main_area)
        list_area = ttk.Frame(upper_area)
        list_area.pack(side=LEFT, fill=BOTH, expand=True)

        # 検索ボックス: DB一覧のフィルタリング
        search_frame = ttk.Frame(list_area)
        search_frame.pack(fill=X, pady=(0, 6))
        ttk.Label(search_frame, text="検索:").pack(side=LEFT, padx=(4, 4))
        search_entry = ttk.Entry(search_frame, textvariable=self.search_text)
        search_entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 6))
        def on_search_enter(event=None):
            self.reload_tree()
        search_entry.bind("<Return>", on_search_enter)
        # live filter: reload on every key release (即時フィルタ)
        search_entry.bind("<KeyRelease>", lambda e: self.reload_tree())
        search_btn = ttk.Button(search_frame, text="検索", command=self.reload_tree)
        search_btn.pack(side=LEFT, padx=(0, 6))
        def clear_search():
            self.search_text.set("")
            self.reload_tree()
        clear_btn = ttk.Button(search_frame, text="クリア", command=clear_search)
        clear_btn.pack(side=LEFT)
        try:
            Tooltip(search_entry, "プラグイン名やファイル名で一覧をフィルタします。\nEnter で即時検索")
            Tooltip(search_btn, "現在の検索条件で一覧を再読み込みします")
            Tooltip(clear_btn, "検索条件をクリアします")
        except Exception:
            pass

        list_frame = ttk.Frame(list_area)
        list_frame.pack(fill=BOTH, expand=True)

        cols = ("plugin_name", "current_version", "last_checked", "source")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="アイコン")
        self.tree.heading("plugin_name", text="プラグイン")
        self.tree.heading("current_version", text="バージョン")
        self.tree.heading("last_checked", text="更新日時")
        self.tree.heading("source", text="提供元")
        self.tree.column("#0", width=60, stretch=False, anchor="center")
        self.tree.column("plugin_name", width=260)
        self.tree.column("current_version", width=120)
        self.tree.column("last_checked", width=160)
        self.tree.column("source", width=120)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        _attach_tooltip(self.tree, "プラグイン一覧です。項目を選んで右側の操作を実行します。")

        list_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        list_scrollbar.pack(side=RIGHT, fill=Y)
        self.tree.configure(yscrollcommand=list_scrollbar.set)
        
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        sidebar_frame = ttk.LabelFrame(upper_area, text="操作")
        sidebar_frame.pack(side=RIGHT, fill=Y, padx=(8, 0), pady=0)

        sidebar_canvas = tk.Canvas(sidebar_frame, highlightthickness=0, borderwidth=0, width=190)
        sidebar_scrollbar = ttk.Scrollbar(sidebar_frame, orient="vertical", command=sidebar_canvas.yview)
        sidebar_canvas.configure(yscrollcommand=sidebar_scrollbar.set)
        sidebar_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        sidebar_scrollbar.pack(side=RIGHT, fill=Y)

        sidebar = ttk.Frame(sidebar_canvas)
        sidebar_window = sidebar_canvas.create_window((0, 0), window=sidebar, anchor="nw")

        def _update_sidebar_scrollregion(event=None) -> None:
            sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all"))
            sidebar_canvas.itemconfigure(sidebar_window, width=sidebar_canvas.winfo_width())

        def _sidebar_on_mousewheel(event) -> str:
            widget = event.widget
            while widget is not None:
                if widget == sidebar_frame:
                    break
                widget = getattr(widget, "master", None)
            else:
                return ""

            delta = 0
            if hasattr(event, "delta") and event.delta:
                delta = -1 if event.delta > 0 else 1
            elif getattr(event, "num", None) == 4:
                delta = -1
            elif getattr(event, "num", None) == 5:
                delta = 1
            if delta:
                sidebar_canvas.yview_scroll(delta, "units")
            return "break"

        sidebar.bind("<Configure>", _update_sidebar_scrollregion)
        sidebar_canvas.bind("<Configure>", _update_sidebar_scrollregion)
        sidebar_canvas.bind_all("<MouseWheel>", _sidebar_on_mousewheel, add="+")
        sidebar_canvas.bind_all("<Button-4>", _sidebar_on_mousewheel, add="+")
        sidebar_canvas.bind_all("<Button-5>", _sidebar_on_mousewheel, add="+")

        bulk_dl_btn = ttk.Button(sidebar, text="一括ダウンロード", command=self.download_updates_manually)
        bulk_dl_btn.pack(fill=X, padx=8, pady=4)
        check_updates_btn = ttk.Button(sidebar, text="更新を確認", command=self.check_updates)
        check_updates_btn.pack(fill=X, padx=8, pady=4)
        failed_list_btn = ttk.Button(sidebar, text="マッチ失敗一覧", command=self.show_failed_matches)
        failed_list_btn.pack(fill=X, padx=8, pady=4)
        open_homepage_btn = ttk.Button(sidebar, text="提供元のページを開く", command=self._open_selected_homepage)
        open_homepage_btn.pack(fill=X, padx=8, pady=4)
        change_version_btn = ttk.Button(sidebar, text="バージョンを変更", command=self._change_selected_version)
        change_version_btn.pack(fill=X, padx=8, pady=4)
        delete_btn = ttk.Button(sidebar, text="削除", command=self._delete_selected_plugin)
        delete_btn.pack(fill=X, padx=8, pady=4)
        edit_url_btn = ttk.Button(sidebar, text="URLを変更", command=self._edit_selected_source_url)
        edit_url_btn.pack(fill=X, padx=8, pady=4)
        export_btn = ttk.Button(sidebar, text="リストをエキスポート", command=self._export_plugins)
        export_btn.pack(fill=X, padx=8, pady=(4, 8))
        try:
            Tooltip(bulk_dl_btn, "プラグインの更新を確認し、一括でダウンロードします")
            Tooltip(check_updates_btn, "一覧の全プラグインについて最新版の有無を確認します")
            Tooltip(failed_list_btn, "自動マッチに失敗したプラグインを一覧表示します")
            Tooltip(open_homepage_btn, "選択中のプラグインの配布元ページをブラウザで開きます")
            Tooltip(change_version_btn, "選択中のプラグインの現在の版を手動で変更します")
            Tooltip(delete_btn, "選択中のプラグインを一覧から削除します")
            Tooltip(edit_url_btn, "選択中のプラグインの配布元 URL / project ref を編集します")
            Tooltip(export_btn, "DB のプラグイン一覧をTSV(UTF-16)で書き出します")
        except Exception:
            pass

        detail_notebook = ttk.Notebook(main_area)

        db_frame = ttk.Frame(detail_notebook)
        detail_notebook.add(db_frame, text="DB内容")
        ttk.Label(db_frame, textvariable=self.db_count_text, anchor="w").pack(fill=X, padx=8, pady=(6, 0))
        self.db_text = __import__("tkinter").Text(db_frame, height=8, wrap="none")
        self.db_text.pack(fill=BOTH, expand=True, padx=8, pady=8)
        self.db_text.configure(state="disabled")
        _attach_tooltip(self.db_text, "データベース内容の詳細表示です。")

        log_frame = ttk.Frame(detail_notebook)
        detail_notebook.add(log_frame, text="ログ")
        ttk.Label(log_frame, textvariable=self.status_text, anchor="w").pack(fill=X, padx=8, pady=(6, 0))

        self.text = __import__("tkinter").Text(log_frame, height=6, wrap="word")
        self.text.pack(fill=BOTH, expand=True, padx=8, pady=8)
        self.text.configure(state="disabled")
        _attach_tooltip(self.text, "実行ログを表示します。")

        main_area.add(upper_area, weight=4)
        main_area.add(detail_notebook, weight=1)

        footer = ttk.Frame(outer)
        footer.pack(fill=X, pady=(8, 0))
        ttk.Label(footer, textvariable=self.busy_text).pack(side=LEFT)
        ttk.Label(footer, text=f"SQLite: {DB_PATH}").pack(side=RIGHT)

    def _setup_context_menu_bindings(self) -> None:
        self._context_menu = tk.Menu(self, tearoff=0)
        self.bind_all("<Button-3>", self._show_context_menu, add="+")
        self.bind_all("<Button-2>", self._show_context_menu, add="+")

    def _show_context_menu(self, event) -> None:
        widget = event.widget
        try:
            widget.focus_set()
        except Exception:
            pass

        try:
            self._context_menu.delete(0, END)
        except Exception:
            self._context_menu = tk.Menu(self, tearoff=0)

        widget_class = str(widget.winfo_class())
        is_text = widget_class in {"Text", "Entry", "TEntry", "TCombobox"}
        is_tree = widget_class == "Treeview"

        if is_text:
            if widget_class == "Text":
                has_selection = bool(widget.tag_ranges("sel"))
            else:
                try:
                    has_selection = bool(widget.selection_present())
                except Exception:
                    has_selection = False

            def cut() -> None:
                if widget_class != "Text" and str(widget.cget("state")) == "readonly":
                    return
                try:
                    widget.event_generate("<<Cut>>")
                except Exception:
                    pass

            def paste() -> None:
                if widget_class != "Text" and str(widget.cget("state")) == "readonly":
                    return
                try:
                    widget.event_generate("<<Paste>>")
                except Exception:
                    pass

            def select_all() -> None:
                try:
                    if widget_class == "Text":
                        widget.tag_add("sel", "1.0", "end-1c")
                        widget.mark_set("insert", "end")
                        widget.see("insert")
                    else:
                        widget.selection_range(0, END)
                        widget.icursor(END)
                except Exception:
                    pass

            self._context_menu.add_command(label="切り取り", command=cut, state="normal" if widget_class == "Text" or str(widget.cget("state")) != "readonly" else "disabled")
            self._context_menu.add_command(label="コピー", command=copy)
            self._context_menu.add_command(label="貼り付け", command=paste, state="normal" if widget_class == "Text" or str(widget.cget("state")) != "readonly" else "disabled")
            self._context_menu.add_separator()
            self._context_menu.add_command(label="全選択", command=select_all)
        elif is_tree:
            def copy_row() -> None:
                try:
                    selection = widget.selection()
                    if not selection:
                        return
                    item = selection[0]
                    values = widget.item(item, "values")
                    self.clipboard_clear()
                    self.clipboard_append("\t".join(str(value) for value in values))
                except Exception:
                    pass

            self._context_menu.add_command(label="選択行をコピー", command=copy_row)

        if self._context_menu.index("end") is None:
            return

        try:
            if widget_class == "Treeview":
                row_id = widget.identify_row(event.y)
                if row_id:
                    widget.selection_set(row_id)
            elif widget_class == "Text":
                widget.mark_set("insert", f"@{event.x},{event.y}")
            elif widget_class in {"Entry", "TEntry", "TCombobox"}:
                try:
                    widget.icursor(widget.index(f"@{event.x},{event.y}"))
                except Exception:
                    pass
        except Exception:
            pass

        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self._context_menu.grab_release()
            except Exception:
                pass

    def _log(self, message: str) -> None:
        self.status_text.set(message)
        self.text.configure(state="normal")
        self.text.insert(END, f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")
        self.text.see(END)
        self.text.configure(state="disabled")
        self.update_idletasks()

    def _set_busy(self, message: str) -> None:
        self.busy_text.set(message)
        self.update_idletasks()

    def _set_progress(self, current: int, total: int, message: str) -> None:
        self.progress_total = max(total, 1)
        self.progress_bar.configure(maximum=self.progress_total)
        self.progress_value.set(current)
        self.progress_text.set(message)
        self.update_idletasks()

    def _reset_progress(self) -> None:
        self.progress_total = 1
        self.progress_bar.configure(maximum=1)
        self.progress_value.set(0)
        self.progress_text.set("進捗: 待機中")
        self.update_idletasks()

    def _schedule_server_settings_save(self) -> None:
        try:
            if getattr(self, "_server_settings_after_id", None):
                try:
                    self.after_cancel(self._server_settings_after_id)
                except Exception:
                    pass
            self._server_settings_after_id = self.after(300, self._save_server_settings)
        except Exception:
            try:
                self._save_server_settings()
            except Exception:
                pass

    def _save_server_settings(self) -> None:
        version = self.server_version.get().strip()
        software = self.server_software.get().strip()
        # Channel is managed per-server in the server manager; do not keep a global channel setting here.
        self.database.set_setting("server_version", version)
        self.database.set_setting("server_software", software)
        try:
            self.database.set_setting("concurrency_workers", str(int(self.concurrency_workers.get())))
        except Exception:
            pass
        # If a server is selected, persist these values on the server row as well
        try:
            sid = int(self.selected_server_id.get() or 0)
        except Exception:
            sid = 0
        if sid:
            srv = self.database.get_server(sid)
            if srv:
                name = str(row_get(srv, "name") or f"Server {sid}")
                try:
                    self.database.update_server(
                        sid,
                        name=name,
                        server_version=version,
                        server_software=software,
                        plugin_folder=self.plugin_folder.get() or "",
                    )
                except Exception:
                    pass

        db_label = DB_PATH
        if getattr(self.database, "server_db_path", None):
            db_label = getattr(self.database, "server_db_path")
        self.status_text.set(f"DB: {db_label} / サーバー: {software or '自動'} {version or '-'}")

    def _filter_rows_for_selected_server(self, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
        try:
            sid = int(self.selected_server_id.get() or 0)
        except Exception:
            sid = 0
        if sid == 0:
            return rows
        filtered: list[sqlite3.Row] = []
        for r in rows:
            try:
                rid = int(row_get(r, "server_id") or 0)
            except Exception:
                rid = 0
            if rid == 0 or rid == sid:
                filtered.append(r)
        return filtered

    def _get_server_context(self) -> tuple[str, str]:
        try:
            sid = int(self.selected_server_id.get() or 0)
        except Exception:
            sid = 0
        if sid:
            row = self.database.get_server(sid)
            if row is not None:
                return str(row_get(row, "server_version") or "").strip(), str(row_get(row, "server_software") or "").strip()
        return self.server_version.get().strip(), self.server_software.get().strip()

    def _get_modrinth_version_channel(self) -> str:
        try:
            sid = int(self.selected_server_id.get() or 0)
        except Exception:
            sid = 0
        if sid:
            srv = self.database.get_server(sid)
            if srv is not None:
                return normalize_modrinth_version_channel(str(row_get(srv, "modrinth_version_channel") or "release"))
        # fallback to release when no server selected
        return "release"

    def _apply_server_row_to_ui(self, srv: sqlite3.Row | None) -> None:
        """Apply values from a server row to the main UI StringVars."""
        if srv is None:
            return
        try:
            server_version = str(row_get(srv, "server_version") or "").strip()
            server_software = str(row_get(srv, "server_software") or "").strip()
            plugin_folder = str(row_get(srv, "plugin_folder") or "").strip()
            modrinth_channel = str(row_get(srv, "modrinth_version_channel") or "").strip()
            if plugin_folder:
                self.plugin_folder.set(plugin_folder)
            if server_version:
                self.server_version.set(server_version)
            if server_software:
                self.server_software.set(server_software)
            # modrinth channel is displayed/edited in server manager only
        except Exception:
            pass

    def _set_server_combo_values(self, names: list[str]) -> None:
        """Set server combo values safely when widget is available."""
        try:
            if hasattr(self, "_server_combo_widget") and self._server_combo_widget is not None:
                self._server_combo_widget["values"] = names
        except Exception:
            pass

    def _sync_selected_server(self, target_sid: int | None, reload_tree: bool = False) -> None:
        """Synchronize the selected server id, combo display, opened DB, and main UI fields."""
        try:
            sid = int(target_sid or 0)
        except Exception:
            sid = 0

        if sid <= 0 or sid not in self._server_id_list:
            try:
                self.selected_server_id.set(0)
                self.database.set_setting("selected_server_id", "")
                self._server_combo_var.set("")
            except Exception:
                pass
            try:
                self.database.open_server_db(0)
            except Exception:
                pass
            try:
                self._apply_server_row_to_ui(None)
            except Exception:
                pass
            if reload_tree:
                try:
                    self.reload_tree()
                except Exception:
                    pass
            return

        idx = self._server_id_list.index(sid)
        try:
            self._server_combo_var.set(self._server_name_list[idx])
        except Exception:
            pass
        try:
            self.selected_server_id.set(sid)
            self.database.set_setting("selected_server_id", str(sid))
        except Exception:
            pass
        try:
            self.database.open_server_db(int(sid))
        except Exception:
            pass
        try:
            srv = self.database.get_server(sid)
            self._apply_server_row_to_ui(srv)
        except Exception:
            pass
        if reload_tree:
            try:
                self.reload_tree()
            except Exception:
                pass

    def _select_server_by_id(self, target_sid: int | None, reload_tree: bool = False) -> None:
        """Select a server by id and sync DB/UI state if the id exists."""
        try:
            self._sync_selected_server(target_sid, reload_tree=reload_tree)
        except Exception:
            pass

    def _load_servers_to_ui(self) -> None:
        servers = self.database.list_servers()
        if not servers:
            # no servers present — do not auto-create a default entry
            _safe_info(self._logger, "_load_servers_to_ui: no servers found, leaving UI empty")
            self._server_name_list = []
            self._server_id_list = []
            self._set_server_combo_values(self._server_name_list)
            # clear selection state
            try:
                self._server_combo_var.set("")
            except Exception:
                pass
            try:
                self.selected_server_id.set(0)
                self.database.set_setting("selected_server_id", "")
            except Exception:
                pass
            try:
                self.reload_tree()
            except Exception:
                pass
            return

        self._server_name_list = [s["name"] for s in servers]
        self._server_id_list = [s["id"] for s in servers]
        self._set_server_combo_values(self._server_name_list)
        # select stored server or default
        try:
            sid = int(self.selected_server_id.get() or 0)
        except Exception:
            sid = 0

        if sid and sid in self._server_id_list:
            self._sync_selected_server(sid)
        else:
            if self._server_name_list:
                self._sync_selected_server(self._server_id_list[0])
        # Refresh plugin list once after switching active server context.
        try:
            self.reload_tree()
        except Exception:
            pass

    def _on_server_combo_changed(self) -> None:
        name = self._server_combo_var.get()
        if name and name in self._server_name_list:
            idx = self._server_name_list.index(name)
            sid = self._server_id_list[idx]
            self._sync_selected_server(sid, reload_tree=True)

    def _open_server_manager(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("サーバー管理")
        dialog.transient(self)
        dialog.grab_set()

        # two-pane server manager: list on left, edit form on right
        # keep selection visible even when focus moves to form widgets
        listbox = tk.Listbox(dialog, width=36, height=12, exportselection=False)
        listbox.pack(side=LEFT, padx=(8, 0), pady=8)
        _attach_tooltip(listbox, "登録済みサーバー一覧です。選択すると右側で編集できます。")

        form = ttk.Frame(dialog)
        form.pack(side=LEFT, fill=BOTH, expand=True, padx=8, pady=8)

        ttk.Label(form, text="名前").grid(row=0, column=0, sticky="w")
        name_var = StringVar()
        name_entry = ttk.Entry(form, textvariable=name_var)
        name_entry.grid(row=0, column=1, sticky="ew", pady=2)
        _attach_tooltip(name_entry, "サーバー名を入力します。")

        ttk.Label(form, text="バージョン").grid(row=1, column=0, sticky="w")
        version_var = StringVar()
        version_entry = ttk.Entry(form, textvariable=version_var)
        version_entry.grid(row=1, column=1, sticky="ew", pady=2)
        _attach_tooltip(version_entry, "対象Minecraftサーバーのバージョンを入力します。")

        ttk.Label(form, text="ソフト").grid(row=2, column=0, sticky="w")
        software_var = StringVar()
        software_combo = ttk.Combobox(form, textvariable=software_var, values=SERVER_SOFTWARE_OPTIONS, state="readonly")
        software_combo.grid(row=2, column=1, sticky="ew", pady=2)
        _attach_tooltip(software_combo, "サーバーソフトを選択します。")

        ttk.Label(form, text="プラグインフォルダ").grid(row=3, column=0, sticky="w")
        folder_var = StringVar()
        folder_entry = ttk.Entry(form, textvariable=folder_var)
        folder_entry.grid(row=3, column=1, sticky="ew", pady=2)
        _attach_tooltip(folder_entry, "このサーバーのプラグインフォルダを指定します。")
        def choose_folder_for_server():
            sel = filedialog.askdirectory(title="サーバーのプラグインフォルダを選択", parent=dialog)
            if sel:
                folder_var.set(sel)
        browse_folder_btn = ttk.Button(form, text="参照", command=choose_folder_for_server)
        browse_folder_btn.grid(row=3, column=2, padx=(6,0))
        _attach_tooltip(browse_folder_btn, "プラグインフォルダを選択します。")

        ttk.Label(form, text="Modrinth チャンネル").grid(row=4, column=0, sticky="w")
        modrinth_var = StringVar()
        modrinth_combo = ttk.Combobox(form, textvariable=modrinth_var, values=tuple(MODRINTH_VERSION_CHANNEL_LABELS.values()), state="readonly")
        modrinth_combo.grid(row=4, column=1, sticky="ew", pady=2)
        _attach_tooltip(modrinth_combo, "更新取得時のModrinthチャンネルを選択します。")

        form.columnconfigure(1, weight=1)

        selected_index: int | None = None
        server_ids: list[int] = []

        def refresh_server_list(selected_sid: int | None = None) -> None:
            nonlocal selected_index, server_ids
            try:
                listbox.delete(0, END)
            except Exception:
                pass
            servers = self.database.list_servers()
            server_ids = [int(s["id"]) for s in servers]
            for idx, s in enumerate(servers, start=1):
                listbox.insert(END, f"{idx}: {s['name']}")

            if selected_sid and selected_sid in server_ids:
                selected_index = server_ids.index(selected_sid)
            elif server_ids:
                selected_index = 0
            else:
                selected_index = None

            try:
                if selected_index is not None:
                    listbox.selection_set(selected_index)
                    listbox.activate(selected_index)
                    listbox.see(selected_index)
            except Exception:
                pass

        def load_server_into_form(sid: int) -> None:
            srv = self.database.get_server(sid)
            if not srv:
                return
            name_var.set(str(row_get(srv, "name") or ""))
            version_var.set(str(row_get(srv, "server_version") or ""))
            software_var.set(str(row_get(srv, "server_software") or ""))
            folder_var.set(str(row_get(srv, "plugin_folder") or ""))
            modrinth_var.set(modrinth_version_channel_label(str(row_get(srv, "modrinth_version_channel") or "")))

        def on_list_select(evt=None):
            nonlocal selected_index
            sel = listbox.curselection()
            if not sel:
                try:
                    save_btn.config(text="保存して追加")
                    del_btn.config(state="disabled")
                except Exception:
                    pass
                return
            idx = int(sel[0])
            if idx < 0 or idx >= len(server_ids):
                return
            sid = server_ids[idx]
            load_server_into_form(sid)
            try:
                save_btn.config(text="保存")
                del_btn.config(state="normal")
            except Exception:
                pass
            try:
                selected_index = idx
            except Exception:
                selected_index = None

        refresh_server_list()
        listbox.bind("<<ListboxSelect>>", on_list_select)
        # select the first server by default when opening the manager
        try:
            if listbox.size() > 0:
                selected_index = 0
                on_list_select()
        except Exception:
            pass

        # Restore listbox selection when form fields gain focus (some platforms may clear selection)
        def _restore_selection_on_focus(evt=None):
            try:
                cur = listbox.curselection()
                if cur:
                    return
                if selected_index is not None and 0 <= selected_index < listbox.size():
                    listbox.selection_set(selected_index)
                    listbox.activate(selected_index)
                    listbox.see(selected_index)
            except Exception:
                pass

        for w in (name_entry, version_entry, software_combo, folder_entry, modrinth_combo):
            try:
                w.bind('<FocusIn>', _restore_selection_on_focus)
            except Exception:
                pass

        def new_server():
            nonlocal selected_index
            try:
                listbox.selection_clear(0, END)
            except Exception:
                pass
            # prevent _restore_selection_on_focus from re-selecting previous item
            try:
                selected_index = None
            except Exception:
                pass
            name_var.set("")
            version_var.set("")
            software_var.set("")
            folder_var.set("")
            modrinth_var.set("")
            try:
                name_entry.focus_set()
            except Exception:
                pass
            try:
                save_btn.config(text="保存して追加")
                del_btn.config(state="disabled")
            except Exception:
                pass

        def save_server():
            sel = listbox.curselection()
            name = name_var.get().strip() or "Default"
            version = version_var.get().strip()
            software = software_var.get().strip()
            folder = folder_var.get().strip()
            modch = normalize_modrinth_version_channel(modrinth_var.get())
            if sel:
                idx = int(sel[0])
                if idx < 0 or idx >= len(server_ids):
                    return
                sid = server_ids[idx]
                try:
                    self.database.update_server(sid, name=name, server_version=version, server_software=software, plugin_folder=folder, modrinth_version_channel=modch)
                except sqlite3.IntegrityError:
                    messagebox.showerror("更新失敗", "同名のサーバーが既に存在します。別の名前を指定してください。", parent=dialog)
                    return
            else:
                try:
                    sid = self.database.create_server(name=name, server_version=version, server_software=software, plugin_folder=folder, modrinth_version_channel=modch)
                    try:
                        new_btn.config(state="normal")
                    except Exception:
                        pass
                except sqlite3.IntegrityError:
                    messagebox.showerror("追加失敗", "同名のサーバーが既に存在します。別の名前を指定してください。", parent=dialog)
                    return
            # ensure the saved/created server becomes the selected server in main UI
            try:
                self.database.set_setting("selected_server_id", str(sid))
                self._sync_selected_server(sid, reload_tree=True)
            except Exception:
                pass
            # Immediately update main UI variables so changes are visible
            try:
                # update main UI fields from the values just saved in the dialog
                if version is not None:
                    self.server_version.set(version)
                if software is not None:
                    self.server_software.set(software)
                if folder is not None:
                    self.plugin_folder.set(folder)
                try:
                    # persist these settings and update server row if needed
                    self._schedule_server_settings_save()
                except Exception:
                    pass
            except Exception:
                pass
            refresh_server_list(sid)
            try:
                self._sync_selected_server(sid, reload_tree=True)
            except Exception:
                pass

        def delete_server():
            sel = listbox.curselection()
            if not sel:
                return
            idx = int(sel[0])
            if idx < 0 or idx >= len(server_ids):
                return
            sid = server_ids[idx]
            if not messagebox.askyesno("削除確認", "このサーバーを削除しますか?", parent=dialog):
                return
            try:
                self.database.delete_server(sid)
            except Exception as exc:
                messagebox.showerror("削除失敗", str(exc), parent=dialog)
                return
            try:
                if len(server_ids) <= 1:
                    new_btn.config(state="disabled")
            except Exception:
                pass
            refresh_server_list()
            if server_ids:
                try:
                    on_list_select()
                except Exception:
                    pass
            else:
                new_server()

        # Buttons: stack vertically at the right side
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(side=RIGHT, fill=Y, padx=8, pady=8)
        new_btn = ttk.Button(btn_frame, text="新規作成", command=new_server)
        new_btn.pack(side="top", pady=4, padx=4, fill=X)
        save_btn = ttk.Button(btn_frame, text="保存して追加", command=save_server)
        save_btn.pack(side="top", pady=4, padx=4, fill=X)
        del_btn = ttk.Button(btn_frame, text="削除", command=delete_server)
        del_btn.pack(side="top", pady=4, padx=4, fill=X)
        close_btn = ttk.Button(btn_frame, text="閉じる", command=dialog.destroy)
        close_btn.pack(side="top", pady=4, padx=4, fill=X)
        _attach_tooltip(new_btn, "フォームをクリアして新規サーバー入力モードにします。")
        _attach_tooltip(save_btn, "入力内容を保存します。未選択時は新規追加、選択時は更新します。")
        _attach_tooltip(del_btn, "選択中のサーバーを削除します。")
        _attach_tooltip(close_btn, "サーバー管理を閉じます。")
        try:
            del_btn.config(state="disabled")
        except Exception:
            pass
        try:
            if listbox.size() == 0:
                new_btn.config(state="disabled")
            else:
                new_btn.config(state="normal")
        except Exception:
            pass

        # Center the dialog over the parent window
        try:
            dialog.update_idletasks()
            dw = dialog.winfo_width()
            dh = dialog.winfo_height()
            px = self.winfo_rootx()
            py = self.winfo_rooty()
            pw = self.winfo_width()
            ph = self.winfo_height()
            if pw <= 1 and ph <= 1:
                sw = self.winfo_screenwidth()
                sh = self.winfo_screenheight()
                x = (sw - dw) // 2
                y = (sh - dh) // 2
            else:
                x = px + max(0, (pw - dw) // 2)
                y = py + max(0, (ph - dh) // 2)
            dialog.geometry(f"+{x}+{y}")
        except Exception:
            pass
        # wait until the dialog is closed, then refresh servers in main UI
        try:
            dialog.wait_window()
            try:
                self._load_servers_to_ui()
            except Exception:
                pass
        except Exception:
            pass

    def _on_search_changed(self, event=None) -> None:
        """Debounce search input and reload the list after a short delay."""
        try:
            if getattr(self, "_search_after_id", None):
                try:
                    self.after_cancel(self._search_after_id)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            self._search_after_id = self.after(250, self.reload_tree)
        except Exception:
            # fallback: immediate
            try:
                self.reload_tree()
            except Exception:
                pass

    def _on_tree_select(self, event=None) -> None:
        selection = self.tree.selection()
        if selection:
            self._select_row(selection[0])
        else:
            self._select_row("")

    def _select_row(self, file_path: str) -> None:
        self.selected_file_path = file_path or None
        self._render_db_text(self._filter_rows_for_selected_server(self.database.list_plugins()))

    def _get_selected_row(self) -> sqlite3.Row | None:
        file_path = self.selected_file_path
        if not file_path:
            return None

        try:
            return self.database.get_plugin_by_path(file_path)
        except Exception:
            return None

    def _selected_row_or_warn(self) -> sqlite3.Row | None:
        row = self._get_selected_row()
        if row is None:
            messagebox.showinfo("対象なし", "先に一覧のプラグインを1件選択してください。")
        return row

    def _is_match_failure(self, row: sqlite3.Row) -> bool:
        last_error = str(row_get(row, "last_error") or "")
        return bool(last_error.strip())

    def _failed_match_rows(self) -> list[sqlite3.Row]:
        return [row for row in self._filter_rows_for_selected_server(self.database.list_plugins()) if self._is_match_failure(row)]

    def _prompt_modrinth_url(self, row: sqlite3.Row, title: str) -> str | None:
        current = str(row_get(row, "source_id") or "")
        return simpledialog.askstring(
            title,
            "配布元の URL または project ref を入力してください。SpigotMC は resource ID でも可です。",
            initialvalue=current,
            parent=self,
        )

    def _refresh_match_for_file(self, file_path: str) -> None:
        row = self.database.get_plugin_by_path(file_path)
        if row is None:
            return
        result = self._resolve_entry_update(row)
        self.database.update_plugin_remote(
            file_path=file_path,
            source_type=result["source_type"],
            source_id=result["source_id"],
            source_title=result["source_title"],
            latest_version=result["latest_version"],
            latest_version_id=result.get("version_id", ""),
            latest_download_url=result["latest_download_url"],
            update_available=result["update_available"],
            last_checked=result["last_checked"],
            last_error=result["last_error"],
        )
        self.reload_tree()

    def _apply_manual_match_url(self, row: sqlite3.Row, source_value: str) -> tuple[bool, str]:
        source_value = (source_value or "").strip()
        file_path = str(row_get(row, "file_path") or "")
        preferred_type = normalize_source_type(row_get(row, "source_type"))
        value_lower = source_value.lower()
        source_type = ""
        source_id = ""
        project_title = str(row_get(row, "plugin_name") or row_get(row, "source_title") or "")

        modrinth_id = extract_modrinth_project_id(source_value)
        hangar_ref = extract_hangar_project_ref(source_value)
        github_ref = extract_github_repo_ref(source_value)
        spiget_ref = extract_spiget_resource_id(source_value)

        if "modrinth.com" in value_lower or "api.modrinth.com" in value_lower or (preferred_type == "modrinth" and modrinth_id) or (modrinth_id and "/" not in source_value):
            source_type = "modrinth"
            source_id = modrinth_id
            try:
                project_info = http_json(MODRINTH_PROJECT_URL.format(project_id=modrinth_id))
                project_title = str(project_info.get("title") or project_info.get("slug") or project_title or modrinth_id)
            except Exception:
                project_title = project_title or modrinth_id
        elif "hangar.papermc.io" in value_lower or (preferred_type == "hangar" and hangar_ref):
            source_type = "hangar"
            source_id = hangar_ref
            try:
                owner, slug = hangar_ref.split("/", 1)
                project_info = http_json(HANGAR_PROJECT_URL.format(owner=owner, slug=slug))
                namespace = project_info.get("namespace") or {}
                project_title = str(project_info.get("name") or namespace.get("slug") or project_title or hangar_ref)
            except Exception:
                project_title = project_title or hangar_ref
        elif "github.com" in value_lower or "api.github.com" in value_lower or (preferred_type == "github" and github_ref):
            source_type = "github"
            source_id = github_ref
            try:
                owner, repo = github_ref.split("/", 1)
                project_info = http_json(GITHUB_REPO_URL.format(owner=owner, repo=repo))
                project_title = str(project_info.get("full_name") or project_info.get("name") or project_title or github_ref)
            except Exception:
                project_title = project_title or github_ref
        elif preferred_type == "hangar" and hangar_ref:
            source_type = "hangar"
            source_id = hangar_ref
            try:
                owner, slug = hangar_ref.split("/", 1)
                project_info = http_json(HANGAR_PROJECT_URL.format(owner=owner, slug=slug))
                namespace = project_info.get("namespace") or {}
                project_title = str(project_info.get("name") or namespace.get("slug") or project_title or hangar_ref)
            except Exception:
                project_title = project_title or hangar_ref
        elif preferred_type == "github" and github_ref:
            source_type = "github"
            source_id = github_ref
            try:
                owner, repo = github_ref.split("/", 1)
                project_info = http_json(GITHUB_REPO_URL.format(owner=owner, repo=repo))
                project_title = str(project_info.get("full_name") or project_info.get("name") or project_title or github_ref)
            except Exception:
                project_title = project_title or github_ref
        elif "spigotmc.org" in value_lower or "spiget.org" in value_lower or (preferred_type == "spiget" and spiget_ref) or (spiget_ref and re.fullmatch(r"\d+", source_value)):
            source_type = "spiget"
            source_id = spiget_ref
            try:
                res = http_json(SPIGET_RESOURCE_URL.format(id=spiget_ref))
                project_title = str(res.get("name") or res.get("title") or project_title or spiget_ref)
            except Exception:
                project_title = project_title or spiget_ref
        elif modrinth_id and ("modrinth.com" in value_lower or "api.modrinth.com" in value_lower or "/" not in source_value):
            source_type = "modrinth"
            source_id = modrinth_id
            try:
                project_info = http_json(MODRINTH_PROJECT_URL.format(project_id=modrinth_id))
                project_title = str(project_info.get("title") or project_info.get("slug") or project_title or modrinth_id)
            except Exception:
                project_title = project_title or modrinth_id
        elif hangar_ref:
            source_type = "hangar"
            source_id = hangar_ref
            try:
                owner, slug = hangar_ref.split("/", 1)
                project_info = http_json(HANGAR_PROJECT_URL.format(owner=owner, slug=slug))
                namespace = project_info.get("namespace") or {}
                project_title = str(project_info.get("name") or namespace.get("slug") or project_title or hangar_ref)
            except Exception:
                project_title = project_title or hangar_ref
        elif github_ref:
            source_type = "github"
            source_id = github_ref
            try:
                owner, repo = github_ref.split("/", 1)
                project_info = http_json(GITHUB_REPO_URL.format(owner=owner, repo=repo))
                project_title = str(project_info.get("full_name") or project_info.get("name") or project_title or github_ref)
            except Exception:
                project_title = project_title or github_ref
        else:
            return False, "Modrinth / Hangar / GitHub / SpigotMC の project URL または project ref を入力してください。"

        if not file_path:
            return False, "対象プラグインのファイルパスが取得できませんでした。"

        conn = self.database.server_connection
        if not conn:
            return False, "サーバーが選択されていません。"

        with conn:
            conn.execute(
                """
                UPDATE plugins
                SET source_type = ?, source_id = ?, source_title = ?, last_error = ?, updated_at = ?
                WHERE file_path = ?
                """,
                (
                    source_type,
                    source_id,
                    project_title,
                    "",
                    now_iso(),
                    file_path,
                ),
            )

        self._log(f"URLを設定しました: {row_get(row, 'plugin_name')} -> {project_title}")
        self._refresh_match_for_file(file_path)
        return True, f"{row_get(row, 'plugin_name')} -> {project_title}"

    def _show_failed_match_dialog(self, failed_rows: list[sqlite3.Row]) -> None:
        if not failed_rows:
            return

        dialog = tk.Toplevel(self)
        dialog.title("マッチング失敗一覧")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("1120x680")
        dialog.minsize(1000, 600)
        dialog.resizable(True, True)

        frame = ttk.Frame(dialog, padding=8)
        frame.pack(fill=BOTH, expand=True)

        ttk.Label(frame, text="自動マッチングに失敗したプラグインです。選択して URL を追加するか、そのまま閉じてスキップしてください。").pack(fill=X, pady=(0, 8))

        cols = ("plugin_name", "current_version", "source_title", "last_error")
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        headings = {
            "plugin_name": "プラグイン",
            "current_version": "現在の版",
            "source_title": "候補/URL",
            "last_error": "失敗理由",
        }
        widths = {"plugin_name": 260, "current_version": 120, "source_title": 320, "last_error": 240}
        for column in cols:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w")

        failed_by_iid: dict[str, sqlite3.Row] = {}

        def refresh_failed_list(select_first: bool = False) -> list[sqlite3.Row]:
            current_failed_rows = self._failed_match_rows()
            tree.delete(*tree.get_children())
            failed_by_iid.clear()

            for index, row in enumerate(current_failed_rows):
                iid = f"failed_{index}"
                failed_by_iid[iid] = row
                tree.insert(
                    "",
                    END,
                    iid=iid,
                    values=(
                        str(row_get(row, "plugin_name") or ""),
                        str(row_get(row, "current_version") or ""),
                        str(row_get(row, "source_id") or row_get(row, "source_title") or ""),
                        str(row_get(row, "last_error") or ""),
                    ),
                )

            if select_first and current_failed_rows:
                first_iid = next(iter(failed_by_iid), None)
                if first_iid:
                    try:
                        tree.selection_set(first_iid)
                        tree.see(first_iid)
                    except Exception:
                        pass

            return current_failed_rows

        refresh_failed_list()

        tree.pack(fill=BOTH, expand=True, side=LEFT)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        tree.configure(yscrollcommand=scrollbar.set)
        _attach_tooltip(tree, "自動マッチに失敗した項目一覧です。対象を選んでURLを設定できます。")

        def current_row() -> sqlite3.Row | None:
            selection = tree.selection()
            if not selection:
                return None
            return failed_by_iid.get(selection[0])

        actions = ttk.Frame(dialog, padding=(8, 0, 8, 8))
        actions.pack(fill=X)

        def add_or_change_url() -> None:
            row = current_row()
            if row is None:
                messagebox.showinfo("対象なし", "先に1件選択してください。")
                return
            value = self._prompt_modrinth_url(row, "マッチ先URLを入力")
            if value is None:
                return
            ok, result_message = self._apply_manual_match_url(row, value)
            if ok:
                messagebox.showinfo("手動マッチング成功", result_message, parent=dialog)
                remaining_failed_rows = refresh_failed_list(select_first=True)
                if not remaining_failed_rows:
                    dialog.destroy()
                    return
                self._log(f"まだ {len(remaining_failed_rows)} 件のマッチング失敗が残っています。")
            else:
                messagebox.showerror("手動マッチング失敗", result_message, parent=dialog)

        def skip_item() -> None:
            row = current_row()
            if row is None:
                messagebox.showinfo("対象なし", "先に1件選択してください。")
                return
            self._log(f"マッチングをスキップしました: {row_get(row, 'plugin_name')}")
            dialog.destroy()

        def search_modrinth() -> None:
            row = current_row()
            if row is None:
                messagebox.showinfo("対象なし", "先に1件選択してください。")
                return
            plugin_name = str(row_get(row, "plugin_name") or "").strip()
            if not plugin_name:
                messagebox.showinfo("対象なし", "検索対象のプラグイン名がありません。")
                return
            query = urllib.parse.quote_plus(plugin_name)
            webbrowser.open(f"https://modrinth.com/plugins?q={query}")

        def search_google() -> None:
            row = current_row()
            if row is None:
                messagebox.showinfo("対象なし", "先に1件選択してください。")
                return
            plugin_name = str(row_get(row, "plugin_name") or "").strip()
            if not plugin_name:
                messagebox.showinfo("対象なし", "検索対象のプラグイン名がありません。")
                return
            query = urllib.parse.quote_plus(plugin_name)
            webbrowser.open(f"https://www.google.com/search?q={query}")

        def close_dialog() -> None:
            dialog.destroy()

        add_url_btn = ttk.Button(actions, text="URLを追加/変更", command=add_or_change_url)
        add_url_btn.pack(side=LEFT, padx=(0, 6))
        skip_btn = ttk.Button(actions, text="スキップ", command=skip_item)
        skip_btn.pack(side=LEFT, padx=(0, 6))
        modrinth_search_btn = ttk.Button(actions, text="Modrinthで検索", command=search_modrinth)
        modrinth_search_btn.pack(side=LEFT, padx=(0, 6))
        google_search_btn = ttk.Button(actions, text="Googleで検索", command=search_google)
        google_search_btn.pack(side=LEFT, padx=(0, 6))
        close_btn = ttk.Button(actions, text="閉じる", command=close_dialog)
        close_btn.pack(side=RIGHT)
        _attach_tooltip(add_url_btn, "選択中プラグインの取得元URLを追加または変更します。")
        _attach_tooltip(skip_btn, "選択中プラグインのマッチングを今回はスキップします。")
        _attach_tooltip(modrinth_search_btn, "選択中プラグイン名でModrinth検索を開きます。")
        _attach_tooltip(google_search_btn, "選択中プラグイン名でGoogle検索を開きます。")
        _attach_tooltip(close_btn, "このダイアログを閉じます。")

        def on_double_click(event=None):
            add_or_change_url()

        tree.bind("<Double-1>", on_double_click)
        self.wait_window(dialog)

    def _open_homepage_for_row(self, row: sqlite3.Row) -> None:
        source_type = normalize_source_type(row_get(row, "source_type"))
        source_id = str(row_get(row, "source_id") or "")
        latest_version_id = str(row_get(row, "latest_version_id") or "").strip()
        latest_version = str(row_get(row, "latest_version") or "").strip()
        if source_id.startswith("http://") or source_id.startswith("https://"):
            webbrowser.open(source_id)
            return
        if source_type == "modrinth" and source_id:
            proj = ensure_modrinth_project_id(source_id)
            if latest_version_id:
                webbrowser.open(MODRINTH_VERSION_PAGE_URL.format(project_id=proj, version_id=latest_version_id))
            else:
                webbrowser.open(MODRINTH_PROJECT_PAGE_URL.format(project_id=proj))
            return
        if source_type == "hangar" and source_id:
            project_ref = extract_hangar_project_ref(source_id)
            if project_ref:
                owner, slug = project_ref.split("/", 1)
                if latest_version_id:
                    webbrowser.open(HANGAR_VERSION_PAGE_URL.format(owner=owner, slug=slug, version_id=latest_version_id))
                else:
                    webbrowser.open(HANGAR_PROJECT_PAGE_URL.format(owner=owner, slug=slug))
                return
        if source_type == "github" and source_id:
            repo_ref = extract_github_repo_ref(source_id)
            if repo_ref:
                owner, repo = repo_ref.split("/", 1)
                if latest_version:
                    webbrowser.open(GITHUB_PROJECT_PAGE_URL.format(owner=owner, repo=repo) + f"/releases/tag/{urllib.parse.quote_plus(latest_version)}")
                else:
                    webbrowser.open(GITHUB_PROJECT_PAGE_URL.format(owner=owner, repo=repo))
                return
        if source_type == "spiget" and source_id:
            try:
                webbrowser.open(SPIGITMC_PROJECT_PAGE_URL.format(id=source_id))
                return
            except Exception:
                try:
                    webbrowser.open(SPIGET_PROJECT_PAGE_URL.format(id=source_id))
                    return
                except Exception:
                    pass

        source_title = str(row_get(row, "source_title") or "").strip()
        plugin_name = str(row_get(row, "plugin_name") or "").strip()
        query = urllib.parse.quote_plus(source_title or plugin_name)
        if query:
            webbrowser.open(f"https://modrinth.com/plugins?q={query}")
            return

        messagebox.showinfo("ホームページ", "このプラグインのホームページを特定できませんでした。")

    def _open_selected_homepage(self) -> None:
        row = self._selected_row_or_warn()
        if row is not None:
            self._open_homepage_for_row(row)

    def _add_plugin_from_source_url(self) -> None:
        if not self.database.server_connection:
            messagebox.showwarning("サーバー未選択", "サーバーが選択されていません。\n(サーバー管理から追加・選択してください)")
            return

        source_value = simpledialog.askstring(
            "配布元URLで追加",
            "配布元の URL または project ref を入力してください。SpigotMC は resource ID でも可です。",
            parent=self,
        )
        if source_value is None:
            return
        source_value = source_value.strip()
        if not source_value:
            return

        current_version = simpledialog.askstring(
            "現在の版",
            "すでに導入済みの版があれば入力してください。空欄なら未設定で追加します。",
            parent=self,
        )
        if current_version is None:
            return
        current_version = current_version.strip()

        temp_key = hashlib.sha1(f"{source_value}|{time.time_ns()}".encode("utf-8", errors="ignore")).hexdigest()
        file_path = f"manual://pending/{temp_key}"
        self.database.upsert_local_plugins(
            [
                PluginEntry(
                    plugin_name="手動追加",
                    current_version=current_version,
                    file_name="manual.jar",
                    file_path=file_path,
                )
            ]
        )

        row = self.database.get_plugin_by_path(file_path)
        if row is None:
            messagebox.showerror("追加失敗", "新規プラグインの登録に失敗しました。")
            return

        ok, result_message = self._apply_manual_match_url(row, source_value)
        if not ok:
            messagebox.showerror("手動マッチング失敗", result_message)
            self.database.delete_plugin_by_path(file_path)
            self.reload_tree()
            return

        resolved_row = self.database.get_plugin_by_path(file_path)
        if resolved_row is not None:
            resolved_title = str(row_get(resolved_row, "source_title") or row_get(resolved_row, "plugin_name") or "手動追加")
            resolved_file_name = f"{safe_filename(resolved_title)}.jar"
            update_available = int(row_get(resolved_row, "update_available") or 0)
            latest_download_url = str(row_get(resolved_row, "latest_download_url") or "")
            latest_version = str(row_get(resolved_row, "latest_version") or "")

            if not current_version and latest_download_url:
                update_available = 1
            elif current_version and latest_version:
                update_available = 1 if compare_versions(latest_version, current_version) > 0 else 0

            conn = self.database.server_connection
            if conn:
                with conn:
                    conn.execute(
                        """
                        UPDATE plugins
                        SET plugin_name = ?, file_name = ?, current_version = ?, update_available = ?, updated_at = ?
                        WHERE file_path = ?
                        """,
                        (
                            resolved_title,
                            resolved_file_name,
                            current_version,
                            update_available,
                            now_iso(),
                            file_path,
                        ),
                    )

        self.reload_tree()
        self._log(f"配布元URLで追加しました: {source_value}")
        messagebox.showinfo("手動マッチング成功", result_message)

    def _edit_selected_source_url(self) -> None:
        row = self._selected_row_or_warn()
        if row is None:
            return

        current_value = str(row_get(row, "source_id") or "")
        new_value = simpledialog.askstring(
            "URLを変更",
            "配布元の URL または project ref を入力してください。SpigotMC は resource ID でも可です。",
            initialvalue=current_value,
            parent=self,
        )
        if new_value is None:
            return

        ok, result_message = self._apply_manual_match_url(row, new_value)
        if not ok:
            messagebox.showerror("手動マッチング失敗", result_message)
            return
        messagebox.showinfo("手動マッチング成功", result_message)

    def show_failed_matches(self) -> None:
        failed_rows = self._failed_match_rows()
        if not failed_rows:
            messagebox.showinfo("失敗なし", "現在、マッチングに失敗したプラグインはありません。")
            return
        self._show_failed_match_dialog(failed_rows)

    def _delete_selected_plugin(self) -> None:
        row = self._selected_row_or_warn()
        if row is None:
            return

        plugin_name = str(row_get(row, "plugin_name") or "")
        file_path = str(row_get(row, "file_path") or "")
        if not messagebox.askyesno("削除確認", f"{plugin_name} を一覧から削除しますか?"):
            return

        try:
            self.database.delete_plugin_by_path(file_path)
            self.reload_tree()
            self._log(f"削除しました: {plugin_name}")
        except Exception as exc:
            messagebox.showerror("削除失敗", str(exc))

    def _export_plugins(self) -> None:
        rows = self._filter_rows_for_selected_server(self.database.list_plugins())
        if not rows:
            messagebox.showinfo("対象なし", "エクスポートするプラグインがありません。")
            return

        destination = filedialog.asksaveasfilename(
            title="エクスポート先を選択",
            defaultextension=".tsv",
            filetypes=[("TSV files", "*.tsv"), ("All files", "*.*")],
        )
        if not destination:
            return

        try:
            # UTF-16 + tab-separated values is reliably readable by Excel on Japanese Windows.
            with open(destination, "w", newline="", encoding="utf-16") as handle:
                writer = csv.writer(handle, delimiter="\t")
                writer.writerow(["プラグイン名", "現在の版", "最新", "最終確認", "取得元", "取得元URL", "ファイル名", "ファイルパス", "エラー"])
                for row in rows:
                    writer.writerow([
                        row_get(row, "plugin_name", ""),
                        row_get(row, "current_version", ""),
                        row_get(row, "latest_version", ""),
                        row_get(row, "last_checked", ""),
                        format_source_label(row_get(row, "source_type"), row_get(row, "source_title"), row_get(row, "source_id")),
                        build_source_url(row_get(row, "source_type"), row_get(row, "source_id")),
                        row_get(row, "file_name", ""),
                        row_get(row, "file_path", ""),
                        row_get(row, "last_error", ""),
                    ])
            self._log(f"リストを書き出しました: {destination}")
        except Exception as exc:
            messagebox.showerror("エクスポート失敗", str(exc))

    def _change_selected_version(self) -> None:
        row = self._selected_row_or_warn()
        if row is None:
            return

        dialog = __import__("tkinter").Toplevel(self)
        dialog.title("バージョンを変更")
        dialog.transient(self)
        dialog.grab_set()

        target_version = StringVar(value=str(row_get(row, "current_version") or ""))
        ttk.Label(dialog, text="新しいバージョンを入力してください:").pack(fill=X, padx=10, pady=(10, 4))
        version_entry = ttk.Entry(dialog, textvariable=target_version)
        version_entry.pack(fill=X, padx=10, pady=(0, 10))
        _attach_tooltip(version_entry, "設定するバージョン文字列を入力します。")

        def apply_version() -> None:
            new_version = target_version.get().strip()
            if not new_version:
                return
            conn = self.database.server_connection
            if not conn:
                return
            try:
                with conn:
                    conn.execute(
                        "UPDATE plugins SET current_version = ?, updated_at = ? WHERE file_path = ?",
                        (new_version, now_iso(), row_get(row, "file_path")),
                    )
                self.reload_tree()
                self._log(f"バージョンを変更しました: {row_get(row, 'plugin_name')} -> {new_version}")
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("変更失敗", str(exc))

        btns = ttk.Frame(dialog)
        btns.pack(fill=X, padx=10, pady=(0, 10))
        apply_btn = ttk.Button(btns, text="適用", command=apply_version)
        apply_btn.pack(side=RIGHT)
        cancel_btn = ttk.Button(btns, text="キャンセル", command=dialog.destroy)
        cancel_btn.pack(side=RIGHT, padx=(0, 8))
        _attach_tooltip(apply_btn, "入力したバージョンを選択中プラグインに適用します。")
        _attach_tooltip(cancel_btn, "変更せずに閉じます。")

    def _open_file_location(self) -> None:
        row = self._selected_row_or_warn()
        if row is None:
            return

        file_path = str(row_get(row, "file_path") or "")
        if not file_path or file_path.startswith("listing://"):
            messagebox.showinfo("対象なし", "この項目にはファイル場所がありません。")
            return

        path = Path(file_path)
        if not path.exists():
            messagebox.showinfo("対象なし", "ファイルが見つかりません。")
            return

        try:
            os.startfile(path.parent)
        except Exception as exc:
            messagebox.showerror("開く失敗", str(exc))

    def _poll_task_queue(self) -> None:
        handled = False
        while True:
            try:
                task_name, payload = self.task_queue.get_nowait()
            except queue.Empty:
                break

            handled = True
            if task_name == "check_updates_finished":
                self._finish_check_updates(payload)
            elif task_name == "manual_download_candidates_finished":
                self._finish_manual_download_candidates(payload)
            elif task_name == "download_updates_finished":
                self._finish_download_updates(payload)
            elif task_name == "icon_updated":
                # payload is key; refresh tree so icons update
                try:
                    if isinstance(payload, str):
                        self.icon_manager.memory.pop(payload, None)
                    self.reload_tree()
                except Exception:
                    pass
            elif task_name == "check_updates_progress":
                current, total, message = payload
                self._set_progress(current, total, message)
            elif task_name == "download_updates_progress":
                current, total, message = payload
                self._set_progress(current, total, message)

        if handled:
            self.update_idletasks()
        self.after(100, self._poll_task_queue)

    def _render_db_text(self, rows: list[sqlite3.Row]) -> None:
        self.db_count_text.set(f"DB件数: {len(rows)}")
        selected = self._get_selected_row()
        if selected is None and rows:
            selected = rows[0]

        if selected is None:
            lines = ["上の一覧からプラグインを選択してください。"]
        else:
            source = format_source_label(row_get(selected, "source_type"), row_get(selected, "source_title"), row_get(selected, "source_id"))
            latest_version = str(row_get(selected, "latest_version") or "-")
            current_version = str(row_get(selected, "current_version") or "-")
            last_checked = str(row_get(selected, "last_checked") or "-")
            file_path = str(row_get(selected, "file_path") or "")
            last_error = str(row_get(selected, "last_error") or "-")
            lines = [
                f"選択中: {row_get(selected, 'plugin_name', '')}",
                f"バージョン: {current_version}",
                f"最新: {latest_version}",
                f"更新日時: {last_checked}",
                f"提供元: {source}",
                f"保存先/元パス: {file_path}",
                f"エラー: {last_error}",
            ]

        self.db_text.configure(state="normal")
        self.db_text.delete("1.0", END)
        self.db_text.insert("1.0", "\n".join(lines))
        self.db_text.configure(state="disabled")

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="プラグインフォルダを選択")
        if selected:
            self.plugin_folder.set(selected)
            try:
                sid = int(self.selected_server_id.get() or 0)
            except Exception:
                sid = 0
            if sid:
                srv = self.database.get_server(sid)
                name = str(row_get(srv, "name") or f"Server {sid}")
                try:
                    self.database.update_server(sid, name=name, server_version=self.server_version.get() or "", server_software=self.server_software.get() or "", plugin_folder=selected, modrinth_version_channel=self._get_modrinth_version_channel())
                except Exception:
                    self.database.set_setting("plugin_folder", selected)
            else:
                self.database.set_setting("plugin_folder", selected)
            self._log(f"フォルダを設定しました: {selected}")

    def load_listing_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="一覧テキストを選択",
            filetypes=[("Text files", "*.txt;*.log;*.csv;*.tsv"), ("All files", "*.*")],
        )
        if not file_path:
            return

        text = Path(file_path).read_text(encoding="utf-8", errors="replace")
        self.listing_text.delete("1.0", END)
        self.listing_text.insert("1.0", text)
        self._log(f"一覧ファイルを読み込みました: {file_path}")

    def import_plugins_from_tsv(self) -> None:
        if not self.database.server_connection:
            messagebox.showwarning("サーバー未選択", "サーバーが選択されていません。\n(サーバー管理から追加・選択してください)")
            return

        file_path = filedialog.askopenfilename(
            title="TSVファイルを選択",
            filetypes=[("TSV files", "*.tsv"), ("Text files", "*.txt;*.log;*.csv"), ("All files", "*.*")],
        )
        if not file_path:
            return

        text = None
        for enc in ("utf-16", "utf-8-sig", "utf-8"):
            try:
                text = Path(file_path).read_text(encoding=enc, errors="strict")
                break
            except Exception:
                continue
        if text is None:
            messagebox.showerror("取り込み失敗", "TSVの文字コードを判別できませんでした。")
            return

        try:
            reader = csv.DictReader(text.splitlines(), delimiter="\t")
            rows = list(reader)
        except Exception as exc:
            messagebox.showerror("取り込み失敗", f"TSVの解析に失敗しました: {exc}")
            return

        if not rows:
            messagebox.showinfo("対象なし", "TSVに取り込めるデータがありません。")
            return

        entries: list[PluginEntry] = []
        source_urls: list[tuple[str, str]] = []
        skipped = 0

        for row in rows:
            plugin_name = str(row.get("プラグイン名") or "").strip()
            current_version = str(row.get("現在の版") or "").strip()
            file_name = str(row.get("ファイル名") or "").strip()
            file_path_value = str(row.get("ファイルパス") or "").strip()
            source_url = str(row.get("取得元URL") or "").strip()

            if not plugin_name and not file_name and not file_path_value:
                skipped += 1
                continue

            if not file_name:
                file_name = f"{safe_filename(plugin_name or 'plugin')}.jar"
            if not file_path_value:
                digest = hashlib.sha1(f"{plugin_name}|{file_name}|{source_url}".encode("utf-8", errors="ignore")).hexdigest()[:12]
                file_path_value = f"imported://{safe_filename(file_name)}-{digest}"

            entries.append(
                PluginEntry(
                    plugin_name=plugin_name or Path(file_name).stem,
                    current_version=current_version,
                    file_name=file_name,
                    file_path=file_path_value,
                )
            )
            if source_url:
                source_urls.append((file_path_value, source_url))

        if not entries:
            messagebox.showinfo("対象なし", "TSVに取り込める行がありません。")
            return

        self.database.upsert_local_plugins(entries)

        matched = 0
        failed = 0
        for fp, src in source_urls:
            target = self.database.get_plugin_by_path(fp)
            if target is None:
                failed += 1
                continue
            ok, _msg = self._apply_manual_match_url(target, src)
            if ok:
                matched += 1
            else:
                failed += 1

        self.reload_tree()
        summary = f"TSVから {len(entries)} 件取り込みました"
        if skipped:
            summary += f"（空行スキップ {skipped} 件）"
        if source_urls:
            summary += f"\n取得元URL適用: 成功 {matched} 件 / 失敗 {failed} 件"
        self._log(summary)
        messagebox.showinfo("取り込み完了", summary)

    def import_listing_text(self) -> None:
        if not self.database.server_connection:
            messagebox.showwarning("サーバー未選択", "サーバーが選択されていません。\n(サーバー管理から追加・選択してください)")
            return

        listing_text = self.listing_text.get("1.0", END).strip()
        if not listing_text:
            messagebox.showwarning("一覧が空です", "ls等の一覧テキストを貼り付けるか、ファイルから読込を行ってください。")
            return

        jar_names = extract_jar_names_from_listing(listing_text)
        if not jar_names:
            messagebox.showinfo("対象なし", ".jar ファイル名を見つけられませんでした。")
            return

        imported = self.database.upsert_imported_jars(jar_names)
        self.reload_tree()
        self._log(f"一覧から {imported}件の .jar をDBに登録しました。")
        messagebox.showinfo("取り込み完了", f"{imported}件の .jar をDBに登録しました。")

    def scan_folder(self) -> None:
        if not self.database.server_connection:
            messagebox.showwarning("サーバー未選択", "サーバーが選択されていません。\n(サーバー管理から追加・選択してください)")
            return

        folder_value = self.plugin_folder.get().strip()
        if not folder_value:
            messagebox.showwarning("フォルダ未設定", "プラグインフォルダを選択してください。")
            return

        folder = Path(folder_value)
        if not folder.exists():
            messagebox.showerror("フォルダが見つかりません", "指定されたプラグインフォルダが存在しません。")
            return

        self._set_busy("スキャン中")
        entries = scan_plugin_folder(folder)
        self.database.upsert_local_plugins(entries)
        try:
            sid = int(self.selected_server_id.get() or 0)
        except Exception:
            sid = 0
        if sid:
            srv = self.database.get_server(sid)
            name = str(row_get(srv, "name") or f"Server {sid}")
            try:
                self.database.update_server(sid, name=name, server_version=self.server_version.get() or "", server_software=self.server_software.get() or "", plugin_folder=str(folder.resolve()), modrinth_version_channel=self._get_modrinth_version_channel())
            except Exception:
                self.database.set_setting("plugin_folder", str(folder.resolve()))
        else:
            self.database.set_setting("plugin_folder", str(folder.resolve()))
        self.reload_tree()
        self._set_busy("待機中")
        self._log(f"{len(entries)}件のプラグインをデータベースに登録しました。")

    def reload_tree(self) -> None:
        # Debounce reloads to avoid interfering with fast scrolls or rapid events
        try:
            if getattr(self, "_reload_after_id", None):
                try:
                    self.after_cancel(self._reload_after_id)
                except Exception:
                    pass
            # schedule actual reload slightly later to batch rapid calls
            self._reload_after_id = self.after(120, self._do_reload_tree)
        except Exception:
            # fallback to immediate
            try:
                self._do_reload_tree()
            except Exception:
                pass

    def _do_reload_tree(self) -> None:
        # guard: avoid extremely frequent full rebuilds
        now = time.time()
        if now - getattr(self, "_last_reload_time", 0.0) < 0.05:
            return
        self._last_reload_time = now

        # use search text to filter rows when provided
        search = (self.search_text.get() or "").strip() if getattr(self, "search_text", None) is not None else ""
        rows = self._filter_rows_for_selected_server(self.database.list_plugins_search(search))

        self.tree.delete(*self.tree.get_children())
        self.row_index = {str(row["file_path"]): row for row in rows}

        for index, row in enumerate(rows, start=1):
            source = format_source_label(row_get(row, "source_type"), row_get(row, "source_title"), row_get(row, "source_id"))

            img = None
            try:
                img = self.icon_manager.get_icon_for_row(row)
            except Exception:
                img = None

            file_path = str(row["file_path"] or "")

            try:
                self.tree.insert(
                    "",
                    END,
                    iid=file_path,
                    text=" ",
                    image=img if img else "",
                    values=(
                        str(row["plugin_name"] or ""),
                        str(row["current_version"] or ""),
                        str(row["last_checked"] or ""),
                        source
                    )
                )
            except Exception as e:
                self._log(f"Failed to insert row {file_path}: {e}")

        if self.selected_file_path and self.tree.exists(self.selected_file_path):
            try:
                self.tree.selection_set(self.selected_file_path)
                self.tree.see(self.selected_file_path)
            except Exception:
                pass

        self._render_db_text(rows)

    def _resolve_entry_update(self, row: sqlite3.Row) -> dict:
        current_version = row["current_version"] or ""
        source_type = normalize_source_type(row["source_type"])
        source_id = row["source_id"] or ""
        source_title = row["source_title"] or ""
        if source_type == "modrinth" and extract_spiget_resource_id(source_id) and ("spigotmc.org" in str(source_id).lower() or "spiget.org" in str(source_id).lower()):
            source_type = "spiget"
        latest_version = ""
        latest_download_url = ""
        resolved_title = source_title
        resolved_source_id = source_id
        resolved_source_type = source_type or "modrinth"
        server_version, server_software = self._get_server_context()
        try:
            pname = row_get(row, "plugin_name") or ""
            fpath = row_get(row, "file_path") or ""
        except Exception:
            pname = str(row.get("plugin_name", ""))
            fpath = str(row.get("file_path", ""))
        self._log(f"Resolve start: {pname} ({fpath}) -- stored source_type={row_get(row, 'source_type')} source_id={row_get(row, 'source_id')}")

        try:
            if resolved_source_type == "modrinth" and resolved_source_id:
                project_id = ensure_modrinth_project_id(resolved_source_id)
                self._log(f"Modrinth branch: resolved_source_id={resolved_source_id} -> project_id={project_id}")
                if not project_id:
                    return {
                        "source_type": resolved_source_type,
                        "source_id": resolved_source_id,
                        "source_title": resolved_title,
                        "latest_version": latest_version,
                        "latest_download_url": latest_download_url,
                        "update_available": 0,
                        "last_checked": now_iso(),
                        "last_error": "ModrinthのURLまたはproject idを解決できませんでした",
                    }
                resolved_source_id = project_id
                release = get_modrinth_release(
                    project_id,
                    server_version=server_version,
                    server_software=server_software,
                    version_channel=self._get_modrinth_version_channel(),
                    source_title=row_get(row, "plugin_name") or row_get(row, "file_name") or resolved_title or "",
                )
                if not release:
                    raise RuntimeError(
                        f"指定条件に対応するModrinth版が見つかりませんでした: {server_software or '自動'} / {server_version or '-'}"
                    )
            elif resolved_source_type == "hangar" and resolved_source_id:
                project_ref = extract_hangar_project_ref(resolved_source_id)
                self._log(f"Hangar branch: resolved_source_id={resolved_source_id} -> project_ref={project_ref}")
                if not project_ref:
                    return {
                        "source_type": resolved_source_type,
                        "source_id": resolved_source_id,
                        "source_title": resolved_title,
                        "latest_version": latest_version,
                        "latest_download_url": latest_download_url,
                        "update_available": 0,
                        "last_checked": now_iso(),
                        "last_error": "HangarのURLまたはproject refを解決できませんでした",
                    }
                resolved_source_id = project_ref
                release = get_hangar_release(project_ref, server_version=server_version, server_software=server_software)
                if not release:
                    raise RuntimeError(
                        f"指定条件に対応するHangar版が見つかりませんでした: {server_software or '自動'} / {server_version or '-'}"
                    )
            elif resolved_source_type == "github" and resolved_source_id:
                repo_ref = extract_github_repo_ref(resolved_source_id)
                self._log(f"GitHub branch: resolved_source_id={resolved_source_id} -> repo_ref={repo_ref}")
                if not repo_ref:
                    return {
                        "source_type": resolved_source_type,
                        "source_id": resolved_source_id,
                        "source_title": resolved_title,
                        "latest_version": latest_version,
                        "latest_download_url": latest_download_url,
                        "update_available": 0,
                        "last_checked": now_iso(),
                        "last_error": "GitHubのURLまたはrepo refを解決できませんでした",
                    }
                resolved_source_id = repo_ref
                release = get_github_release(repo_ref, server_version=server_version, server_software=server_software)
                if not release:
                    raise RuntimeError(
                        f"指定条件に対応するGitHub Releaseが見つかりませんでした: {server_software or '自動'} / {server_version or '-'}"
                    )
            elif resolved_source_type == "spiget" and resolved_source_id:
                resource_id = extract_spiget_resource_id(resolved_source_id)
                self._log(f"Spiget branch: resolved_source_id={resolved_source_id} -> resource_id={resource_id}")
                if not resource_id:
                    return {
                        "source_type": resolved_source_type,
                        "source_id": resolved_source_id,
                        "source_title": resolved_title,
                        "latest_version": latest_version,
                        "latest_download_url": latest_download_url,
                        "update_available": 0,
                        "last_checked": now_iso(),
                        "last_error": "SpigetのURLまたはresource idを解決できませんでした",
                    }
                resolved_source_id = resource_id
                release = get_spiget_release(resource_id, server_version=server_version, server_software=server_software)
                if not release:
                    raise RuntimeError(
                        f"指定条件に対応するSpiget版が見つかりませんでした: {server_software or '自動'} / {server_version or '-'}"
                    )
            else:
                self._log(f"Fallback: searching Modrinth for '{row_get(row, 'plugin_name')}'")
                hit = search_modrinth_plugin(row["plugin_name"])
                if hit:
                    self._log(f"Fallback: Modrinth hit for '{row_get(row, 'plugin_name')}' -> {hit.get('project_id') or hit.get('slug') or hit.get('title')}" )
                else:
                    self._log(f"Fallback: Modrinth missed for '{row_get(row, 'plugin_name')}', trying Hangar")
                    hit = search_hangar_project(row["plugin_name"])
                    if hit:
                        self._log(f"Fallback: Hangar hit for '{row_get(row, 'plugin_name')}' -> {hit.get('source_id')}" )
                if hit:
                    if hit.get("source_type") == "hangar":
                        resolved_source_type = "hangar"
                        resolved_source_id = hit.get("source_id", "")
                        resolved_title = hit.get("source_title") or row["plugin_name"]
                        release = get_hangar_release(resolved_source_id, server_version=server_version, server_software=server_software)
                    else:
                        project_id = hit.get("project_id", "")
                        resolved_source_id = project_id
                        resolved_source_type = "modrinth"
                        resolved_title = hit.get("title") or hit.get("slug") or row["plugin_name"]
                        release = get_modrinth_release(
                            project_id,
                            server_version=server_version,
                            server_software=server_software,
                            version_channel=self._get_modrinth_version_channel(),
                            source_title=row_get(row, "plugin_name") or row_get(row, "file_name") or resolved_title or "",
                        )
                    if not release:
                        raise RuntimeError(
                            f"指定条件に対応する{resolved_source_type.capitalize()}版が見つかりませんでした: {server_software or '自動'} / {server_version or '-'}"
                        )
                else:
                    spiget_candidate = (
                        extract_spiget_resource_id(resolved_source_id)
                        or extract_spiget_resource_id(resolved_title)
                        or extract_spiget_resource_id(str(row_get(row, "plugin_name") or ""))
                    )
                    if spiget_candidate:
                        self._log(f"Fallback: spiget_candidate detected: {spiget_candidate}")
                        resolved_source_type = "spiget"
                        resolved_source_id = spiget_candidate
                        release = get_spiget_release(spiget_candidate, server_version=server_version, server_software=server_software)
                        if not release:
                            raise RuntimeError(
                                f"指定条件に対応するSpiget版が見つかりませんでした: {server_software or '自動'} / {server_version or '-'}"
                            )
                    else:
                        return {
                            "source_type": resolved_source_type,
                            "source_id": resolved_source_id,
                            "source_title": resolved_title,
                            "latest_version": latest_version,
                            "latest_download_url": latest_download_url,
                            "update_available": 0,
                            "last_checked": now_iso(),
                            "last_error": "配布サイト未対応または未検出",
                        }

            latest_version = release["version"]
            latest_download_url = release["download_url"]
            resolved_title = resolved_title or release["title"]
            self._log(f"Resolved: {row_get(row, 'plugin_name')} -> {resolved_source_type}:{resolved_source_id} @ {latest_version}")

            update_available = 0
            if current_version and latest_version:
                update_available = 1 if compare_versions(latest_version, current_version) > 0 else 0

            return {
                "source_type": resolved_source_type,
                "source_id": resolved_source_id,
                "source_title": resolved_title,
                "latest_version": latest_version,
                "latest_download_url": latest_download_url,
                "update_available": update_available,
                "last_checked": now_iso(),
                "last_error": "",
            }
        except Exception as exc:
            self._log(f"_resolve_entry_update exception for {row_get(row,'plugin_name')}: {exc}")
            return {
                "source_type": resolved_source_type,
                "source_id": resolved_source_id,
                "source_title": resolved_title,
                "latest_version": latest_version,
                "latest_download_url": latest_download_url,
                "update_available": 0,
                "last_checked": now_iso(),
                "last_error": f"{exc}",
            }

    def check_updates(self) -> None:
        rows = self._filter_rows_for_selected_server(self.database.list_plugins())
        if not rows:
            messagebox.showinfo("対象なし", "先にプラグインフォルダをスキャンするか手動追加してください。")
            return

        self._set_busy("更新確認中")
        self._set_progress(0, len(rows), f"更新確認中 0 / {len(rows)}")
        row_snapshots = [dict(row) for row in rows]

        def worker() -> None:
            results: list[dict] = []
            total = len(row_snapshots)
            # Use a thread pool to resolve multiple entries concurrently to reduce wall-clock time
            try:
                max_workers = int(self.concurrency_workers.get())
                if max_workers < 1:
                    max_workers = 1
            except Exception:
                max_workers = min(8, max(2, (os.cpu_count() or 2) * 2))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as exe:
                future_to_row = {exe.submit(self._resolve_entry_update, row): row for row in row_snapshots}
                completed = 0
                for fut in concurrent.futures.as_completed(future_to_row):
                    row = future_to_row[fut]
                    completed += 1
                    try:
                        res = fut.result()
                    except Exception as exc:
                        # Convert exceptions into a result with last_error so the UI can handle it
                        res = {
                            "source_type": "",
                            "source_id": "",
                            "source_title": "",
                            "latest_version": "",
                            "latest_download_url": "",
                            "update_available": 0,
                            "last_checked": now_iso(),
                            "last_error": str(exc),
                        }
                    results.append({"file_path": row["file_path"], "result": res})
                    # report progress as entries complete
                    self.task_queue.put(("check_updates_progress", (completed, total, f"更新確認中 {completed} / {total}: {row['plugin_name']}")))
            self.task_queue.put(("check_updates_finished", results))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_check_updates(self, results: list[dict]) -> None:
        updated_rows = 0
        updates_found: list[dict] = []
        failed_rows: list[sqlite3.Row] = []

        for item in results:
            result = item["result"]
            self.database.update_plugin_remote(
                file_path=item["file_path"],
                source_type=result["source_type"],
                source_id=result["source_id"],
                source_title=result["source_title"],
                latest_version=result["latest_version"],
                latest_version_id=result.get("version_id", ""),
                latest_download_url=result["latest_download_url"],
                update_available=result["update_available"],
                last_checked=result["last_checked"],
                last_error=result["last_error"],
            )
            updated_rows += 1
            if result["update_available"]:
                updates_found.append(item)

            if str(result.get("last_error") or "").strip():
                row = self.database.get_plugin_by_path(item["file_path"])
                if row is not None:
                    failed_rows.append(row)

        self.reload_tree()
        self._set_busy("待機中")
        self._reset_progress()
        self._log(f"{updated_rows}件の更新確認が完了しました。更新あり: {len(updates_found)}件")

        if failed_rows:
            self._show_failed_match_dialog(failed_rows)
            return

        if updates_found:
            prompt = f"{len(updates_found)}件の更新が見つかりました。一括ダウンロードしますか?"
            if messagebox.askyesno("一括ダウンロード", prompt):
                self.download_updates(updates_found)
        else:
            messagebox.showinfo("確認完了", "更新は見つかりませんでした。")

    def _choose_download_folder(self) -> Path | None:
        selected = filedialog.askdirectory(title="保存先フォルダを選択")
        if not selected:
            return None
        destination = Path(selected)
        destination.mkdir(parents=True, exist_ok=True)
        return destination

    def show_download_selector(self, rows: list[dict]) -> list[dict] | None:
        """Show a modal dialog allowing the user to pick which items to download.

        Returns a list of the selected row dicts, or None if cancelled.
        """
        dialog = __import__("tkinter").Toplevel(self)
        dialog.title("ダウンロード対象の選択")
        dialog.transient(self)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=8)
        frame.pack(fill=BOTH, expand=True)

        cols = ("selected", "plugin_name", "current_version", "latest_version", "source", "file_name")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=12)
        headings = {
            "selected": "",
            "plugin_name": "名前",
            "current_version": "現在の版",
            "latest_version": "最新",
            "source": "取得元",
            "file_name": "ファイル名",
        }
        widths = {"selected": 48, "plugin_name": 220, "current_version": 140, "latest_version": 140, "source": 160, "file_name": 260}
        for c in cols:
            tree.heading(c, text=headings[c])
            tree.column(c, width=widths[c], anchor=("center" if c == "selected" else "w"))

        tree.pack(fill=BOTH, expand=True, side=LEFT)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        vsb.pack(side=RIGHT, fill=Y)
        tree.configure(yscrollcommand=vsb.set)
        _attach_tooltip(tree, "ダウンロード対象一覧です。左端のチェックで対象を切り替えます。")

        # track selection state in a map: item_id -> bool
        item_map: dict[str, dict] = {}

        for idx, row in enumerate(rows):
            item_id = f"i{idx}"
            # normalize display fields (rows may be DB rows or {file_path, result})
            if isinstance(row, dict) and "result" in row:
                result = row_get(row, "result") or {}
                file_path = row_get(row, "file_path")
                try:
                    dbrow = self.database.get_plugin_by_path(file_path)
                except Exception:
                    dbrow = None

                plugin_name = dbrow["plugin_name"] if dbrow else (result.get("source_title") or file_path or "")
                current_version = dbrow["current_version"] if dbrow else ""
                latest_version = row_get(result, "latest_version") or ""
                source = format_source_label(row_get(result, "source_type"), row_get(result, "source_title"), row_get(result, "source_id"))
                file_name = dbrow["file_name"] if dbrow else (file_path or "")
            else:
                plugin_name = row_get(row, "plugin_name") or ""
                current_version = row_get(row, "current_version") or ""
                latest_version = row_get(row, "latest_version") or ""
                source = format_source_label(row_get(row, "source_type"), row_get(row, "source_title"), row_get(row, "source_id"))
                file_name = row_get(row, "file_name") or ""

            # default to selected (use checkbox glyph for clarity)
            item_map[item_id] = {"row": row, "sel": True}
            tree.insert("", END, iid=item_id, values=("☑", plugin_name, current_version or "-", latest_version or "-", source, file_name))

        def toggle_item(event):
            # toggle only when clicking in the selected column to avoid interfering with row selection
            col = tree.identify_column(event.x)
            if col != "#1":
                return
            iid = tree.identify_row(event.y)
            if not iid:
                return
            item = item_map.get(iid)
            if not item:
                return
            item["sel"] = not item["sel"]
            tree.set(iid, "selected", "☑" if item["sel"] else "☐")

        def select_all():
            for iid, data in item_map.items():
                data["sel"] = True
                tree.set(iid, "selected", "✓")

        def deselect_all():
            for iid, data in item_map.items():
                data["sel"] = False
                tree.set(iid, "selected", "")

        tree.bind("<Button-1>", toggle_item)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=X, pady=(8, 4))
        select_all_btn = ttk.Button(btn_frame, text="すべて選択", command=select_all)
        select_all_btn.pack(side=LEFT, padx=6)
        deselect_all_btn = ttk.Button(btn_frame, text="すべて解除", command=deselect_all)
        deselect_all_btn.pack(side=LEFT, padx=6)
        _attach_tooltip(select_all_btn, "一覧の全項目をダウンロード対象にします。")
        _attach_tooltip(deselect_all_btn, "一覧の全項目をダウンロード対象から外します。")
        def open_source_for_selected():
            iid = tree.focus()
            if not iid:
                messagebox.showinfo("選択なし", "先に一覧の項目を1つ選択してください。")
                return
            item = item_map.get(iid)
            if not item:
                messagebox.showinfo("選択なし", "先に一覧の項目を1つ選択してください。")
                return
            row = item.get("row")
            # try to resolve to DB row when possible
            if isinstance(row, dict) and "result" in row:
                result = row_get(row, "result") or {}
                file_path = row_get(row, "file_path")
                try:
                    dbrow = self.database.get_plugin_by_path(file_path)
                except Exception:
                    dbrow = None
                if dbrow is not None:
                    self._open_homepage_for_row(dbrow)
                    return
                source_type = row_get(result, "source_type") or ""
                source_id = row_get(result, "source_id") or ""
                source_title = row_get(result, "source_title") or ""
                plugin_name = source_title or file_path or ""
            else:
                dbrow = row
                source_type = row_get(dbrow, "source_type")
                source_id = row_get(dbrow, "source_id")
                source_title = row_get(dbrow, "source_title")
                plugin_name = row_get(dbrow, "plugin_name")

            try:
                # prefer opening a page for the specific version if available
                if isinstance(row, dict) and "result" in row:
                    result = row_get(row, "result") or {}
                    # Modrinth: open version page if we have project_id + version_id
                    if (result.get("project_id") or source_id) and result.get("version_id") and source_type == "modrinth":
                        proj = result.get("project_id") or source_id
                        webbrowser.open(MODRINTH_VERSION_PAGE_URL.format(project_id=proj, version_id=result.get("version_id")))
                        return
                    # Hangar: owner/slug and version_id
                    if result.get("project_id") and result.get("version_id") and source_type == "hangar":
                        ref = result.get("project_id")
                        if "/" in ref:
                            owner, slug = ref.split("/", 1)
                            webbrowser.open(HANGAR_VERSION_PAGE_URL.format(owner=owner, slug=slug, version_id=result.get("version_id")))
                            return
                    # GitHub: open release by tag if version (tag) available
                    if source_type == "github" and source_id and result.get("version"):
                        repo_ref = extract_github_repo_ref(source_id)
                        if repo_ref:
                            owner, repo = repo_ref.split("/", 1)
                            tag = str(result.get("version"))
                            webbrowser.open(GITHUB_PROJECT_PAGE_URL.format(owner=owner, repo=repo) + f"/releases/tag/{urllib.parse.quote_plus(tag)}")
                            return

                # fallback: open profile/project pages similar to existing behavior
                if source_type == "github" and source_id:
                    repo_ref = extract_github_repo_ref(source_id)
                    if repo_ref:
                        owner, repo = repo_ref.split("/", 1)
                        webbrowser.open(GITHUB_PROJECT_PAGE_URL.format(owner=owner, repo=repo))
                        return
                if source_type == "spiget" and source_id:
                    try:
                        webbrowser.open(SPIGITMC_PROJECT_PAGE_URL.format(id=source_id))
                        return
                    except Exception:
                        try:
                            webbrowser.open(SPIGET_PROJECT_PAGE_URL.format(id=source_id))
                            return
                        except Exception:
                            pass

                source_title_val = str(source_title or plugin_name or "").strip()
                query = urllib.parse.quote_plus(source_title_val)
                if query:
                    webbrowser.open(f"https://modrinth.com/plugins?q={query}")
                    return
            except Exception:
                pass

            messagebox.showinfo("ホームページ", "このプラグインのホームページを特定できませんでした。")

        open_src_btn = ttk.Button(btn_frame, text="取得元を開く", command=open_source_for_selected)
        open_src_btn.pack(side=RIGHT, padx=6)
        Tooltip(open_src_btn, "選択中の項目の取得元ページをブラウザで開きます")
        result: list[dict] | None = None

        def on_ok():
            nonlocal result
            chosen = [data["row"] for iid, data in item_map.items() if data["sel"]]
            result = chosen
            dialog.destroy()

        def on_cancel():
            nonlocal result
            result = None
            dialog.destroy()

        ok_btn = ttk.Button(btn_frame, text="OK", command=on_ok)
        ok_btn.pack(side=RIGHT, padx=6)
        cancel_btn = ttk.Button(btn_frame, text="キャンセル", command=on_cancel)
        cancel_btn.pack(side=RIGHT)
        _attach_tooltip(ok_btn, "チェックされた項目でダウンロードを続行します。")
        _attach_tooltip(cancel_btn, "ダウンロード選択を取り消して閉じます。")

        # wait for the dialog to close
        self.wait_window(dialog)
        return result

    def download_updates_manually(self) -> None:
        rows = self._filter_rows_for_selected_server(self.database.list_plugins())
        if not rows:
            messagebox.showinfo("対象なし", "ダウンロード対象の更新がありません。先に更新確認を実行してください。")
            return

        self._set_busy("ダウンロード候補を確認中")
        self._set_progress(0, len(rows), f"ダウンロード候補を確認中 0 / {len(rows)}")
        row_snapshots = [dict(row) for row in rows]

        def worker() -> None:
            results: list[dict] = []
            total = len(row_snapshots)
            for index, row in enumerate(row_snapshots, start=1):
                result = self._resolve_entry_update(row)
                if result.get("update_available"):
                    results.append({"file_path": row["file_path"], "result": result})
                self.task_queue.put(("download_updates_progress", (index, total, f"ダウンロード候補を確認中 {index} / {total}: {row['plugin_name']}")))
            self.task_queue.put(("manual_download_candidates_finished", results))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_manual_download_candidates(self, rows: list[dict]) -> None:
        self._set_busy("待機中")
        self._reset_progress()
        if not rows:
            messagebox.showinfo("対象なし", "ダウンロード対象の更新がありません。先に更新確認を実行してください。")
            return
        self.download_updates(rows)

    def download_updates(self, rows: list[sqlite3.Row]) -> None:
        # show selector dialog first
        row_snapshots = [dict(row) for row in rows]
        selected = self.show_download_selector(row_snapshots)
        if selected is None:
            self._log("ダウンロードをキャンセルしました。")
            return
        if not selected:
            messagebox.showinfo("対象なし", "ダウンロード対象が選択されませんでした。")
            return

        destination = self._choose_download_folder()
        if destination is None:
            return

        # normalize selected items into snapshots with required download fields
        normalized: list[dict] = []
        for sel in selected:
            if isinstance(sel, dict) and "result" in sel:
                result = row_get(sel, "result") or {}
                file_path = row_get(sel, "file_path")
                dbrow = None
                try:
                    dbrow = self.database.get_plugin_by_path(file_path)
                except Exception:
                    dbrow = None
                plugin_name = dbrow["plugin_name"] if dbrow else (row_get(result, "source_title") or file_path or "")
                file_name = dbrow["file_name"] if dbrow else (file_path or "")
                latest_download_url = row_get(result, "latest_download_url") or ""
                latest_version = row_get(result, "latest_version") or ""
                normalized.append({
                    "plugin_name": plugin_name,
                    "file_name": file_name,
                    "file_path": file_path,
                    "latest_download_url": latest_download_url,
                    "latest_version": latest_version,
                })
            else:
                # assume full DB-like dict
                normalized.append({
                    "plugin_name": row_get(sel, "plugin_name") or "",
                    "file_name": row_get(sel, "file_name") or "",
                    "file_path": row_get(sel, "file_path") or "",
                    "latest_download_url": row_get(sel, "latest_download_url") or "",
                    "latest_version": row_get(sel, "latest_version") or "",
                })

        self._set_busy("ダウンロード中")
        self._set_progress(0, len(normalized), f"ダウンロード中 0 / {len(normalized)}")
        row_snapshots = normalized

        def worker() -> None:
            results: list[dict] = []
            total = len(row_snapshots)
            for index, row in enumerate(row_snapshots, start=1):
                try:
                    if not row["latest_download_url"]:
                        raise RuntimeError("ダウンロードURLがありません")

                    version = row["latest_version"] or "latest"
                    suffix = Path(urllib.parse.urlparse(row["latest_download_url"]).path).suffix or ".jar"
                    target = destination / f"{safe_filename(row['plugin_name'])}-{safe_filename(version)}{suffix}"
                    counter = 1
                    while target.exists():
                        target = destination / f"{safe_filename(row['plugin_name'])}-{safe_filename(version)}-{counter}{suffix}"
                        counter += 1

                    download_file(row["latest_download_url"], target)
                    results.append({"ok": True, "plugin_name": row["plugin_name"], "file_name": target.name})
                except Exception as exc:
                    results.append({"ok": False, "plugin_name": row["plugin_name"], "error": str(exc)})

                self.task_queue.put(("download_updates_progress", (index, total, f"ダウンロード中 {index} / {total}: {row['plugin_name']}")))

            self.task_queue.put(("download_updates_finished", results))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_download_updates(self, results: list[dict]) -> None:
        downloaded = 0
        failed = 0
        for item in results:
            if item["ok"]:
                downloaded += 1
                self._log(f"ダウンロード完了: {item['file_name']}")
            else:
                failed += 1
                self._log(f"ダウンロード失敗: {item['plugin_name']} - {item['error']}")

        self._set_busy("待機中")
        self._reset_progress()
        self.reload_tree()
        messagebox.showinfo("完了", f"ダウンロード完了: {downloaded}件 / 失敗: {failed}件")


def main() -> None:
    app = PluginManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()