from sqlalchemy import func
from flask_sqlalchemy import SQLAlchemy

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

from config import Config


db = SQLAlchemy()


class Usuario(db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre_completo = db.Column(db.String(120), nullable=False)
    correo = db.Column(db.String(120), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default="estudiante")
    creado_en = db.Column(db.DateTime(timezone=True), server_default=func.now())

    # Relación bidireccional: un usuario puede tener muchas propuestas de tesis
    propuestas = db.relationship("PropuestaTesis", back_populates="estudiante", cascade="all, delete-orphan")


class PropuestaTesis(db.Model):
    __tablename__ = "propuestas"

    id = db.Column(db.Integer, primary_key=True)
    estudiante_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    titulo = db.Column(db.String(255), nullable=False)
    resumen = db.Column(db.Text, nullable=False)
    fecha_creacion = db.Column(db.DateTime(timezone=True), server_default=func.now())
    estado = db.Column(db.String(30), nullable=False, default="borrador")

    # Este campo almacena los vectores matemáticos (embeddings) generados por el modelo de NLP.
    # Se utiliza para calcular la similitud semántica entre propuestas y detectar posibles
    # plagios o duplicados comparando con tesis existentes en la base de datos.
    embedding_nlp = db.Column(db.Text, nullable=True)

    max_similitud = db.Column(db.Float)
    resultado_ia = db.Column(db.Text, nullable=True)

    # Relación bidireccional hacia Usuario
    estudiante = db.relationship("Usuario", back_populates="propuestas")


class TesisExistente(db.Model):
    __tablename__ = "tesis_existentes"

    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(255), nullable=False)
    estudiante = db.Column(db.String(255), nullable=True)
    linea_investigacion = db.Column(db.String(180), nullable=True)
    sublinea_investigacion = db.Column(db.String(180), nullable=True)
    modalidad = db.Column(db.String(80), nullable=True)
    carrera = db.Column(db.String(120), nullable=True)
    resumen = db.Column(db.Text, nullable=True)
    embedding = db.Column(db.Text, nullable=True)
    creado_en = db.Column(db.DateTime(timezone=True), server_default=func.now())
