import json
import os
import hashlib
from aiohttp import web
import security

# Load the USERS_FILE from music_manager path
USERS_FILE = "/root/dashboard/music_users.json"

def load_music_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_music_users(users):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=4)
    except Exception as e:
        print(f"Error saving music users in admin: {e}")

async def api_music_admin_list(request):
    # Verify session authentication on MotoServer Admin
    token = request.cookies.get("motoserver_session")
    if not token or not security.validate_session(token):
        return web.json_response({"success": False, "error": "No autorizado"}, status=401)
    
    users = load_music_users()
    # Format list for frontend (without password hashes for safety)
    user_list = []
    for username, data in users.items():
        user_list.append({
            "username": username,
            "artists": data.get("artists", [])
        })
    return web.json_response({"success": True, "users": user_list})

async def api_music_admin_save(request):
    token = request.cookies.get("motoserver_session")
    if not token or not security.validate_session(token):
        return web.json_response({"success": False, "error": "No autorizado"}, status=401)

    try:
        data = await request.json()
        username = data.get("username", "").strip().lower()
        password = data.get("password", "")
        artists = data.get("artists", [])

        if not username or not isinstance(artists, list):
            return web.json_response({"success": False, "error": "Datos inválidos"}, status=400)

        users = load_music_users()
        
        # If it's a new user, password is required
        is_new = username not in users
        if is_new and not password:
            return web.json_response({"success": False, "error": "La contraseña es requerida para nuevos usuarios"}, status=400)

        if is_new:
            users[username] = {
                "password_hash": hashlib.sha256(password.encode()).hexdigest(),
                "artists": [a.strip() for a in artists if a.strip()]
            }
        else:
            # Modify existing user
            if password:
                users[username]["password_hash"] = hashlib.sha256(password.encode()).hexdigest()
            users[username]["artists"] = [a.strip() for a in artists if a.strip()]

        save_music_users(users)
        return web.json_response({"success": True, "message": "Usuario guardado correctamente"})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_admin_delete(request):
    token = request.cookies.get("motoserver_session")
    if not token or not security.validate_session(token):
        return web.json_response({"success": False, "error": "No autorizado"}, status=401)

    try:
        data = await request.json()
        username = data.get("username", "").strip().lower()

        if not username:
            return web.json_response({"success": False, "error": "Nombre de usuario requerido"}, status=400)

        users = load_music_users()
        if username in users:
            del users[username]
            save_music_users(users)
            return web.json_response({"success": True, "message": "Usuario eliminado correctamente"})
        else:
            return web.json_response({"success": False, "error": "El usuario no existe"}, status=404)
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_admin_download_stats(request):
    token = request.cookies.get("motoserver_session")
    if not token or not security.validate_session(token):
        return web.json_response({"success": False, "error": "No autorizado"}, status=401)
        
    try:
        from music_manager import _active_downloads, _gdrive_cached_songs
        # Read from background backup script active downloads
        backup_active = []
        backup_file = "/tmp/active_backup_downloads.json"
        if os.path.exists(backup_file):
            try:
                with open(backup_file, "r") as f:
                    backup_active = json.load(f)
            except:
                pass
        
        # Combine and deduplicate
        combined_active = list(set(list(_active_downloads) + backup_active))
        
        return web.json_response({
            "success": True,
            "active_downloads": combined_active,
            "active_downloads_count": len(combined_active),
            "total_cached_songs": len(_gdrive_cached_songs)
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_admin_favorites_raw(request):
    try:
        username = request.query.get("username", "").strip().lower()
        if not username:
            return web.json_response({"success": False, "error": "Usuario requerido"}, status=400)
        users = load_music_users()
        if username not in users:
            return web.json_response({"success": False, "error": "Usuario no encontrado"}, status=404)
        favorites = users[username].get("favorites", [])
        return web.json_response({"success": True, "favorites": favorites})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)
