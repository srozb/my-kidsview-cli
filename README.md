# kidsview-cli

Polski CLI do platformy Kidsview (obecności, oceny, posiłki, czesne, kalendarz, wiadomości) przeznaczony dla ludzi i automatyzacji (np. Home Assistant, MQTT).

## Szybki start
1. Wymagania: Python 3.11+, `uv` zainstalowany globalnie.
2. Instalacja zależności: `uv sync`.
3. Uruchom pomoc: `uv run kidsview-cli --help` (alias: `uv run kv-cli --help`).
4. Podstawowe logowanie: `uv run kidsview-cli login` (zapisze tokeny w `~/.config/kidsview-cli/session.json`).

## Konfiguracja uwierzytelniania
- Region: `eu-west-1`
- User Pool ID: `eu-west-1_PZZVGIN20`
- ClientId: `4k8c50cn6ri9hk6197p9bnl0g4`

Wartości domyślne są wpisane w `Settings`. W razie zmian nadpisz zmiennymi środowiskowymi, np. `KIDSVIEW_USER_POOL_ID`.

## Użycie CLI (wybrane komendy)
- Ogólne zapytanie GraphQL:
  `uv run kidsview-cli graphql --query 'query { __typename }'`
  lub z własnego pliku: `uv run kidsview-cli graphql --query @sciezka/do/pliku.graphql --vars '{"first":5}'`
- Ogłoszenia: `uv run kidsview-cli announcements --first 10`
- Rachunki miesięczne: `uv run kidsview-cli monthly-bills --year WWVhck5vZGU6MjM4OA== --is-paid true`
- Galerie: `uv run kidsview-cli galleries --first 3`
- Pobierz galerie: `uv run kidsview-cli gallery-download --all --output-dir galleries` lub `--ids g1,g2`
- Dziecko (skrót): `uv run kidsview-cli active-child`
- Dziecko (szczegóły + aktywności): `uv run kidsview-cli active-child --detailed --date-from 2025-11-23 --date-to 2025-11-28`
- Użytkownicy czatu: `uv run kidsview-cli chat-users`
- Szukaj w czacie: `uv run kidsview-cli chat-search --search olga`
- Wyślij wiadomość: `uv run kidsview-cli chat-send --recipients S2lkc1ZpZXdCYXNlVXNlck5vZGU6Nzc5MzI= --text "🦄"`
- Profil (me): `uv run kidsview-cli me`
- Kolory placówek: `uv run kidsview-cli colors`
- Liczniki nieprzeczytanych: `uv run kidsview-cli unread`
- Dieta dziecka: `uv run kidsview-cli meals`
- Wnioski (applications): `uv run kidsview-cli applications --phrase "" --status ""`
- Powiadomienia (notifications): `uv run kidsview-cli notifications --first 20 --pending true`
- Kalendarz: `uv run kidsview-cli calendar --date-from 2025-11-01 --date-to 2025-11-30 --activity-types 0,1,5,9`
- Obserwacje zajęć dodatkowych: `uv run kidsview-cli observations --child-id <id_dziecka>`

## Kontekst cookies i tokeny
- Niektóre zapytania wymagają kontekstu dziecka/grupy. Dodaj ciasteczka:
  `KIDSVIEW_COOKIES="active_child=...; active_year=...; preschool=...; locale=pl" uv run kidsview-cli ...`
- Domyślnie nagłówek `Authorization: JWT <id_token>`. Aby wymusić access token:
  `KIDSVIEW_AUTH_TOKEN_PREFERENCE=access uv run kidsview-cli ...`

## Użycie programistyczne (jako moduł)
```python
import asyncio
from kidsview_cli import Settings, AuthClient, GraphQLClient, SessionStore, queries

settings = Settings()
store = SessionStore(settings.session_file)
tokens = store.load() or asyncio.run(AuthClient(settings).login("email", "haslo"))
client = GraphQLClient(settings, tokens)
data = asyncio.run(client.execute(queries.ANNOUNCEMENTS, {"first": 5}))
print(data)
```
Możesz wykorzystać `GraphQLClient` i modele w innych projektach (np. publikacja wyników do MQTT dla Home Assistant).

## Instalacja globalna (uv tool)
- Z tagu releasu: `uv tool install git+https://github.com/USER/kidsview-cli.git@v0.1.0`
- Dostępne entrypointy: `kidsview-cli` i krótszy alias `kv-cli`.

## Testy i jakość
- Testy: `uv run pytest`
- Lint/format: `uv run ruff check --fix && uv run ruff format`
- Pre-commit (ruff, format, pytest, mypy): `pre-commit run --all-files`

## Dev tooling
- Install dev deps: `uv sync --extra dev`
- Run tests: `uv run pytest`
- Lint/format: `uv run ruff check --fix && uv run ruff format`
