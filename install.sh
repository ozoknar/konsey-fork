#!/usr/bin/env bash
# Konsey tek-komut kurulum: venv + bağımlılıklar + audit DB şeması.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
echo "▸ Python: $($PY --version)"

echo "▸ venv oluşturuluyor (.venv)..."
"$PY" -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate

echo "▸ bağımlılıklar kuruluyor (langgraph, duckdb)..."
pip install --quiet --upgrade pip
pip install --quiet -e .

echo "▸ audit DB şeması kuruluyor (idempotent)..."
python - <<'PY'
import duckdb, os, pathlib
db = os.getenv("KONSEY_DB", "council.duckdb")
duckdb.connect(db).execute(pathlib.Path("schema.sql").read_text(encoding="utf-8"))
print(f"  şema hazır: {db}")
PY

echo "▸ bin/ çalıştırılabilir yapılıyor..."
chmod +x bin/* 2>/dev/null || true

[ -f .env ] || { cp .env.example .env; echo "▸ .env oluşturuldu (.env.example'dan)"; }

echo
echo "✓ Kurulum tamam. Dene:"
echo "    ./bin/konsey-run \"ilk görevim\""
echo "    ./bin/konsey recent"
