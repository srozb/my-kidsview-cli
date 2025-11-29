from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from .client import GraphQLClient
from .config import Settings
from .context import Context
from .queries import GALLERIES
from .session import AuthTokens


def sanitize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name or "gallery"


def target_dir(base: Path, name: str, gallery_id: str) -> Path:
    return base / f"{sanitize_name(name)} - {gallery_id}"


async def fetch_galleries(
    settings: Settings, tokens: AuthTokens, context: Context | None, first: int = 100
) -> list[dict[str, Any]]:
    client = GraphQLClient(settings, tokens, context=context)
    data = await client.execute(GALLERIES, {"first": first})
    galleries = data.get("galleries") or {}
    edges = galleries.get("edges") or []
    return [edge.get("node", {}) for edge in edges if isinstance(edge, dict)]


async def download_gallery(
    gallery: dict[str, Any],
    output_dir: Path,
    *,
    progress: Progress | None = None,
    concurrency: int = 4,
) -> Path:
    gid = str(gallery.get("id"))
    name = str(gallery.get("name", gid))
    images = ((gallery.get("paginatedImages") or {}).get("edges")) or []
    image_urls: list[str] = []
    for img in images:
        node = img.get("node", {})
        url = node.get("imageUrlFull") or node.get("imageUrl")
        if url:
            image_urls.append(str(url))

    target = target_dir(output_dir, name, gid)
    target.mkdir(parents=True, exist_ok=True)

    task_id: TaskID | None = None
    if progress:
        task_id = progress.add_task(f"[cyan]{sanitize_name(name)}[/cyan]", total=len(image_urls))

    async def fetch_one(
        idx: int, url: str, client: httpx.AsyncClient, sem: asyncio.Semaphore
    ) -> None:
        filename = target / f"{idx:03d}{Path(url).suffix or '.jpg'}"
        if filename.exists():
            if progress and task_id is not None:
                progress.advance(task_id)
            return
        async with sem:
            resp = await client.get(url)
            resp.raise_for_status()
            filename.write_bytes(resp.content)
        if progress and task_id is not None:
            progress.advance(task_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        sem = asyncio.Semaphore(concurrency)
        await asyncio.gather(
            *(fetch_one(idx, url, client, sem) for idx, url in enumerate(image_urls, start=1))
        )
    if progress and task_id is not None:
        progress.update(task_id, completed=len(image_urls))
    return target


async def download_all(  # noqa: PLR0913
    settings: Settings,
    tokens: AuthTokens,
    context: Context | None,
    gallery_ids: Iterable[str],
    output_dir: Path,
    skip_downloaded: bool = False,
    galleries: list[dict[str, Any]] | None = None,
    progress: Progress | None = None,
    concurrency: int = 4,
) -> list[Path]:
    all_galleries = galleries or await fetch_galleries(settings, tokens, context)
    if gallery_ids:
        wanted = set(gallery_ids)
        all_galleries = [g for g in all_galleries if str(g.get("id")) in wanted]

    downloaded: list[Path] = []
    for gal in all_galleries:
        gid = str(gal.get("id"))
        name = str(gal.get("name", gid))
        dest_dir = target_dir(output_dir, name, gid)
        if skip_downloaded and dest_dir.exists():
            continue
        dest = await download_gallery(gal, output_dir, progress=progress, concurrency=concurrency)
        downloaded.append(dest)
    return downloaded


def make_progress() -> Progress:
    return Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        transient=True,
    )
