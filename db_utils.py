import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "imagenes.db"

# Crear la tabla si no existe
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute('''
CREATE TABLE IF NOT EXISTS imagenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    ruta TEXT NOT NULL,
    artista TEXT
)
''')
conn.commit()
conn.close()

def guardar_imagen(nombre, ruta, artista=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO imagenes (nombre, ruta, artista) VALUES (?, ?, ?)", (nombre, ruta, artista))
    conn.commit()
    conn.close()

def obtener_imagenes():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, nombre, ruta, artista FROM imagenes")
    rows = c.fetchall()
    conn.close()
    return [
        {"id": row[0], "nombre": row[1], "ruta": row[2], "artista": row[3]} for row in rows
    ]
