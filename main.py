import os
import shutil
import json
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, Body, Request, Response, Cookie, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from auth_db import get_db, UsuarioDB, get_password_hash, verificar_password
from spotify_utils import (
    crear_playlist_para_artista,
    guardar_imagen_perfil,
    crear_listas_por_nombres,
    obtener_auth_manager,
    USUARIOS_PERMITIDOS
)
from db_utils import guardar_imagen, obtener_imagenes

for folder in ["static", "imagenes", "templates", "logs"]:
    Path(folder).mkdir(exist_ok=True)

app = FastAPI(title="Spotify API 2.0")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "super-clave-spotify-miguel-123"),
    https_only=True,
    same_site="lax"
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/imagenes", StaticFiles(directory="imagenes"), name="imagenes")
templates = Jinja2Templates(directory="templates")

# ===========================================================
# FUNCIONES DE MANEJO DE TOKENS POR USUARIO
# ===========================================================

def guardar_token_para_usuario(request: Request, usuario: str, token_info: dict):
    """Guarda el token en la sesión asociado al usuario."""
    # Añadimos el nombre de usuario dentro del token para verificación extra
    token_info["usuario"] = usuario
    request.session[f"token_{usuario}"] = token_info

def obtener_token_valido(request: Request, usuario: str):
    """Obtiene y (si es necesario) refresca el token del usuario especificado."""
    token_key = f"token_{usuario}"
    token_info = request.session.get(token_key)

    if not token_info:
        print(f"No se encontró token para {usuario}")
        return None

    # Verifica que el token pertenezca al usuario
    if token_info.get("usuario") != usuario:
        print(f"Token guardado no coincide con el usuario {usuario}")
        return None

    try:
        auth_manager = obtener_auth_manager(usuario)
        if auth_manager.is_token_expired(token_info):
            print(f"Token de {usuario} expirado, refrescando...")
            token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
            token_info['usuario'] = usuario  # reasegurar
            request.session[token_key] = token_info
        return token_info['access_token']
    except Exception as e:
        print(f"Error al validar/refrescar token para {usuario}: {e}")
        # Si falla, eliminamos el token corrupto
        request.session.pop(token_key, None)
        return None

# ===========================================================
# RUTAS DE AUTENTICACIÓN INTERNA
# ===========================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: int = 0, success: int = 0):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": error, "success": success})

@app.get("/registro", response_class=HTMLResponse)
async def registro_page(request: Request, error: int = 0):
    return templates.TemplateResponse(request=request, name="registro.html", context={"error": error})

@app.post("/api/registro")
async def procesar_registro(
    username: str = Form(...), 
    password: str = Form(...), 
    db: Session = Depends(get_db)
):
    user = username.lower().strip()
    usuario_existente = db.query(UsuarioDB).filter(UsuarioDB.username == user).first()
    if usuario_existente:
        return RedirectResponse(url="/registro?error=1", status_code=303)
    
    hashed_pwd = get_password_hash(password)
    nuevo_usuario = UsuarioDB(username=user, hashed_password=hashed_pwd)
    db.add(nuevo_usuario)
    db.commit()
    return RedirectResponse(url="/login?success=1", status_code=303)

@app.post("/api/login")
async def procesar_login(
    request: Request,
    username: str = Form(...), 
    password: str = Form(...), 
    db: Session = Depends(get_db)
):
    user = username.lower().strip()
    db_user = db.query(UsuarioDB).filter(UsuarioDB.username == user).first()
    
    if not db_user or not verificar_password(password, db_user.hashed_password):
        return RedirectResponse(url="/login?error=1", status_code=303)
        
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(key="usuario", value=user, max_age=604800)
    # Opcional: limpiar la sesión anterior al iniciar con otro usuario
    # Puedes descomentar la siguiente línea si quieres borrar todos los tokens al login
    # request.session.clear()
    return resp

@app.get("/logout")
async def logout(request: Request):
    usuario = request.cookies.get("usuario", "")
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("usuario")
    # Limpia solo el token del usuario actual, no los demás
    if usuario:
        request.session.pop(f"token_{usuario}", None)
    return resp

# ===========================================================
# RUTAS DE SPOTIFY
# ===========================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, usuario: str | None = Cookie(None)):
    if not usuario: return RedirectResponse(url="/login")
    imgs = obtener_imagenes()
    return templates.TemplateResponse(request=request, name="index.html", context={"imagenes": imgs, "usuario_actual": usuario.capitalize()})

@app.get("/conectar-spotify")
async def conectar_spotify(usuario: str | None = Cookie(None)):
    if not usuario: return RedirectResponse("/login")
    auth_manager = obtener_auth_manager(usuario)
    return RedirectResponse(auth_manager.get_authorize_url(state=usuario))

@app.get("/callback")
async def callback_spotify(request: Request, code: str | None = None, state: str | None = None, usuario: str | None = Cookie(None)):
    usuario_activo = state if state else usuario
    if not usuario_activo: 
        return RedirectResponse(url="/login")
        
    if code:
        try:
            auth_manager = obtener_auth_manager(usuario_activo)
            token_info = auth_manager.get_access_token(code, as_dict=True)
            # Guardar token asociado al usuario
            guardar_token_para_usuario(request, usuario_activo, token_info)
            print(f"Token guardado correctamente para {usuario_activo}")
        except Exception as e:
            print(f"Error en callback para {usuario_activo}: {e}")
            # Podrías redirigir a una página de error si quieres
    else:
        print("No se recibió code en callback, posible error de autorización")
            
    return RedirectResponse(url="/")

# Modelos de petición
class CrearListasBody(BaseModel):
    nombres: str
    language: str = "es"
    id_extra: List[str] = []

class PlaylistRequest(BaseModel):
    artist_name: str
    language: str = "es"
    id_extra: List[str] = []

# Endpoint para crear listas por múltiples artistas (JSON)
@app.post("/api/crear_listas_json")
async def crear_listas_json(request: Request, payload: CrearListasBody, usuario: str | None = Cookie(None)):
    if not usuario: return {"status": "error", "message": "No has iniciado sesión en la app"}
    
    access_token = obtener_token_valido(request, usuario)
    if not access_token: 
        return {"status": "error", "message": "Debes conectar Spotify con este usuario antes de crear listas."}
        
    nombres = [n.strip() for n in payload.nombres.split(',') if n.strip()]
    return crear_listas_por_nombres(nombres, language=payload.language, access_token=access_token, id_extra=payload.id_extra)

# Endpoint para crear una sola playlist
@app.post("/api/crear_playlist")
def crear_playlist(request: Request, req: PlaylistRequest, usuario: str | None = Cookie(None)):
    if not usuario: return {"status": "error"}
    
    access_token = obtener_token_valido(request, usuario)
    if not access_token: 
        return [{"status": "error", "message": "Debes conectar Spotify con este usuario."}]
        
    return [crear_playlist_para_artista(req.artist_name, language=req.language, access_token=access_token, id_extra=req.id_extra)]

# Subida de imágenes
@app.post("/api/upload_image")
async def upload_image(file: UploadFile = File(...), artista: str = Form(None), usuario: str | None = Cookie(None)):
    if not usuario: return {"status": "error"}
    path = Path("imagenes") / file.filename
    with path.open("wb") as buffer: shutil.copyfileobj(file.file, buffer)
    guardar_imagen(file.filename, str(path), artista)
    return {"status": "success"}
