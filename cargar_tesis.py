"""Reconstruye la base de datos y carga listado_mejorado.csv en PostgreSQL."""

import json
import re
import unicodedata

import pandas as pd

from app import create_app
from app.models import TesisExistente, db
from app.services.nlp_service import construir_super_embedding, generar_embedding


CSV_PATH = "listado_mejorado.csv"


def normalizar_columna(nombre: str) -> str:
    texto = str(nombre).strip().lower().replace("\n", " ").replace(":", "")
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"\s+", "_", texto)
    texto = re.sub(r"[^a-z0-9_]", "", texto)
    texto = texto.replace("esepecificos", "especificos")
    return texto


def valor_texto(row: pd.Series, column_name: str) -> str:
    return str(row.get(column_name, "")).strip()

app = create_app()

with app.app_context():
    db.drop_all()
    db.create_all()
    print("Base de datos reiniciada con la nueva estructura.\n")

    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig").fillna("")
    df.columns = [normalizar_columna(col) for col in df.columns]
    print(f"Filas en CSV: {len(df)}")

    insertados = 0

    for _, row in df.iterrows():
        titulo = valor_texto(row, "tema") or valor_texto(row, "titulo")
        if not titulo:
            print("  [OMITIDO] Fila sin título.")
            continue

        resumen = valor_texto(row, "resumen")
        objetivo_general = valor_texto(row, "objetivo_general")
        objetivos_especificos = valor_texto(row, "objetivos_especificos")
        justificacion = valor_texto(row, "justificacion")

        texto_embedding = construir_super_embedding(
            str(titulo),
            str(resumen),
            str(objetivo_general),
            str(objetivos_especificos),
            str(justificacion),
        )
        vector = generar_embedding(texto_embedding)

        tesis = TesisExistente(
            titulo=titulo,
            estudiante=valor_texto(row, "estudiante"),
            linea_investigacion=valor_texto(row, "linea_de_investigacion"),
            sublinea_investigacion=valor_texto(row, "sublinea_de_investigacion"),
            modalidad=valor_texto(row, "modalidad"),
            carrera=valor_texto(row, "carrera"),
            resumen=resumen,
            objetivo_general=objetivo_general,
            objetivos_especificos=objetivos_especificos,
            justificacion=justificacion,
            embedding=json.dumps(vector, ensure_ascii=False) if vector else None,
        )
        db.session.add(tesis)
        insertados += 1
        print(f"  [INSERT] {titulo[:60]}...")

    db.session.commit()
    print(f"\nResultado: {insertados} insertados.")

    total = TesisExistente.query.count()
    print(f"Total registros en tabla tesis_existentes: {total}")
