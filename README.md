# kidsview-cli

Klient CLI platformy Kidsview (app.kidsview.pl). Stworzony z myślą o wygodnej obsłudzę z poziomu konsoli oraz skryptowaniu (mqtt).

## Szybki start
1. Wymagania: Python 3.11+, `uv` zainstalowany globalnie.
2. Instalacja zależności: `uv sync`.
3. Uruchom pomoc: `uv run kidsview-cli --help` (alias: `uv run kv-cli --help`).
4. Podstawowe logowanie: `uv run kidsview-cli login` (zapisze tokeny w `~/.config/kidsview-cli/session.json`).
5. Ustaw kontekst automatycznie (placówka/dziecko/rok → ciasteczka):
   `uv run kidsview-cli context --auto`
   Jeśli jest wiele opcji, CLI zapyta interaktywnie (Rich); pojedyncze wybiera automatycznie. Aby wymusić ponowny wybór mimo istniejącego kontekstu, użyj `--change`. Wybrane wartości zapisze do `~/.config/kidsview-cli/context.json` i będzie ich używać do budowy ciasteczek dla wszystkich zapytań.
6. Autouzupełnianie: `uv run kidsview-cli --install-completion` (bash/zsh/fish) — ułatwia pracę z wieloma flagami.

## Konfiguracja uwierzytelniania
- Region: `eu-west-1`
- User Pool ID: `eu-west-1_PZZVGIN20`
- ClientId: `4k8c50cn6ri9hk6197p9bnl0g4`

Wartości domyślne są wpisane w `Settings`. W razie zmian nadpisz zmiennymi środowiskowymi, np. `KIDSVIEW_USER_POOL_ID`.

## Użycie CLI (wybrane komendy)
| Komenda | Opis |
| --- | --- |
| `graphql --query ...` | Dowolne zapytanie GraphQL (inline lub `@plik.graphql`). |
| `announcements --first 10` | Ogłoszenia. |
| `monthly-bills --year ... --is-paid true` | Rachunki miesięczne. |
| `payments` / `payments-summary` / `payment-orders` | Historia płatności, podsumowanie, zlecenia płatności. |
| `galleries --first 3` | Lista galerii. |
| `gallery-download --all` / `--id g1,g2` | Pobieranie galerii (bez parametrów wybierzesz interaktywnie). |
| `gallery-like` / `gallery-comment` | Polubienie/komentarz galerii. |
| `active-child` / `active-child --detailed ...` | Skrót lub szczegóły dziecka. |
| `me` | Profil użytkownika, dzieci, placówki, lata. |
| `chat-users` / `chat-search` / `chat-send` | Użytkownicy czatu, wyszukiwanie, wysyłanie wiadomości. |
| `chat-threads` / `chat-messages` | Lista wątków i wiadomości w wątku. |
| `notifications` | Powiadomienia (filtry, mark-read, only-unread). |
| `applications` / `application-submit` | Lista wniosków, składanie wniosku. |
| `absence --date today` | Zgłoszenie nieobecności (domyślnie dziecko z kontekstu). |
| `meals` / `colors` / `unread` | Dieta, kolory placówek, liczniki nieprzeczytanych. |
| `quick-calendar` / `schedule` / `calendar` | Szybki kalendarz, plan grupy, kalendarz (obsługa `--week/--month/--days`). |
| `observations` | Obserwacje zajęć dodatkowych. |

## Kontekst cookies i tokeny
- CLI automatycznie buduje ciasteczka z kontekstu zapisanego w `~/.config/kidsview-cli/context.json` (ustaw `kidsview-cli context --auto` lub ręcznie podaj `--child-id/--preschool-id/--year-id`). Nie musisz ręcznie wklejać ciasteczek.
- Jeśli potrzebujesz nadpisać ciasteczka, możesz użyć `KIDSVIEW_COOKIES="active_child=...; active_year=...; preschool=...; locale=pl"` – wtedy CLI użyje ich zamiast kontekstu.
- Domyślnie nagłówek `Authorization: JWT <id_token>`. Aby wymusić access token:
  `KIDSVIEW_AUTH_TOKEN_PREFERENCE=access uv run kidsview-cli ...`
- Domyślny katalog pobierania galerii: `~/Pictures/Kidsview` (zmień przez `KIDSVIEW_DOWNLOAD_DIR` lub `--output-dir`).

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
- Z tagu releasu: `uv tool install git+https://github.com/USER/kidsview-cli.git@v0.3.0`
- Dostępne entrypointy: `kidsview-cli` i krótszy alias `kv-cli`.

## Testy i jakość
- Testy: `uv run pytest`
- Lint/format: `uv run ruff check --fix && uv run ruff format`
- Pre-commit (ruff, format, pytest, mypy): `pre-commit run --all-files`

## Dev tooling
- Install dev deps: `uv sync --extra dev`
- Run tests: `uv run pytest`
- Lint/format: `uv run ruff check --fix && uv run ruff format`
