import json

from flask import Flask, Blueprint, jsonify, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from app.models import db, Usuario, PropuestaTesis, TesisExistente
from app.services.nlp_service import generar_embedding, buscar_tesis_similares, generar_propuesta_ia

main_bp = Blueprint("main", __name__)


@main_bp.before_app_request
def cargar_usuario():
    usuario_id = session.get("usuario_id")
    if usuario_id:
        g.user = Usuario.query.get(usuario_id)
    else:
        g.user = None


@main_bp.get("/health")
def healthcheck():
    return jsonify(status="ok")


@main_bp.get("/")
def index():
    return render_template("index.html")


@main_bp.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "GET":
        return render_template("registro.html")

    nombre_completo = request.form.get("nombre_completo", "").strip()
    correo = request.form.get("correo", "").strip().lower()
    password = request.form.get("password", "")

    if not nombre_completo or not correo or not password:
        flash("Todos los campos son obligatorios.", "error")
        return redirect(url_for("main.registro"))

    # Restricción UTM
    if not correo.endswith("@utm.edu.ec"):
        flash("Solo se permiten correos institucionales de la UTM (@utm.edu.ec).", "error")
        return redirect(url_for("main.registro"))

    if len(password) < 6:
        flash("La contraseña debe tener al menos 6 caracteres.", "error")
        return redirect(url_for("main.registro"))

    if Usuario.query.filter_by(correo=correo).first():
        flash("Este correo ya está registrado. Inicia sesión.", "error")
        return redirect(url_for("main.registro"))

    nuevo_usuario = Usuario(
        nombre_completo=nombre_completo,
        correo=correo,
        password_hash=generate_password_hash(password),
    )
    db.session.add(nuevo_usuario)
    db.session.commit()

    flash("¡Cuenta creada con éxito! Ya puedes iniciar sesión.", "success")
    return redirect(url_for("main.login"))


@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    correo = request.form.get("correo", "").strip()
    password = request.form.get("password", "")

    usuario = Usuario.query.filter_by(correo=correo).first()

    if usuario and check_password_hash(usuario.password_hash, password):
        session["usuario_id"] = usuario.id
        flash(f"Bienvenido/a, {usuario.nombre_completo}.", "success")
        return redirect(url_for("main.dashboard"))

    flash("Credenciales incorrectas. Verifica tu correo y contraseña.", "error")
    return redirect(url_for("main.login"))


@main_bp.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("main.index"))


@main_bp.route("/dashboard")
def dashboard():
    if not g.user:
        flash("Debes iniciar sesión para acceder al panel.", "error")
        return redirect(url_for("main.login"))
    propuestas = PropuestaTesis.query.filter_by(estudiante_id=g.user.id).order_by(PropuestaTesis.fecha_creacion.desc()).all()
    return render_template("dashboard.html", propuestas=propuestas)


@main_bp.route("/generar_propuesta", methods=["POST"])
def generar_propuesta():
    if not g.user:
        flash("Debes iniciar sesión para usar esta función.", "error")
        return redirect(url_for("main.login"))

    titulo = request.form.get("titulo", "").strip()
    resumen = request.form.get("resumen", "").strip()

    if not titulo or not resumen:
        flash("El título y el resumen son obligatorios.", "error")
        return redirect(url_for("main.dashboard"))

    # 1. Generar embedding de la idea del usuario
    texto_completo = f"Título: {titulo}. Resumen: {resumen}"
    vector_usuario = generar_embedding(texto_completo)

    if not vector_usuario:
        flash("Error al conectar con OpenAI. Verifica tu API Key.", "error")
        return redirect(url_for("main.dashboard"))

    # 2. Buscar las 2 tesis más similares
    tesis_existentes = TesisExistente.query.all()
    tesis_similares = buscar_tesis_similares(vector_usuario, tesis_existentes, top_k=2)

    # 3. Generar propuesta con GPT usando contexto de tesis similares
    resultado = generar_propuesta_ia(titulo, resumen, tesis_similares)

    if not resultado:
        flash("Error al generar la propuesta con IA. Intenta de nuevo.", "error")
        return redirect(url_for("main.dashboard"))

    # 4. Guardar la propuesta en la base de datos
    max_sim = tesis_similares[0][1] if tesis_similares else 0.0
    nueva_propuesta = PropuestaTesis(
        estudiante_id=g.user.id,
        titulo=titulo,
        resumen=resumen,
        embedding_nlp=json.dumps(vector_usuario),
        max_similitud=round(max_sim, 4),
        estado="analizado",
        resultado_ia=json.dumps(resultado, ensure_ascii=False),
    )
    db.session.add(nueva_propuesta)
    db.session.commit()

    # 5. Pasar el resultado a la vista
    propuestas = PropuestaTesis.query.filter_by(estudiante_id=g.user.id).order_by(PropuestaTesis.fecha_creacion.desc()).all()
    return render_template("dashboard.html", propuestas=propuestas, resultado_ia=resultado, titulo_original=titulo)


@main_bp.get("/propuesta/<int:id>")
def detalle_propuesta(id):
    if not g.user:
        return jsonify(error="No autenticado"), 401

    propuesta = PropuestaTesis.query.filter_by(id=id, estudiante_id=g.user.id).first()
    if not propuesta:
        return jsonify(error="Propuesta no encontrada"), 404

    data = {
        "id": propuesta.id,
        "titulo": propuesta.titulo,
        "resumen": propuesta.resumen,
        "estado": propuesta.estado,
        "max_similitud": propuesta.max_similitud,
        "fecha": propuesta.fecha_creacion.strftime("%d/%m/%Y %H:%M") if propuesta.fecha_creacion else None,
        "resultado_ia": json.loads(propuesta.resultado_ia) if propuesta.resultado_ia else None,
    }
    return jsonify(data)


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tesis_utm.db'

    db.init_app(app)

    with app.app_context():
        from app.models import Usuario, PropuestaTesis, TesisExistente
        db.create_all()

    app.register_blueprint(main_bp)
    return app
