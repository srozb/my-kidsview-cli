import asyncio
from pathlib import Path

import respx
from httpx import Response

from kidsview_cli.config import Settings
from kidsview_cli.download import download_all, make_progress, sanitize_name, target_dir
from kidsview_cli.session import AuthTokens


def test_target_dir_sanitize() -> None:
    base = Path("x")
    name = "Foo / Bar"
    gid = "ID"
    assert target_dir(base, name, gid).name == "Foo _ Bar - ID"
    assert sanitize_name("  ") == "gallery"


@respx.mock
def test_download_all_skips_existing(tmp_path: Path) -> None:
    settings = Settings()
    tokens = AuthTokens(id_token="id", access_token="acc", refresh_token=None)
    galleries = [
        {"id": "g1", "name": "G1", "paginatedImages": {"edges": []}},
        {
            "id": "g2",
            "name": "G2",
            "paginatedImages": {
                "edges": [
                    {"node": {"imageUrl": "https://example.com/img1.jpg"}},
                    {"node": {"imageUrl": "https://example.com/img2.jpg"}},
                ]
            },
        },
    ]

    # Make existing dir to trigger skip.
    existing = target_dir(tmp_path, "G1", "g1")
    existing.mkdir(parents=True, exist_ok=True)

    respx.get("https://example.com/img1.jpg").mock(return_value=Response(200, content=b"1"))
    respx.get("https://example.com/img2.jpg").mock(return_value=Response(200, content=b"2"))

    with make_progress() as progress:
        downloaded = asyncio.run(
            download_all(
                settings=settings,
                tokens=tokens,
                context=None,
                gallery_ids=[],
                output_dir=tmp_path,
                skip_downloaded=True,
                galleries=galleries,
                progress=progress,
                concurrency=2,
            )
        )

    # g1 skipped, g2 downloaded
    assert len(downloaded) == 1
    g2_dir = target_dir(tmp_path, "G2", "g2")
    assert g2_dir.exists()
    files = sorted(p.name for p in g2_dir.iterdir())
    assert files == ["001.jpg", "002.jpg"]
