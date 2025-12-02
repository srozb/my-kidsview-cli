from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from .. import queries
from ..download import download_all, fetch_galleries, make_progress
from ..helpers import (
    console,
    run_query_table,
)
from ..helpers import env as _env
from ..helpers import execute_graphql as _execute_graphql
from ..helpers import fetch_me as _fetch_me
from ..helpers import (
    prompt_multi_choice as _prompt_multi_choice,
)
from ..helpers import run as _run


def register_galleries(app: typer.Typer) -> None:  # noqa: PLR0915
    @app.command()
    def galleries(  # noqa: PLR0913
        group_id: str | None = typer.Option(None, help="Group ID filter."),
        first: int = typer.Option(3, help="Items to fetch."),
        after: str | None = typer.Option(None, help="Cursor for pagination."),
        search: str = typer.Option("", help="Search phrase."),
        order: str | None = typer.Option(None, help="Order string."),
        json_output: bool = typer.Option(False, "--json/--no-json"),
    ) -> None:
        """Fetch galleries."""
        variables: dict[str, object] = {
            "groupId": group_id,
            "first": first,
            "after": after,
            "search": search,
            "order": order,
        }
        headers = ["ID", "Name", "Created", "Images"]
        run_query_table(
            query=queries.GALLERIES,
            variables=variables,
            label="galleries",
            json_output=json_output,
            empty_msg="No galleries.",
            headers=headers,
            title="🖼️ Galleries",
            rows_fn=lambda payload: [
                [
                    str((item.get("node") or {}).get("id", "")),
                    str((item.get("node") or {}).get("name", "")),
                    str((item.get("node") or {}).get("created", "")),
                    str((item.get("node") or {}).get("imagesCount", "")),
                ]
                for item in (payload.get("galleries") or {}).get("edges") or []
            ],
            show_lines=True,
        )

    @app.command()
    def gallery_download(  # noqa: B008
        ids: str = typer.Option("", "--id", "--ids", help="Comma-separated gallery IDs."),
        all_: bool = typer.Option(
            False, "--all", help="Download all galleries not yet downloaded."
        ),
        output_dir: Path | None = typer.Option(  # noqa: B008
            None,
            help="Output dir (default KIDSVIEW_DOWNLOAD_DIR or ~/Pictures/Kidsview).",
        ),
    ) -> None:
        """Download gallery images."""
        settings, tokens, context = _env()

        # Resolve child name for subdirectory (if context has child_id)
        child_name: str | None = None
        if context and context.child_id:
            try:
                me_data = _fetch_me(settings, tokens, context)
                me_obj = me_data.get("me") or {}
                for child in me_obj.get("children") or []:
                    if str(child.get("id")) == context.child_id:
                        child_name = (
                            f"{child.get('name','')} {child.get('surname','')}".strip() or None
                        )
                        break
            except Exception:
                child_name = None
            if not child_name:
                child_name = context.child_id

        dest_base = output_dir or settings.download_dir
        dest = Path(dest_base).expanduser()
        dest.mkdir(parents=True, exist_ok=True)

        id_list = [i.strip() for i in ids.split(",") if i.strip()]
        galleries_cache: list[dict[str, Any]] | None = None
        if not all_ and not id_list:
            try:
                galleries_cache = _run(
                    fetch_galleries(settings=settings, tokens=tokens, context=context)
                )
            except Exception as exc:  # pragma: no cover - network errors
                console.print(f"[red]Failed to list galleries:[/red] {exc}")
                raise typer.Exit(code=1) from exc
            if not galleries_cache:
                console.print("[red]No galleries available to choose.[/red]")
                raise typer.Exit(code=1)
            id_list = _prompt_multi_choice(galleries_cache, "Select galleries", "name")
            if not id_list:
                console.print("[red]No galleries selected.[/red]")
                raise typer.Exit(code=1)

        try:
            with make_progress() as progress:
                downloaded = _run(
                    download_all(
                        settings=settings,
                        tokens=tokens,
                        context=context,
                        gallery_ids=id_list,
                        output_dir=dest,
                        skip_downloaded=all_,
                        galleries=galleries_cache,
                        progress=progress,
                        concurrency=4,
                        child_name=child_name,
                    )
                )
        except Exception as exc:  # pragma: no cover - network/file errors
            console.print(f"[red]Download failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

        if not downloaded:
            console.print("No galleries downloaded (all already present?).")
            return

        console.print("Downloaded galleries:")
        for path in downloaded:
            console.print(f"- {path}")

    @app.command("gallery-like")
    def gallery_like(
        gallery_id: str = typer.Option(..., "--id", help="Gallery ID to like/unlike."),
        json_output: bool = typer.Option(False, "--json/--no-json"),
    ) -> None:
        """Toggle like for a gallery."""
        settings, tokens, context = _env()
        data = _execute_graphql(
            settings,
            tokens,
            queries.SET_GALLERY_LIKE,
            {"galleryId": gallery_id},
            context,
            label="setGalleryLike",
        )
        if json_output:
            console.print_json(data=data)
        else:
            result = (data.get("setGalleryLike") or {}).get("isLiked")
            console.print(f"[green]Gallery like toggled. isLiked={result}[/green]")

    @app.command("gallery-comment")
    def gallery_comment(
        gallery_id: str = typer.Option(..., "--id", help="Gallery ID."),
        content: str = typer.Option(..., "--content", prompt=True, help="Comment text."),
        json_output: bool = typer.Option(False, "--json/--no-json"),
    ) -> None:
        """Add comment to a gallery."""
        settings, tokens, context = _env()
        data = _execute_graphql(
            settings,
            tokens,
            queries.CREATE_GALLERY_COMMENT,
            {"galleryId": gallery_id, "content": content},
            context,
            label="createGalleryComment",
        )
        if json_output:
            console.print_json(data=data)
        else:
            errors = (data.get("createGalleryComment") or {}).get("errors")
            if errors:
                console.print(f"[red]Error:[/red] {errors}")
            else:
                console.print("[green]Comment added.[/green]")
