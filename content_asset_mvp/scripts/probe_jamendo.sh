#!/usr/bin/env bash
# Quick smoke test for Jamendo API: list 3 ambient/electronic tracks that
# are available for download under CC license.
set -euo pipefail

CLIENT_ID="${JAMENDO_CLIENT_ID:-709fa152}"
TAGS="${1:-ambient+electronic+lofi}"

curl -s "https://api.jamendo.com/v3.0/tracks/?client_id=${CLIENT_ID}&format=json&limit=5&fuzzytags=${TAGS}&speed=high&audiodlformat=mp32&audiodownload_allowed=true&include=licenses" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
status = d.get('headers', {})
print('status:', status.get('status'))
print('results_count:', status.get('results_count'))
print('---')
for t in d.get('results', []):
    print(f'{t[\"id\"]}  {t[\"duration\"]}s  {t[\"name\"]} -- {t[\"artist_name\"]}')
    print(f'  license: {t.get(\"license_ccurl\", \"\")}')
    print(f'  download: {t[\"audiodownload\"]}')
    print()
"
