"""Regenera embeddings enriquecidos para la tabla tesis_existentes."""
import json
from app import create_app
from app.models import db, TesisExistente
from app.services.nlp_service import construir_super_embedding, generar_embedding

app = create_app()

with app.app_context():
    tesis_list = TesisExistente.query.all()
    print(f"Tesis encontradas: {len(tesis_list)}\n")

    actualizadas = 0
    omitidas = 0

    for t in tesis_list:
        # Saltar si ya tiene embedding
        if t.embedding and str(t.embedding).strip() not in ("", "[]", "None"):
            print(f"  [SKIP] #{t.id} ya tiene embedding: {t.titulo[:55]}...")
            omitidas += 1
            continue

        texto = construir_super_embedding(
            t.titulo or "",
            t.resumen or "",
            t.objetivo_general or "",
            t.objetivos_especificos or "",
            t.justificacion or "",
        )

        vector = generar_embedding(texto)

        if vector:
            t.embedding = json.dumps(vector)
            actualizadas += 1
            print(f"  [OK] #{t.id} ({len(vector)} dims): {t.titulo[:55]}...")
        else:
            print(f"  [ERROR] #{t.id}: {t.titulo[:55]}...")

    db.session.commit()
    print(f"\nResultado: {actualizadas} actualizadas, {omitidas} ya tenían embedding.")
