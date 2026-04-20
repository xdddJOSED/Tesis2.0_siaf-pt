import os
import json
import numpy as np
from openai import OpenAI
from dotenv import load_dotenv

# Forzar la carga de las variables de entorno
load_dotenv()

# Inicializar el cliente pasando la llave explícitamente
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def generar_embedding(texto: str) -> list:
    """Genera un vector de embedding usando la API de OpenAI."""
    try:
        respuesta = client.embeddings.create(
            input=texto,
            model="text-embedding-3-small",
        )
        return respuesta.data[0].embedding
    except Exception as e:
        print(f"[NLP Service] Error al generar embedding: {e}")
        return []


def similitud_coseno(vec_a: list, vec_b: list) -> float:
    """Calcula la similitud de coseno entre dos vectores."""
    a = np.array(vec_a, dtype=np.float64)
    b = np.array(vec_b, dtype=np.float64)
    norma = np.linalg.norm(a) * np.linalg.norm(b)
    if norma == 0:
        return 0.0
    return float(np.dot(a, b) / norma)


def buscar_tesis_similares(embedding_usuario: list, tesis_list, top_k: int = 2):
    """
    Compara el embedding del usuario contra los embeddings almacenados
    y devuelve las top_k tesis más similares.
    Cada elemento de tesis_list debe tener .embedding (JSON string) y .titulo.
    """
    resultados = []
    for tesis in tesis_list:
        if not tesis.embedding:
            continue
        vec_tesis = json.loads(tesis.embedding)
        score = similitud_coseno(embedding_usuario, vec_tesis)
        resultados.append((tesis, score))

    resultados.sort(key=lambda x: x[1], reverse=True)
    return resultados[:top_k]


def generar_propuesta_ia(titulo: str, resumen: str, tesis_similares: list) -> dict:
    """
    Envía la idea del usuario y las tesis similares a GPT para generar
    un tema final sugerido, innovador y alineado con las sublíneas de la facultad.
    Retorna un dict con tema_sugerido, justificacion, y las tesis de referencia.
    """
    contexto_tesis = ""
    referencias = []
    for tesis, score in tesis_similares:
        porcentaje = round(score * 100, 1)
        contexto_tesis += (
            f"- \"{tesis.titulo}\" (similitud: {porcentaje}%)\n"
            f"  Sublínea: {tesis.sublinea_investigacion or 'N/A'}\n"
            f"  Modalidad: {tesis.modalidad or 'N/A'}\n\n"
        )
        referencias.append({
            "titulo": tesis.titulo,
            "similitud": porcentaje,
            "sublinea": tesis.sublinea_investigacion or "N/A",
            "modalidad": tesis.modalidad or "N/A",
        })

    prompt = f"""Eres un asesor académico experto de la Facultad de Ciencias Informáticas de la Universidad Técnica de Manabí (UTM).

Un estudiante quiere desarrollar su tesis de titulación con la siguiente idea:

**Título tentativo:** {titulo}
**Resumen de la idea:** {resumen}

Las siguientes tesis existentes en la facultad son las más similares a su idea:

{contexto_tesis}

Con base en esto, genera una **propuesta de tema final mejorada** que sea:
1. Innovadora y diferenciada de las tesis existentes.
2. Alineada con las sublíneas de investigación de la facultad (Soluciones de Software, etc.).
3. Clara, concisa y con un alcance realista para una tesis de pregrado.

Responde EXACTAMENTE en este formato JSON (sin bloques de código markdown):
{{
  "tema_sugerido": "El título final sugerido para la tesis",
  "justificacion": "Explicación breve de por qué este tema es innovador y cómo se diferencia de las tesis existentes",
  "sublinea_recomendada": "La sublínea de investigación más adecuada",
  "modalidad_sugerida": "Propuesta Tecnológica o Artículo Académico-Científico"
}}"""

    try:
        respuesta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un asesor de tesis universitario. Respondes siempre en JSON válido."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=600,
        )
        contenido = respuesta.choices[0].message.content.strip()
        # Limpiar posibles bloques de código markdown
        if contenido.startswith("```"):
            contenido = contenido.split("\n", 1)[1]
            contenido = contenido.rsplit("```", 1)[0]
        resultado = json.loads(contenido)
        resultado["referencias"] = referencias
        return resultado
    except Exception as e:
        print(f"[NLP Service] Error al generar propuesta: {e}")
        return None
