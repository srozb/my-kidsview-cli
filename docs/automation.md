# Automatyzacje z Home Assistant i kidsview-cli

Krótki przewodnik, jak połączyć `kidsview-cli` z Home Assistant (HA), aby wygodnie budować automatyzacje – głównie wokół zdarzeń kalendarzowych i notyfikacji.

## Założenia wstępne
- Zainstaluj CLI jako narzędzie: `uv tool install .` (dostępne entrypointy: `kidsview-cli`, `kv-cli`).
- Ustaw kontekst: `kv-cli context --auto` (CLI sam wybierze placówkę/dziecko/rok; w razie wielu opcji uruchomi tryb interaktywny Rich).
- Sprawdź sesję i tokeny: `kv-cli session` lub `kv-cli refresh` (odświeża token przy błędach 401/403).

## Wyciąganie zdarzeń do HA
### 1) Powiadomienia → kalendarz HA
- Pobierz świeże powiadomienia o wydarzeniach:
  ```bash
  kv-cli notifications --type new_event --json
  ```
- Każdy rekord ma `relatedId` (ID wydarzenia) i pole `data`, które jest stringiem JSON z m.in. `date`. Parsuj je przez `fromjson`:
  ```bash
  kv-cli notifications --type new_event --json \
    | jq -r '
        .notifications.edges[].node
        | .data |= (try (fromjson // {}) catch {} )
        | "\(.relatedId) \(.data.date // "") \(.text)"
      '
  ```
- Publikacja do HA przez MQTT (przykład szablonu):
  ```bash
  kv-cli notifications --type new_event --json \
    | jq -c '
        .notifications.edges[].node
        | .data |= (try (fromjson // {}) catch {} )
        | {id:.relatedId, date:(.data.date // ""), text:.text}
      ' \
    | while read evt; do
        mosquitto_pub -h HA_HOST -t home/kidsview/notifications -m "$evt"
      done
  ```
  W HA skonfiguruj `mqtt` + automatyzację, która tworzy wpis kalendarza z payloadu (`id`, `date`, `text`).

#### Przykładowy pipeline MQTT dla wydarzeń (UPCOMING_EVENT)
```bash
# oznacza jako przeczytane (--mark-read) i bierze tylko nieprzeczytane
kv-cli notifications --type upcoming_event --json --only-unread --mark-read \
  | jq --arg child "$child_label" -c '
      .notifications.edges[]
      | .node as $n
      | ($n.data | fromjson) as $d
      | {
          id: $n.id,
          related_id: $n.relatedId,
          child: $child,
          raw_text: $n.text,
          date: $d.date,
          summary: ($child + " " + $n.text)
        }
    ' \
  | while read -r event_json; do
      mosquitto_pub -h "$MQTT_HOST" -u "$MQTT_USER" -P "$MQTT_PASS" -t "$MQTT_TOPIC" -m "$event_json"
    done
```

### 2) Kalendarz Kidsview → kalendarz HA
- Pobierz plan na dziś: `kv-cli calendar --today --json`
- Jutro: `kv-cli calendar --tomorrow --json`
- Dowolny zakres: `kv-cli calendar --from 2025-12-01 --to 2025-12-07 --json`
- W JSON znajdziesz `title`, `startDate`, `endDate`, `type` i opcjonalnie `absenceReportedBy.fullName`. Możesz podobnie jak wyżej wypchnąć to do HA (MQTT lub REST).

### 3) Snapshoty do plików
- Zapisz dane do lokalnego JSON (np. do dalszej obróbki w Node-RED/HA):
  ```bash
  kv-cli notifications --type new_event --json > /tmp/kidsview-notifications.json
  kv-cli calendar --today --json > /tmp/kidsview-calendar.json
  ```

## Harmonogram (cron/systemd)
Przykład crontaba tworzącego feed do HA co 30 minut:
```
*/30 * * * * KIDSVIEW_DEBUG=0 kv-cli notifications --type new_event --json \
  | jq -c '
      .notifications.edges[].node
      | .data |= (try (fromjson // {}) catch {} )
      | {id:.relatedId, date:(.data.date // ""), text:.text}
    ' \
  | xargs -I '{}' mosquitto_pub -h HA_HOST -t home/kidsview/notifications -m '{}'
```
Analogicznie dla kalendarza: `kv-cli calendar --today --json`.

### 4) Przykład automatyzacji HA → Google Calendar
Dodaj do `automations.yaml` (zmień `calendar.rodzinny` na swoją encję kalendarza):
```yaml
alias: Wydarzenia szkolne z MQTT do kalendarza
description: >
  Tworzy wydarzenia w Google Calendar na podstawie wiadomości z topicu school/events
triggers:
  - topic: school/events
    trigger: mqtt
conditions: []
actions:
  - target:
      entity_id: calendar.rodzinny
    data:
      summary: "{{ trigger.payload_json.summary }}"
      description: |
        Oryginalny tekst: {{ trigger.payload_json.raw_text }}

        ID powiadomienia: {{ trigger.payload_json.id }}
      start_date_time: |
        {{ trigger.payload_json.date | as_datetime + timedelta(hours=8) }}
      end_date_time: >
        {{ trigger.payload_json.date | as_datetime + timedelta(hours=8, minutes=30) }}
    action: google.create_event
mode: queued
max: 20
```

## Dobre praktyki
- Utrzymuj kontekst automatycznie (`kv-cli context --auto` po odświeżeniu tokenu).
- W automatyzacjach ustaw `--json`; w interaktywnym użyciu zostaw domyślny widok tabel.
- Włącz `KIDSVIEW_DEBUG=1` tylko do debugowania błędów (loguje surowe odpowiedzi GraphQL).
- Jeśli obsługujesz wielu użytkowników/środowisk, rozdziel katalog konfiguracyjny zmienną `KIDSVIEW_CONFIG_DIR`.

## Pomysły na kolejne integracje
- Publikacja liczników (`kv-cli unread --json`) do czujników HA (Sensor/MQTT).
- Automatyczne pobieranie galerii do `~/Pictures/Kidsview/…` i wyświetlanie ich w HA (Media Browser).
- Reaktywne akcje: gdy pojawi się `NEW_GALLERY` lub `UPCOMING_EVENT`, dodaj przypomnienie w HA, wyślij powiadomienie mobilne lub stwórz wpis w kalendarzu domowym.
