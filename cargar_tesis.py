"""
Script de carga masiva: inserta tesis_utm_limpias.csv en la tabla tesis_existentes.
- Recrea la tabla para reflejar las columnas nuevas del modelo.
- Evita duplicados verificando por título antes de insertar.
"""
import pandas as pd
from app import create_app
from app.models import db, TesisExistente

app = create_app()

with app.app_context():
    # Recrear la tabla para aplicar los nuevos campos del modelo
    TesisExistente.__table__.drop(db.engine, checkfirst=True)
    db.create_all()
    print("Tabla 'tesis_existentes' recreada con la nueva estructura.\n")

    # Leer el CSV limpio
    df = pd.read_csv("tesis_utm_limpias.csv", encoding="utf-8-sig")
    print(f"Filas en CSV: {len(df)}")

    insertados = 0
    omitidos = 0

    for _, row in df.iterrows():
        titulo = row["tema"].strip()

        # Verificar duplicado por título
        existe = TesisExistente.query.filter_by(titulo=titulo).first()
        if existe:
            print(f"  [OMITIDO] Ya existe: {titulo[:60]}...")
            omitidos += 1
            continue

        tesis = TesisExistente(
            titulo=titulo,
            estudiante=row.get("estudiante", ""),
            linea_investigacion=row.get("línea_de_investigación", ""),
            sublinea_investigacion=row.get("sublínea_de_investigación", ""),
            modalidad=row.get("modalidad", ""),
        )
        db.session.add(tesis)
        insertados += 1
        print(f"  [INSERT] {titulo[:60]}...")

    db.session.commit()
    print(f"\nResultado: {insertados} insertados, {omitidos} omitidos (duplicados).")

    # Verificación final
    total = TesisExistente.query.count()
    print(f"Total registros en tabla tesis_existentes: {total}")
