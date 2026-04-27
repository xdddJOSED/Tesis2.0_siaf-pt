import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

BASE_DIR = Path(__file__).resolve().parent
SQLITE_PATH = BASE_DIR / "instance" / "tesis_utm.db.bak"


def load_database_url() -> str:
    load_dotenv(BASE_DIR / ".env", override=True)
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL no definida en .env")
    return database_url


def fetch_sqlite_rows(sqlite_path: Path) -> list[dict]:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"No existe el archivo SQLite: {sqlite_path}")

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                titulo,
                estudiante,
                linea_investigacion,
                sublinea_investigacion,
                modalidad,
                carrera,
                resumen,
                embedding,
                creado_en
            FROM tesis_existentes
            ORDER BY id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def migrate_rows(rows: list[dict], database_url: str) -> tuple[int, int]:
    engine = create_engine(database_url)

    insert_stmt = text(
        """
        INSERT INTO tesis_existentes (
            id,
            titulo,
            estudiante,
            linea_investigacion,
            sublinea_investigacion,
            modalidad,
            carrera,
            resumen,
            embedding,
            creado_en
        ) VALUES (
            :id,
            :titulo,
            :estudiante,
            :linea_investigacion,
            :sublinea_investigacion,
            :modalidad,
            :carrera,
            :resumen,
            :embedding,
            :creado_en
        )
        ON CONFLICT (id) DO UPDATE
        SET
            titulo = EXCLUDED.titulo,
            estudiante = EXCLUDED.estudiante,
            linea_investigacion = EXCLUDED.linea_investigacion,
            sublinea_investigacion = EXCLUDED.sublinea_investigacion,
            modalidad = EXCLUDED.modalidad,
            carrera = EXCLUDED.carrera,
            resumen = EXCLUDED.resumen,
            embedding = EXCLUDED.embedding,
            creado_en = EXCLUDED.creado_en
        """
    )

    with engine.begin() as conn:
        before_count = conn.execute(text("SELECT COUNT(*) FROM tesis_existentes")).scalar_one()
        for row in rows:
            conn.execute(insert_stmt, row)

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

        after_count = conn.execute(text("SELECT COUNT(*) FROM tesis_existentes")).scalar_one()

    return before_count, after_count


def main() -> None:
    database_url = load_database_url()
    rows = fetch_sqlite_rows(SQLITE_PATH)

    if not rows:
        print("No hay registros en SQLite para migrar.")
        return

    before_count, after_count = migrate_rows(rows, database_url)

    print(f"REGISTROS_ORIGEN_SQLITE={len(rows)}")
    print(f"REGISTROS_SUPABASE_ANTES={before_count}")
    print(f"REGISTROS_SUPABASE_DESPUES={after_count}")
    print("MIGRACION_OK")


if __name__ == "__main__":
    main()
