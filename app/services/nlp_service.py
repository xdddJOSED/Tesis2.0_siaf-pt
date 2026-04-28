import os
import json
import numpy as np
from openai import OpenAI
from dotenv import load_dotenv

# Forzar la carga de las variables de entorno
load_dotenv()

# Inicialización diferida: el cliente se crea la primera vez que se necesita,
# no al importar el módulo. Esto evita que la app crashee en startup si la
# variable de entorno aún no está disponible en ese instante.
_client = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY no está configurada. "
                "Agrégala en Render → Environment → Add Environment Variable."
            )
        _client = OpenAI(api_key=api_key)
    return _client


def construir_super_embedding(
    titulo: str,
    resumen: str,
    objetivo_general: str,
    objetivos_especificos: str,
    justificacion: str,
) -> str:
    """Construye el texto enriquecido para generar embeddings de tesis."""
    return (
        "Título: " + titulo
        + ". Resumen: " + resumen
        + ". Objetivo General: " + objetivo_general
        + ". Objetivos Específicos: " + objetivos_especificos
        + ". Justificación: " + justificacion
    )


def generar_embedding(texto: str) -> list:
    """Genera un vector de embedding usando la API de OpenAI."""
    try:
        respuesta = _get_client().embeddings.create(
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


def normalizar_objetivos_especificos(objetivos) -> list[str]:
    """Asegura que los objetivos específicos se manejen como lista de strings."""
    if isinstance(objetivos, list):
        return [str(objetivo).strip() for objetivo in objetivos if str(objetivo).strip()]
    if isinstance(objetivos, str):
        partes = [parte.strip(" -•\t") for parte in objetivos.split("\n") if parte.strip()]
        return partes
    return []


def normalizar_palabras_clave(palabras_clave) -> list[str]:
    """Asegura que las palabras clave se manejen como una lista corta de strings."""
    if isinstance(palabras_clave, list):
        return [str(palabra).strip() for palabra in palabras_clave if str(palabra).strip()][:6]
    if isinstance(palabras_clave, str):
        partes = [parte.strip(" -•\t") for parte in palabras_clave.replace(",", "\n").split("\n") if parte.strip()]
        return partes[:6]
    return []


def normalizar_justificacion(justificacion) -> list[str]:
    """Convierte la justificación en una lista de tres bloques para la UI."""
    if isinstance(justificacion, list):
        bloques = [str(parrafo).strip() for parrafo in justificacion if str(parrafo).strip()]
        return bloques[:3]

    if isinstance(justificacion, str):
        texto = justificacion.strip()
        if not texto:
            return []

        bloques = [bloque.strip() for bloque in texto.split("\n\n") if bloque.strip()]
        if bloques:
            return bloques[:3]

        return [texto]

    return []


def normalizar_resultado_ia(resultado: dict) -> dict:
    """Convierte la respuesta del modelo al contrato JSON esperado por la UI."""
    return {
        "titulo": str(resultado.get("titulo", "")).strip(),
        "resumen": str(resultado.get("resumen", "")).strip(),
        "objetivo_general": str(resultado.get("objetivo_general", "")).strip(),
        "objetivos_especificos": normalizar_objetivos_especificos(resultado.get("objetivos_especificos", []))[:4],
        "palabras_clave": normalizar_palabras_clave(resultado.get("palabras_clave", [])),
        "justificacion": normalizar_justificacion(resultado.get("justificacion", [])),
        "referencias": resultado.get("referencias", []),
    }


def generar_propuesta_ia(titulo: str, resumen: str, tesis_similares: list) -> dict:
    """
    Envía la idea del usuario y las tesis similares a GPT para generar
    un tema final sugerido, innovador y alineado con las sublíneas de la facultad.
    Retorna un dict estricto con titulo, resumen, objetivo_general,
    objetivos_especificos, justificacion y las tesis de referencia.
    """
    contexto_tesis = ""
    referencias = []
    for tesis, score in tesis_similares:
        porcentaje = round(score * 100, 1)
        contexto_tesis += (
            f"- \"{tesis.titulo}\" (similitud: {porcentaje}%)\n"
            f"  Resumen: {tesis.resumen or 'N/A'}\n"
            f"  Objetivo general: {tesis.objetivo_general or 'N/A'}\n"
            f"  Objetivos específicos: {tesis.objetivos_especificos or 'N/A'}\n"
            f"  Sublínea: {tesis.sublinea_investigacion or 'N/A'}\n"
            f"  Modalidad: {tesis.modalidad or 'N/A'}\n\n"
        )
        referencias.append({
            "titulo": tesis.titulo,
            "similitud": porcentaje,
            "resumen": tesis.resumen or "",
            "objetivo_general": tesis.objetivo_general or "",
            "objetivos_especificos": normalizar_objetivos_especificos(tesis.objetivos_especificos or ""),
            "justificacion": tesis.justificacion or "",
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
4. Escrita en español formal universitario.
5. Redactada con el rigor de un tutor de tesis estricto de la Universidad Técnica de Manabí.

Reglas ESTRICTAS para el campo "justificacion":
1. La justificación NO debe ser un string único; debe ser una lista de exactamente 3 strings.
2. El primer string debe abordar la problemática y el contexto institucional.
3. El segundo string debe explicar la solución tecnológica propuesta y su impacto esperado.
4. El tercer string debe describir los beneficiarios directos e indirectos.
5. Cada string debe estar bien desarrollado, con lenguaje académico universitario y verbos formales como: diagnosticar, obstaculizar, coadyuvar, mitigar, fortalecer, optimizar, consolidar, contribuir.
6. No debe ser genérica, breve ni promocional; debe sonar como una fundamentación de tesis real.

Debes responder con JSON estricto válido, sin texto adicional, sin markdown y sin claves extra.
Responde EXACTAMENTE con esta estructura:
{{
    "titulo": "Título final sugerido para la tesis",
    "resumen": "Resumen académico del tema propuesto en un solo párrafo",
    "objetivo_general": "Objetivo general redactado en infinitivo",
    "objetivos_especificos": [
        "Objetivo específico 1",
        "Objetivo específico 2",
        "Objetivo específico 3",
        "Objetivo específico 4"
    ],
    "palabras_clave": [
        "Palabra clave 1",
        "Palabra clave 2",
        "Palabra clave 3",
        "Palabra clave 4",
        "Palabra clave 5"
    ],
    "justificacion": [
        "Párrafo 1 sobre problemática y contexto.",
        "Párrafo 2 sobre solución tecnológica e impacto.",
        "Párrafo 3 sobre beneficiarios directos e indirectos."
    ]
}}"""

    try:
        respuesta = _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                                {
                                        "role": "system",
                                        "content": (
                                            "Eres un tutor de tesis estricto de la Universidad Técnica de Manabí, "
                                            "especialista en redacción académica universitaria y generador de JSON estricto. "
                                            "Respondes solo con un objeto JSON válido que contenga exactamente las claves "
                                            "titulo, resumen, objetivo_general, objetivos_especificos, palabras_clave y justificacion. "
                                            "objetivos_especificos debe ser una lista de exactamente 4 strings. "
                                            "palabras_clave debe ser una lista de exactamente 5 a 6 strings cortos. "
                                            "La justificacion debe ser una lista de exactamente 3 strings y seguir esta estructura obligatoria: "
                                            "primer string problemática y contexto; segundo string solución tecnológica e impacto; "
                                            "tercer string beneficiarios directos e indirectos. "
                                            "Debes usar tono académico formal, vocabulario universitario y verbos como diagnosticar, "
                                            "obstaculizar, coadyuvar y mitigar. No aceptes justificaciones genéricas ni demasiado cortas."
                                        ),
                                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
                            max_tokens=1000,
        )
        contenido = respuesta.choices[0].message.content.strip()
        # Limpiar posibles bloques de código markdown
        if contenido.startswith("```"):
            contenido = contenido.split("\n", 1)[1]
            contenido = contenido.rsplit("```", 1)[0]
        resultado = json.loads(contenido)
        resultado = normalizar_resultado_ia(resultado)
        resultado["referencias"] = referencias
        return resultado
    except Exception as e:
        print(f"[NLP Service] Error al generar propuesta: {e}")
        return None
