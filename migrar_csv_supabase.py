"""
Migración completa: lee listado_mejorado.csv (texto rico) + cruza embeddings desde SQLite
e inserta todo en la tabla tesis_existentes de Supabase.
"""
import csv
import json
import sqlite3
import unicodedata
from pathlib import Path

from dotenv import load_dotenv
import os
from sqlalchemy import create_engine, text

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "listado_mejorado.csv"
SQLITE_PATH = BASE_DIR / "instance" / "tesis_utm.db.bak"


# ── helpers ──────────────────────────────────────────────────────────────────

def normalizar(s: str) -> str:
    """Normaliza título para matching: mayúsculas, sin acentos, sin espacios extra."""
    s = s.strip().upper()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def cargar_embeddings_sqlite(path: Path) -> dict[str, str]:
    """Devuelve {titulo_normalizado: embedding_json} desde el backup SQLite."""
    if not path.exists():
        print(f"[AVISO] SQLite no encontrado en {path}; se omiten embeddings existentes.")
        return {}
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT titulo, embedding FROM tesis_existentes").fetchall()
    conn.close()
    return {
        normalizar(r["titulo"]): r["embedding"]
        for r in rows
        if r["titulo"]
    }


def cargar_csv(path: Path) -> list[dict]:
    """Lee el CSV con utf-8-sig (elimina BOM) y devuelve filas con TEMA no vacío."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.DictReader(f))

    # Normalizar nombres de columna (quitar saltos de línea y espacios extra)
    clean_rows = []
    for row in rows:
        clean = {k.strip().replace("\n", ""): v for k, v in row.items()}
        clean_rows.append(clean)

    # Solo filas con título presente
    return [r for r in clean_rows if r.get("TEMA", "").strip()]


# ── migración ─────────────────────────────────────────────────────────────────

def run_migration() -> None:
    load_dotenv(BASE_DIR / ".env", override=True)
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL no definida en .env")

    embedding_map = cargar_embeddings_sqlite(SQLITE_PATH)
    print(f"Embeddings disponibles desde SQLite: {len(embedding_map)}")

    csv_rows = cargar_csv(CSV_PATH)
    print(f"Filas válidas en CSV: {len(csv_rows)}")

    engine = create_engine(database_url)

    insert_stmt = text(
        """
        INSERT INTO tesis_existentes (
            titulo, estudiante, linea_investigacion, sublinea_investigacion,
            modalidad, resumen, objetivo_general, objetivos_especificos,
            justificacion, embedding
        ) VALUES (
            :titulo, :estudiante, :linea_investigacion, :sublinea_investigacion,
            :modalidad, :resumen, :objetivo_general, :objetivos_especificos,
            :justificacion, :embedding
        )
        """
    )

    with engine.begin() as conn:
        # Truncar tabla manteniendo la estructura
        conn.execute(text("TRUNCATE TABLE tesis_existentes RESTART IDENTITY CASCADE"))
        print("Tabla tesis_existentes truncada.")

        inserted = 0
        sin_embedding = 0
        first_row_data = None

        for row in csv_rows:
            titulo = row.get("TEMA", "").strip()
            params = {
                "titulo":                  titulo,
                "estudiante":              row.get("ESTUDIANTE", "").strip() or None,
                "linea_investigacion":     row.get("LÍNEA DE INVESTIGACIÓN:", "").strip() or None,
                "sublinea_investigacion":  row.get("SUBLÍNEA DE INVESTIGACIÓN:", "").strip() or None,
                "modalidad":               row.get("MODALIDAD:", "").strip() or None,
                "resumen":                 row.get("RESUMEN", "").strip() or None,
                "objetivo_general":        row.get("OBJETIVO GENERAL", "").strip() or None,
                "objetivos_especificos":   row.get("OBJETIVOS ESEPECIFICOS", "").strip() or None,
                "justificacion":           row.get("JUSTIFICACION", "").strip() or None,
                "embedding":               embedding_map.get(normalizar(titulo)),
            }

            if params["embedding"] is None:
                sin_embedding += 1

            conn.execute(insert_stmt, params)
            inserted += 1

            if first_row_data is None:
                first_row_data = params

        # Reajustar secuencia de id
        conn.execute(
            text(
                """
                SELECT setval(
                    pg_get_serial_sequence('tesis_existentes', 'id'),
                    COALESCE((SELECT MAX(id) FROM tesis_existentes), 1),
                    true
                )
                """
            )
        )

    print(f"\nInsertados: {inserted}")
    print(f"Con embedding heredado de SQLite: {inserted - sin_embedding}")
    print(f"Sin embedding (se generarán con generar_embeddings.py): {sin_embedding}")

    print("\n=== PRIMER REGISTRO INSERTADO ===")
    for campo, valor in first_row_data.items():
        if campo == "embedding":
            v = str(valor)[:60] + "..." if valor else "NULL"
        else:
            v = str(valor)[:120] if valor else "NULL"
        print(f"  {campo}: {v}")

    print("\nMIGRACION_OK")


if __name__ == "__main__":
    run_migration()
