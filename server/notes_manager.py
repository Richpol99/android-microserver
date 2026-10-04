import os
import json
import time
import uuid
import base64
import asyncio
import aiohttp
from aiohttp import web
import security

import urllib.parse

NOTES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes_data.json")
GDRIVE_FILE = "/root/dashboard/gdrive_accounts.json"
GDRIVE_CONFIG_FILE = "/root/dashboard/gdrive_config.json"

async def get_gdrive_auth_token():
    if not os.path.exists(GDRIVE_FILE):
        return None
    try:
        with open(GDRIVE_FILE, 'r') as f:
            accounts = json.load(f)
        if not accounts:
            return None
        acc = accounts[0]
        
        expires_at = acc.get("expires_at", 0)
        if time.time() < (expires_at - 120):
            return acc.get("access_token")
            
        refresh_token = acc.get("refresh_token")
        if not refresh_token:
            return acc.get("access_token")
            
        if not os.path.exists(GDRIVE_CONFIG_FILE):
            return acc.get("access_token")
        with open(GDRIVE_CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
            
        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": cfg.get("client_id"),
            "client_secret": cfg.get("client_secret"),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, data=payload) as resp:
                if resp.status == 200:
                    token_data = await resp.json()
                    new_access_token = token_data.get("access_token")
                    new_expires_in = token_data.get("expires_in", 3600)
                    acc["access_token"] = new_access_token
                    acc["expires_at"] = time.time() + new_expires_in
                    
                    for i, a in enumerate(accounts):
                        if a.get("id") == acc.get("id"):
                            accounts[i] = acc
                            break
                    with open(GDRIVE_FILE, 'w') as f:
                        json.dump(accounts, f, indent=2)
                    return new_access_token
    except Exception as e:
        print(f"Error in notes manager GDrive token refresh: {e}")
    return None

async def find_gdrive_file_id(access_token, filename):
    query = f"name = '{filename}' and trashed = false"
    url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(query)}&fields=files(id)"
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {access_token}"}
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    files = data.get("files", [])
                    if files:
                        return files[0].get("id")
    except Exception as e:
        print(f"Error finding GDrive file id: {e}")
    return None

async def upload_to_gdrive(access_token, file_id, filename, content_bytes):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with aiohttp.ClientSession() as session:
            if file_id:
                url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
                headers["Content-Type"] = "application/json"
                async with session.patch(url, headers=headers, data=content_bytes) as resp:
                    return resp.status in [200, 201]
            else:
                url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
                boundary = "foo_bar_baz"
                headers["Content-Type"] = f"multipart/related; boundary={boundary}"
                
                metadata = {"name": filename, "mimeType": "application/json"}
                body = (
                    f"--{boundary}\r\n"
                    f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                    f"{json.dumps(metadata)}\r\n"
                    f"--{boundary}\r\n"
                    f"Content-Type: application/json\r\n\r\n"
                ).encode("utf-8") + content_bytes + f"\r\n--{boundary}--".encode("utf-8")
                
                async with session.post(url, headers=headers, data=body) as resp:
                    return resp.status in [200, 201]
    except Exception as e:
        print(f"Error uploading to GDrive: {e}")
    return False

async def archive_notes_flow():
    access_token = await get_gdrive_auth_token()
    if not access_token:
        return False, "Google Drive no configurado o no autenticado"
        
    notes = load_notes()
    now = time.time()
    local_notes = []
    to_archive = []
    
    for note in notes:
        is_old = (now - note.get("created_at", now)) > (7 * 24 * 3600)
        if note.get("completed") or is_old:
            to_archive.append(note)
        else:
            local_notes.append(note)
            
    if not to_archive:
        return True, "No hay notas para archivar"
        
    file_id = await find_gdrive_file_id(access_token, "notes_archive.json")
    archived_notes = []
    if file_id:
        download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {access_token}"}
                async with session.get(download_url, headers=headers) as resp:
                    if resp.status == 200:
                        archived_notes = await resp.json()
        except Exception as e:
            print(f"Error downloading existing notes archive: {e}")
            
    existing_ids = {n["id"] for n in archived_notes}
    added_count = 0
    for note in to_archive:
        if note["id"] not in existing_ids:
            archived_notes.append(note)
            added_count += 1
            
    archive_bytes = json.dumps(archived_notes, indent=2, ensure_ascii=False).encode("utf-8")
    success = await upload_to_gdrive(access_token, file_id, "notes_archive.json", archive_bytes)
    
    if success:
        save_notes(local_notes)
        return True, f"Se archivaron {added_count} notas en Google Drive exitosamente."
    else:
        return False, "Error al subir el archivo de respaldo a Google Drive"

async def archive_logs_flow():
    access_token = await get_gdrive_auth_token()
    if not access_token:
        return False, "Google Drive no configurado o no autenticado"
        
    pm2_out = "/root/.pm2/logs/dashboard-out.log"
    pm2_err = "/root/.pm2/logs/dashboard-error.log"
    
    success_count = 0
    for log_path, name in [(pm2_out, "pm2_out_archive.log"), (pm2_err, "pm2_err_archive.log")]:
        if not os.path.exists(log_path):
            continue
            
        try:
            size = os.path.getsize(log_path)
            if size == 0:
                continue
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading log {log_path}: {e}")
            continue
            
        filename = f"motoserver_{name}"
        file_id = await find_gdrive_file_id(access_token, filename)
        existing_content = ""
        if file_id:
            download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
            try:
                async with aiohttp.ClientSession() as session:
                    headers = {"Authorization": f"Bearer {access_token}"}
                    async with session.get(download_url, headers=headers) as resp:
                        if resp.status == 200:
                            existing_content = await resp.text()
            except:
                pass
                
        merged = existing_content + "\n" + content
        if len(merged) > 1 * 1024 * 1024:
            merged = merged[-1 * 1024 * 1024:]
            
        success = await upload_to_gdrive(access_token, file_id, filename, merged.encode("utf-8"))
        if success:
            try:
                with open(log_path, "w", encoding="utf-8") as f:
                    f.truncate(0)
                success_count += 1
            except:
                pass
    return True, f"Se respaldaron y vaciaron {success_count} archivos de log locales."

_notes_cache = None
_notes_cache_mtime = 0.0

def load_notes():
    global _notes_cache, _notes_cache_mtime
    if not os.path.exists(NOTES_FILE):
        return []
    try:
        mtime = os.path.getmtime(NOTES_FILE)
        if _notes_cache is not None and mtime == _notes_cache_mtime:
            return _notes_cache
            
        with open(NOTES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            _notes_cache = data
            _notes_cache_mtime = mtime
            return data
    except Exception as e:
        print(f"Error loading notes: {e}")
        if _notes_cache is not None:
            return _notes_cache
        return []

def save_notes(notes):
    try:
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            json.dump(notes, f, indent=2, ensure_ascii=False)
        try:
            os.chmod(NOTES_FILE, 0o600)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"Error saving notes: {e}")
        return False

# =====================================================================
# TELEGRAM REMINDER DISPATCHER
# =====================================================================
async def send_telegram_reminder(note):
    cfg = security.load_config()
    token = cfg.get("bot_token")
    chats = cfg.get("admin_chat_ids", [])
    if not token or not chats:
        return False

    title = note.get("title", "Sin Título")
    content = note.get("content", "").strip()
    drawing_b64 = note.get("drawing_data")
    created_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(note.get("created_at", time.time())))

    caption_text = (
        f"⏰ <b>RECORDATORIO PROGRAMADO</b>\n\n"
        f"📌 <b>{title}</b>\n"
    )
    if content:
        caption_text += f"\n📝 <i>{content}</i>\n"
    caption_text += f"\n🗓️ <b>Creado:</b> {created_str}\n🌐 MotoServer • Motorola One"

    async with aiohttp.ClientSession() as session:
        for chat_id in chats:
            try:
                # If drawing attached, send as photo
                if drawing_b64 and "base64," in drawing_b64:
                    raw_b64 = drawing_b64.split("base64,", 1)[1]
                    photo_bytes = base64.b64decode(raw_b64)
                    
                    form = aiohttp.FormData()
                    form.add_field("chat_id", str(chat_id))
                    form.add_field("photo", photo_bytes, filename="nota_dibujo.png", content_type="image/png")
                    form.add_field("caption", caption_text)
                    form.add_field("parse_mode", "HTML")
                    
                    url = f"https://api.telegram.org/bot{token}/sendPhoto"
                    async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            # Fallback to plain text message
                            await session.post(
                                f"https://api.telegram.org/bot{token}/sendMessage",
                                json={"chat_id": chat_id, "text": caption_text, "parse_mode": "HTML"},
                                timeout=aiohttp.ClientTimeout(total=5)
                            )
                else:
                    # Pure text message
                    await session.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": caption_text, "parse_mode": "HTML"},
                        timeout=aiohttp.ClientTimeout(total=5)
                    )
            except Exception as e:
                print(f"Error sending reminder to chat {chat_id}: {e}")

    return True

async def reminder_worker_loop():
    print("⏰ MotoServer Reminder Daemon Started", flush=True)
    last_archive_day = None
    while True:
        try:
            now = time.time()
            
            # Auto-archive at 3 AM daily
            local_time = time.localtime(now)
            if local_time.tm_hour == 3 and local_time.tm_mday != last_archive_day:
                print("⏰ Auto-Archiver: Running scheduled daily backup to Google Drive...", flush=True)
                asyncio.create_task(archive_notes_flow())
                asyncio.create_task(archive_logs_flow())
                last_archive_day = local_time.tm_mday
                
            notes = load_notes()
            changed = False
            for note in notes:
                rem_time = note.get("reminder_time")
                rem_tg = note.get("reminder_telegram", False)
                rem_sent = note.get("reminder_sent", False)
                completed = note.get("completed", False)

                if rem_tg and not rem_sent and not completed and rem_time and now >= rem_time:
                    print(f"🔔 Dispatched reminder for note: {note.get('title')}", flush=True)
                    asyncio.create_task(send_telegram_reminder(note))
                    note["reminder_sent"] = True
                    note["reminder_sent_at"] = now
                    changed = True

            if changed:
                save_notes(notes)
        except Exception as e:
            print(f"Error in reminder worker loop: {e}", flush=True)

        await asyncio.sleep(15)

# =====================================================================
# API HANDLERS
# =====================================================================
async def api_notes_list(request):
    notes = load_notes()
    # Sort: active reminders first, then by updated_at desc
    notes.sort(key=lambda n: (n.get("completed", False), -(n.get("updated_at", 0))))
    return web.json_response({"success": True, "notes": notes})

async def api_notes_save(request):
    try:
        data = await request.json()
        notes = load_notes()
        note_id = data.get("id")
        
        now = time.time()
        title = data.get("title", "").strip() or "Nota sin título"
        content = data.get("content", "").strip()
        drawing_data = data.get("drawing_data", "")
        color = data.get("color", "blue")
        tags = data.get("tags", [])
        
        reminder_time = data.get("reminder_time") # Epoch timestamp in seconds or None
        reminder_telegram = bool(data.get("reminder_telegram", True))
        
        if note_id:
            # Update existing note
            found = False
            for note in notes:
                if note["id"] == note_id:
                    note["title"] = title
                    note["content"] = content
                    note["drawing_data"] = drawing_data
                    note["color"] = color
                    note["tags"] = tags
                    
                    # If reminder time was updated, reset reminder_sent
                    if note.get("reminder_time") != reminder_time:
                        note["reminder_time"] = reminder_time
                        note["reminder_sent"] = False
                    
                    note["reminder_telegram"] = reminder_telegram
                    note["updated_at"] = now
                    found = True
                    saved_note = note
                    break
            if not found:
                return web.json_response({"success": False, "error": "Nota no encontrada"}, status=404)
        else:
            # Create new note
            new_id = f"note_{int(now)}_{uuid.uuid4().hex[:6]}"
            saved_note = {
                "id": new_id,
                "title": title,
                "content": content,
                "drawing_data": drawing_data,
                "color": color,
                "tags": tags,
                "reminder_time": reminder_time,
                "reminder_telegram": reminder_telegram,
                "reminder_sent": False,
                "completed": False,
                "created_at": now,
                "updated_at": now
            }
            notes.insert(0, saved_note)

        save_notes(notes)
        return web.json_response({"success": True, "note": saved_note})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_notes_delete(request):
    try:
        data = await request.json()
        note_id = data.get("id")
        if not note_id:
            return web.json_response({"success": False, "error": "ID requerido"}, status=400)
        
        notes = load_notes()
        initial_len = len(notes)
        notes = [n for n in notes if n["id"] != note_id]
        if len(notes) == initial_len:
            return web.json_response({"success": False, "error": "Nota no encontrada"}, status=404)
        
        save_notes(notes)
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_notes_toggle_done(request):
    try:
        data = await request.json()
        note_id = data.get("id")
        if not note_id:
            return web.json_response({"success": False, "error": "ID requerido"}, status=400)
        
        notes = load_notes()
        target = None
        for n in notes:
            if n["id"] == note_id:
                n["completed"] = not n.get("completed", False)
                n["updated_at"] = time.time()
                target = n
                break
        
        if not target:
            return web.json_response({"success": False, "error": "Nota no encontrada"}, status=404)
        
        save_notes(notes)
        return web.json_response({"success": True, "completed": target["completed"]})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_notes_archive_sync(request):
    try:
        success, msg = await archive_notes_flow()
        # Also run logs archiving
        logs_success, logs_msg = await archive_logs_flow()
        return web.json_response({"success": success, "message": msg, "logs_message": logs_msg})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_notes_archive_list(request):
    try:
        access_token = await get_gdrive_auth_token()
        if not access_token:
            return web.json_response({"success": False, "error": "Google Drive no configurado o no autenticado"}, status=401)
            
        file_id = await find_gdrive_file_id(access_token, "notes_archive.json")
        if not file_id:
            return web.json_response({"success": True, "notes": []})
            
        download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {access_token}"}
            async with session.get(download_url, headers=headers) as resp:
                if resp.status == 200:
                    notes = await resp.json()
                    return web.json_response({"success": True, "notes": notes})
        return web.json_response({"success": False, "error": "Error al descargar notas desde Google Drive"}, status=500)
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_notes_archive_restore(request):
    try:
        data = await request.json()
        note_id = data.get("id")
        if not note_id:
            return web.json_response({"success": False, "error": "ID requerido"}, status=400)
            
        access_token = await get_gdrive_auth_token()
        if not access_token:
            return web.json_response({"success": False, "error": "Google Drive no configurado o no autenticado"}, status=401)
            
        file_id = await find_gdrive_file_id(access_token, "notes_archive.json")
        if not file_id:
            return web.json_response({"success": False, "error": "Archivo de notas no encontrado en Google Drive"}, status=404)
            
        download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        archived_notes = []
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {access_token}"}
            async with session.get(download_url, headers=headers) as resp:
                if resp.status == 200:
                    archived_notes = await resp.json()
                    
        target_note = next((n for n in archived_notes if n["id"] == note_id), None)
        if not target_note:
            return web.json_response({"success": False, "error": "Nota no encontrada en el archivo de Google Drive"}, status=404)
            
        archived_notes = [n for n in archived_notes if n["id"] != note_id]
        archive_bytes = json.dumps(archived_notes, indent=2, ensure_ascii=False).encode("utf-8")
        
        # Upload updated archive back to GDrive
        success = await upload_to_gdrive(access_token, file_id, "notes_archive.json", archive_bytes)
        if not success:
            return web.json_response({"success": False, "error": "Error al actualizar el archivo en Google Drive"}, status=500)
            
        # Restore locally
        target_note["completed"] = False
        target_note["created_at"] = time.time()
        target_note["updated_at"] = time.time()
        
        notes = load_notes()
        notes.insert(0, target_note)
        save_notes(notes)
        
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)
