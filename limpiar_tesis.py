"""
Script de limpieza del archivo listado_de_temas.xlsx
Genera tesis_utm_limpias.csv con una fila por tesis.
"""
import pandas as pd
import re

# ── 1. Leer el Excel con openpyxl (preserva celdas combinadas) ──
df = pd.read_excel(
    "listado_de_temas.xlsx",
    engine="openpyxl",
    header=0,
    dtype=str,
)

print("── Columnas originales ──")
print(df.columns.tolist())
print(f"Filas originales: {len(df)}")

# Eliminar columna de número de orden (#)
if "#" in df.columns:
    df.drop(columns=["#"], inplace=True)

# ── 2. Limpiar cabeceras ──
def limpiar_cabecera(col):
    col = col.strip().lower()
    col = col.replace(":", "").replace("\n", " ")
    col = re.sub(r"\s+", "_", col)
    col = re.sub(r"[^a-záéíóúñü0-9_]", "", col)
    return col

df.columns = [limpiar_cabecera(c) for c in df.columns]
print("\n── Columnas limpias ──")
print(df.columns.tolist())

# ── 3. Eliminar columnas de privacidad (cédula, celular, correo) ──
patron_privacidad = re.compile(r"cedula|cédula|celular|correo|email|teléfono|telefono", re.I)
cols_a_eliminar = [c for c in df.columns if patron_privacidad.search(c)]
if cols_a_eliminar:
    print(f"\nColumnas de privacidad eliminadas: {cols_a_eliminar}")
    df.drop(columns=cols_a_eliminar, inplace=True)

# Eliminar cualquier columna con nombre vacío residual
df = df.loc[:, df.columns != ""]

# ── 4. Eliminar filas completamente vacías ──
df.dropna(how="all", inplace=True)
df.reset_index(drop=True, inplace=True)

# ── 5. Limpiar saltos de línea y espacios extra en todas las celdas ──
for col in df.columns:
    df[col] = (
        df[col]
        .fillna("")
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
        .str.strip('"')
        .str.strip()
    )

# ── 6. Agrupar autores: forward-fill del tema y agrupar estudiantes ──
# Regla: si "tema" está vacío, pertenece a la tesis de la fila anterior.
df["tema"] = df["tema"].replace("", pd.NA)
df["tema"] = df["tema"].ffill()

# También forward-fill de las demás columnas descriptivas cuando estén vacías
for col in ["línea_de_investigación", "sublínea_de_investigación", "modalidad"]:
    if col in df.columns:
        df[col] = df[col].replace("", pd.NA).ffill()

# Agrupar: una fila por tesis, estudiantes separados por coma
df_clean = (
    df.groupby("tema", sort=False)
    .agg({
        "estudiante": lambda x: ", ".join(v for v in x if v),
        **{
            c: "first"
            for c in df.columns
            if c not in ("tema", "estudiante")
        },
    })
    .reset_index()
)

# Reordenar columnas
cols_orden = ["tema", "estudiante"] + [
    c for c in df_clean.columns if c not in ("tema", "estudiante")
]
df_clean = df_clean[cols_orden]

# ── 7. Guardar CSV limpio con codificación UTF-8 ──
salida = "tesis_utm_limpias.csv"
df_clean.to_csv(salida, index=False, encoding="utf-8-sig")

print(f"\n── Resultado ──")
print(f"Tesis únicas: {len(df_clean)}")
print(f"Columnas finales: {df_clean.columns.tolist()}")
print(f"Archivo guardado: {salida}")
print()
print(df_clean.to_string(index=False, max_colwidth=60))
