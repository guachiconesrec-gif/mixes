
import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import MemoryCacheHandler
from pathlib import Path
import shutil
import re
from spotipy.exceptions import SpotifyException
from dotenv import load_dotenv

load_dotenv()

def obtener_credenciales():
    return {
        "miguel": {
            "client_id": os.getenv("MIGUEL_CLIENT_ID") or os.getenv("miguel_CLIENT_ID"),
            "client_secret": os.getenv("MIGUEL_SECRET_ID") or os.getenv("MIGUEL_CLIENT_SECRET")
        },
        "sermusic": {
            "client_id": os.getenv("ARMANDO_CLIENT_ID") or os.getenv("armando_CLIENT_ID"),
            "client_secret": os.getenv("ARMANDO_SECRET_ID") or os.getenv("ARMANDO_CLIENT_SECRET")
        },
      

USUARIOS_PERMITIDOS = list(obtener_credenciales().keys())

def limpiar_id_track(input_data: str) -> str:
    if not input_data or str(input_data).strip().lower() == 'none':
        return ""
    input_data = str(input_data).strip()
    match = re.search(r'track(?:/|:)([a-zA-Z0-9]{22})', input_data)
    if match: return match.group(1)
    if re.match(r'^[a-zA-Z0-9]{22}$', input_data): return input_data
    return ""

def obtener_auth_manager(usuario: str):
    usuario = usuario.lower()
    apps = obtener_credenciales()
    creds = apps.get(usuario)
    
    if not creds or not creds.get("client_id") or not creds.get("client_secret"):
        raise ValueError(f"No hay credenciales configuradas en el entorno para: {usuario}")

    c_id = creds["client_id"].strip()
    c_secret = creds["client_secret"].strip()
    
    print(f"🔹 {usuario.capitalize()} (Usando ID: {c_id[:4]}... / Secret: {c_secret[:4]}...)")
    
    return SpotifyOAuth(
        client_id=c_id,
        client_secret=c_secret,
        redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI", "https://playlist-e9xy.onrender.com/callback"),
        scope="playlist-modify-public playlist-modify-private user-library-read ugc-image-upload user-read-private",
        cache_handler=MemoryCacheHandler(), 
        open_browser=False,
        show_dialog=True,
        state=usuario
    )

def guardar_imagen_perfil(file):    
    images_dir = Path(__file__).parent.parent / "imagenes"
    images_dir.mkdir(exist_ok=True)
    file_path = images_dir / f"perfil_{file.filename}"
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "success", "filename": file.filename, "ruta": str(file_path)}

def get_artist_tracks(sp, artist_id, artist_name, pais_cuenta, num_tracks=50):
    track_uris = []
    mercado_seguro = 'US'
    
    try:
        offset = 0
        while len(track_uris) < num_tracks and offset < 100:
            results = sp.search(q=artist_name, type='track', limit=20, offset=offset, market=mercado_seguro)
            items = results['tracks']['items']
            if not items: break
            for track in items:
                if any(a['id'] == artist_id for a in track['artists']):
                    if track['uri'] not in track_uris:
                        track_uris.append(track['uri'])
                if len(track_uris) >= num_tracks: break
            offset += 20
        if len(track_uris) >= 10: return track_uris[:num_tracks]
    except Exception as e:
        print(f"Aviso Buscador: {e}")

    try:
        top = sp.artist_top_tracks(artist_id, country=mercado_seguro)
        for t in top.get('tracks', []):
            if t['uri'] not in track_uris:
                track_uris.append(t['uri'])
        if len(track_uris) >= num_tracks: return track_uris[:num_tracks]
    except Exception as e:
        pass

    try:
        albums = sp.artist_albums(artist_id, album_type='album,single', country=mercado_seguro, limit=10)
        for album in albums.get('items', []):
            if len(track_uris) >= num_tracks: break
            album_tracks = sp.album_tracks(album['id'], limit=50)
            for track in album_tracks.get('items', []):
                if any(a['id'] == artist_id for a in track['artists']):
                    if track['uri'] not in track_uris:
                        track_uris.append(track['uri'])
                if len(track_uris) >= num_tracks: break
    except Exception as e:
        pass
        
    return track_uris[:num_tracks]

def crear_playlist_para_artista(artist_name, num_tracks=50, language="es", access_token=None, id_extra=None):
    if not access_token:
         return {"status": "error", "message": "Sesión expirada. Por favor, conecta Spotify de nuevo."}
         
    try:
        # Iniciamos Spotipy usando directamente el token del navegador
        sp = spotipy.Spotify(auth=access_token)
        user_info = sp.current_user()
        user_id = user_info['id']
        
        results = sp.search(q='artist:' + artist_name, type='artist', limit=1)
        if not results['artists']['items']:
            return {"status": "error", "message": f"No se encontró el artista {artist_name}"}
        artist = results['artists']['items'][0]
        
        track_uris = get_artist_tracks(sp, artist['id'], artist['name'], 'US', num_tracks)
        
        if not track_uris:
            return {"status": "error", "message": "No se encontraron canciones."}

        playlist_name = f"{artist['name']} Éxitos MIX"
        playlist = sp.user_playlist_create(user=user_id, name=playlist_name, public=True)
        sp.playlist_add_items(playlist['id'], track_uris)
        
        if id_extra:
            limpios = [limpiar_id_track(i) for i in id_extra if limpiar_id_track(i)]
            if limpios: sp.playlist_add_items(playlist['id'], limpios, position=5)

        return {"status": "success", "playlist_url": playlist['external_urls']['spotify']}
    
    except SpotifyException as e:
        if e.http_status in (403, 400):
            return {"status": "error", "message": "Error de Permisos 403: El usuario debe agregar su correo en la sección 'User Management' del Dashboard de Spotify."}
        return {"status": "error", "message": f"Error de Spotify: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Error del sistema: {e}"}

def crear_listas_por_nombres(nombres, language="es", access_token=None, id_extra=None):
    results = []
    for n in nombres:
        if str(n).strip():
            res = crear_playlist_para_artista(n.strip(), 50, language, access_token, id_extra)
            results.append({"artista": n, "status": res['status'], "message": res.get("message", "")})
    return results
