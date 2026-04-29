import json

from flask import Flask, Blueprint, jsonify, render_template, request, redirect, url_for, flash, session, g
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from app.models import db, Usuario, PropuestaTesis, TesisExistente
from app.services.nlp_service import generar_embedding, buscar_tesis_similares, generar_propuesta_ia, normalizar_resultado_ia, normalizar_justificacion

mail = Mail()

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
        verificado=False,
    )
    db.session.add(nuevo_usuario)
    db.session.commit()

    # Enviar correo de verificación
    from flask import current_app
    token = _generar_token(correo, current_app._get_current_object())
    enlace = url_for("main.verificar_correo", token=token, _external=True)
    try:
        msg = Message(
            subject="Verifica tu cuenta – Sistema de Tesis UTM",
            recipients=[correo],
        )
        msg.body = (
            f"Hola {nombre_completo},\n\n"
            f"Gracias por registrarte. Por favor verifica tu correo haciendo clic en el enlace:\n\n"
            f"{enlace}\n\n"
            f"El enlace expira en 1 hora.\n\nSistema de Tesis UTM"
        )
        mail.send(msg)
        flash("¡Cuenta creada! Revisa tu correo institucional para verificar tu cuenta.", "success")
    except Exception as e:
        flash(f"Cuenta creada, pero no se pudo enviar el correo de verificación: {e}", "warning")

    return redirect(url_for("main.login"))


@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    correo = request.form.get("correo", "").strip()
    password = request.form.get("password", "")

    usuario = Usuario.query.filter_by(correo=correo).first()

    if usuario and check_password_hash(usuario.password_hash, password):
        if not usuario.verificado:
            flash("Debes verificar tu correo antes de iniciar sesión. Revisa tu bandeja de entrada.", "error")
            return redirect(url_for("main.login"))
        session["usuario_id"] = usuario.id
        flash(f"Bienvenido/a, {usuario.nombre_completo}.", "success")
        return redirect(url_for("main.dashboard"))

    flash("Credenciales incorrectas. Verifica tu correo y contraseña.", "error")
    return redirect(url_for("main.login"))


@main_bp.get("/verificar/<token>")
def verificar_correo(token):
    from flask import current_app
    correo = _verificar_token(token, current_app._get_current_object())
    if correo is None:
        flash("El enlace de verificación es inválido o ha expirado.", "error")
        return redirect(url_for("main.login"))

    usuario = Usuario.query.filter_by(correo=correo).first()
    if not usuario:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("main.login"))

    if usuario.verificado:
        flash("Tu correo ya fue verificado anteriormente. Puedes iniciar sesión.", "info")
        return redirect(url_for("main.login"))

    usuario.verificado = True
    db.session.add(usuario)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error("Error al verificar correo para %s: %s", correo, e)
        flash("Ocurrió un error al guardar la verificación. Intenta de nuevo.", "error")
        return redirect(url_for("main.login"))

    flash("¡Correo verificado con éxito! Ya puedes iniciar sesión.", "success")
    return redirect(url_for("main.login"))


@main_bp.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("main.index"))


@main_bp.route("/perfil", methods=["GET", "POST"])
def perfil():
    usuario_id = session.get("usuario_id")
    if not usuario_id:
        flash("Debes iniciar sesión para acceder a tu perfil.", "error")
        return redirect(url_for("main.login"))

    usuario = Usuario.query.get(usuario_id)
    if not usuario:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("main.login"))

    if request.method == "POST":
        from flask import current_app
        import uuid, httpx

        # 1. Actualizar nombre
        nuevo_nombre = request.form.get("nombre_completo", "").strip()
        if nuevo_nombre and len(nuevo_nombre) >= 3:
            usuario.nombre_completo = nuevo_nombre

        # 2. Subir foto a Supabase Storage si se envió una
        foto = request.files.get("foto")
        ALLOWED = {"image/jpeg", "image/png", "image/jpg"}
        if foto and foto.filename:
            if foto.mimetype not in ALLOWED:
                flash("Formato de imagen no válido. Usa JPG o PNG.", "error")
                return redirect(url_for("main.perfil"))

            # Leer contenido y limitar a 2 MB
            imagen_bytes = foto.read()
            if len(imagen_bytes) > 2 * 1024 * 1024:
                flash("La imagen no puede superar los 2 MB.", "error")
                return redirect(url_for("main.perfil"))

            ext = "jpg" if "jpeg" in foto.mimetype else "png"
            nombre_archivo = f"{usuario.id}_{uuid.uuid4().hex}.{ext}"

            supabase_url = current_app.config.get("SUPABASE_URL", "")
            service_key  = current_app.config.get("SUPABASE_SERVICE_KEY", "")

            if not supabase_url or not service_key or service_key == "your-service-role-key-here":
                flash("La subida de avatares no está configurada todavía. Contacta al administrador.", "error")
                return redirect(url_for("main.perfil"))

            try:
                from supabase import create_client
                base_url = supabase_url.rstrip("/")
                sb = create_client(base_url, service_key)
                bucket_path = f"{usuario.id}/{nombre_archivo}"
                current_app.logger.info("Supabase upload → bucket=avatares path=%s", bucket_path)
                print(f"--- DEBUG: bucket=avatars path={bucket_path} supabase_url={base_url} ---", flush=True)
                sb.storage.from_("avatars").upload(
                    path=bucket_path,
                    file=imagen_bytes,
                    file_options={"content-type": foto.mimetype, "upsert": "true"},
                )
                # URL pública del bucket
                usuario.avatar_url = sb.storage.from_("avatars").get_public_url(bucket_path)
            except Exception as e:
                current_app.logger.error("Storage upload error: %s", e)
                print(f"--- DEBUG Storage error: {e} ---", flush=True)
                flash("No se pudo subir la imagen. Verifica la configuración del bucket.", "error")
                return redirect(url_for("main.perfil"))

        # 3. Guardar en BD
        try:
            db.session.add(usuario)
            db.session.commit()
            flash("Perfil actualizado correctamente.", "success")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error("Error al actualizar perfil: %s", e)
            flash("No se pudo guardar el perfil. Intenta de nuevo.", "error")

        return redirect(url_for("main.perfil"))

    return render_template("perfil.html", usuario=usuario)


@main_bp.route("/olvide_contrasena", methods=["GET", "POST"])
def olvide_contrasena():
    if request.method == "GET":
        return render_template("olvide_contrasena.html")

    correo = request.form.get("correo", "").strip().lower()
    if not correo:
        flash("Ingresa tu correo institucional.", "error")
        return redirect(url_for("main.olvide_contrasena"))

    usuario = Usuario.query.filter_by(correo=correo).first()
    # No revelamos si el correo existe o no (seguridad)
    if usuario:
        from flask import current_app
        token = _generar_token(correo, current_app._get_current_object())
        enlace = url_for("main.restablecer_contrasena", token=token, _external=True)
        try:
            msg = Message(
                subject="Recupera tu contraseña – SIAF-PT UTM",
                recipients=[correo],
            )
            msg.body = (
                f"Hola {usuario.nombre_completo},\n\n"
                f"Recibimos una solicitud para restablecer tu contraseña.\n"
                f"Haz clic en el siguiente enlace (válido por 1 hora):\n\n"
                f"{enlace}\n\n"
                f"Si no solicitaste esto, ignora este mensaje.\n\nSIAF-PT UTM"
            )
            mail.send(msg)
        except Exception as e:
            print(f"\n[DEV] Envío de correo fallido ({e}). Usa este enlace manualmente:\n{enlace}\n")

    flash("Si el correo existe, recibirás un enlace (o revisa la terminal en modo desarrollo).", "success")
    return redirect(url_for("main.login"))


@main_bp.route("/restablecer_contrasena/<token>", methods=["GET", "POST"])
def restablecer_contrasena(token):
    from flask import current_app
    correo = _verificar_token(token, current_app._get_current_object())
    if correo is None:
        flash("El enlace es inválido o ha expirado. Solicita uno nuevo.", "error")
        return redirect(url_for("main.olvide_contrasena"))

    if request.method == "GET":
        return render_template("restablecer_contrasena.html", token=token)

    nueva = request.form.get("password", "")
    confirmacion = request.form.get("confirmacion", "")

    if len(nueva) < 6:
        flash("La contraseña debe tener al menos 6 caracteres.", "error")
        return redirect(url_for("main.restablecer_contrasena", token=token))

    if nueva != confirmacion:
        flash("Las contraseñas no coinciden.", "error")
        return redirect(url_for("main.restablecer_contrasena", token=token))

    usuario = Usuario.query.filter_by(correo=correo).first()
    if not usuario:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("main.login"))

    usuario.password_hash = generate_password_hash(nueva)
    db.session.commit()
    flash("¡Contraseña actualizada con éxito! Ya puedes iniciar sesión.", "success")
    return redirect(url_for("main.login"))


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
        objetivo_general=resultado.get("objetivo_general", ""),
        objetivos_especificos=json.dumps(resultado.get("objetivos_especificos", []), ensure_ascii=False),
        justificacion=json.dumps(resultado.get("justificacion", []), ensure_ascii=False),
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

    resultado_ia = json.loads(propuesta.resultado_ia) if propuesta.resultado_ia else None
    if resultado_ia:
        resultado_ia = normalizar_resultado_ia(resultado_ia)

    data = {
        "id": propuesta.id,
        "titulo": propuesta.titulo,
        "resumen": propuesta.resumen,
        "objetivo_general": propuesta.objetivo_general,
        "objetivos_especificos": json.loads(propuesta.objetivos_especificos) if propuesta.objetivos_especificos else [],
        "justificacion": normalizar_justificacion(
            json.loads(propuesta.justificacion) if propuesta.justificacion and propuesta.justificacion.strip().startswith("[") else propuesta.justificacion
        ),
        "estado": propuesta.estado,
        "max_similitud": propuesta.max_similitud,
        "fecha": propuesta.fecha_creacion.strftime("%d/%m/%Y %H:%M") if propuesta.fecha_creacion else None,
        "resultado_ia": resultado_ia,
    }
    return jsonify(data)


def _generar_token(correo: str, app) -> str:
    s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    return s.dumps(correo, salt="verificacion-correo")


def _verificar_token(token: str, app, max_age: int = 3600):
    s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    try:
        correo = s.loads(token, salt="verificacion-correo", max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None
    return correo


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    mail.init_app(app)

    with app.app_context():
        from app.models import Usuario, PropuestaTesis, TesisExistente
        db.create_all()

    app.register_blueprint(main_bp)
    return app
