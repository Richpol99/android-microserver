from aiohttp import web
from ytmusicapi import YTMusic
import yt_dlp
import asyncio
import logging
import time
import security
import secrets
import hashlib
import json
import os
import subprocess
os.environ['HOME'] = '/root'

logger = logging.getLogger("music")

def get_ytmusic_client():
    from ytmusicapi import YTMusic
    auth_file = "/root/dashboard/browser.json"
    if os.path.exists(auth_file):
        try:
            return YTMusic(auth_file)
        except Exception as e:
            logger.error(f"Error loading browser.json: {e}")
    return YTMusic()

ytmusic = get_ytmusic_client()

# File to store user profiles securely
USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_users.json")

# Simple in-memory cache to speed up repeated queries and bypass rate-limiting
_search_cache = {}
CACHE_EXPIRY_SECONDS = 300 # 5 minutes cache

# Temporary OTP verification store (challenge_id -> data)
_music_pending_otps = {}

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
        logger.error(f"Error saving music users: {e}")

def clean_track_title(title):
    """
    Cleans up common YouTube garbage suffixes to make titles look neat in Apple Music.
    """
    garbage_keywords = [
        "(Official Video)", "[Official Video]", "(Official Audio)", "[Official Audio]",
        "(Lyrics)", "[Lyrics]", "(Lyric Video)", "[Lyric Video]",
        "(Official Music Video)", "[Official Music Video]", "(Official)", "[Official]",
        "HD Video", "1080p", "4K", "(Slowed)", "[Slowed]"
    ]
    cleaned = title
    for kw in garbage_keywords:
        cleaned = cleaned.replace(kw, "")
        # Case insensitive check
        cleaned = cleaned.replace(kw.lower(), "")
        cleaned = cleaned.replace(kw.upper(), "")
    return cleaned.strip()

async def api_music_search(request):
    global _search_cache
    try:
        query = request.query.get("q", "").strip()
        search_filter = request.query.get("filter", "all").strip().lower()
        if not query:
            return web.json_response({"success": False, "error": "Query requerido"}, status=400)
            
        cache_key = f"{query}_{search_filter}"
        now = time.time()
        if cache_key in _search_cache:
            cache_data, cache_time = _search_cache[cache_key]
            if now - cache_time < CACHE_EXPIRY_SECONDS:
                return web.json_response({
                    "success": True, 
                    "songs": cache_data.get("songs", []), 
                    "artists": cache_data.get("artists", []),
                    "playlists": cache_data.get("playlists", []),
                    "cached": True
                })
                
        def perform_search_and_artists():
            songs = []
            artists = []
            
            def parse_tracks(results):
                parsed = []
                seen_ids = set()
                for r in results:
                    if not r or not isinstance(r, dict):
                        continue
                    video_id = r.get('videoId')
                    if not video_id or video_id in seen_ids:
                        continue
                    
                    # 1. Skip items that are too long (Max 10 minutes / 600s to filter out live sets and long mix loops)
                    duration = r.get('duration_seconds', 0)
                    if not duration:
                        duration_str = r.get('duration', '0')
                        if ':' in duration_str:
                            try:
                                parts = duration_str.split(':')
                                duration = sum(int(x) * 60 ** i for i, x in enumerate(reversed(parts)))
                            except:
                                duration = 0
                    
                    if duration > 600: # 10 minutes limit
                        continue
                        
                    raw_title = r.get('title', 'Tema Desconocido')
                    title = clean_track_title(raw_title)
                    
                    # 2. String match blacklist to exclude mixes/sets/albums
                    blacklist = ["remix", "set", "full album", "album completo", "live set", "dj set", "lofi mix", "1 hour", "2 hour", "90 min", "compilation"]
                    if any(word in title.lower() for word in blacklist):
                        continue
                        
                    seen_ids.add(video_id)
                    artists_list = r.get('artists', [])
                    if isinstance(artists_list, list) and artists_list:
                        artist = ", ".join([(a.get('name') or 'Artista') for a in artists_list if isinstance(a, dict)])
                    else:
                        artist = r.get('author', 'Artista Desconocido')
                    album_info = r.get('album')
                    album = album_info.get('name', 'Single') if isinstance(album_info, dict) else 'Single'
                    
                    thumbnails = r.get('thumbnails', [])
                    thumb = thumbnails[-1].get('url', '') if isinstance(thumbnails, list) and thumbnails else f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                    for marker in ["=w60-h60", "=w120-h120", "=s90", "=s120"]:
                        if marker in thumb:
                            thumb = thumb.replace(marker, "=w500-h500")
                            break
                    parsed.append({
                        "id": video_id,
                        "title": title,
                        "artist": artist,
                        "album": album,
                        "duration": duration,
                        "thumbnail": thumb
                    })
                return parsed

            def parse_artists(results):
                parsed = []
                for r in results:
                    if not r or not isinstance(r, dict):
                        continue
                    artist_name = r.get('artist', '') or r.get('name', 'Artista')
                    browse_id = r.get('browseId') or r.get('channelId')
                    if not browse_id:
                        continue
                    thumbnails = r.get('thumbnails', [])
                    thumb = thumbnails[-1].get('url', '') if isinstance(thumbnails, list) and thumbnails else ""
                    for marker in ["=w60-h60", "=w120-h120", "=s90", "=s120"]:
                        if marker in thumb:
                            thumb = thumb.replace(marker, "=w180-h180")
                            break
                    parsed.append({
                        "id": browse_id,
                        "name": artist_name,
                        "thumbnail": thumb
                    })
                return parsed

            def parse_playlists(results):
                parsed = []
                for r in results:
                    if not r or not isinstance(r, dict):
                        continue
                    playlist_id = r.get('browseId') or r.get('playlistId')
                    if not playlist_id:
                        continue
                    title = r.get('title', 'Playlist')
                    description = r.get('description', '') or f"De {r.get('author', 'YouTube Music')}"
                    thumbnails = r.get('thumbnails', [])
                    thumb = thumbnails[-1].get('url', '') if isinstance(thumbnails, list) and thumbnails else ""
                    parsed.append({
                        "id": playlist_id,
                        "title": title,
                        "description": description,
                        "cover": thumb
                    })
                return parsed

            playlists = []

            if search_filter == "artists":
                try:
                    res = ytmusic.search(query, filter="artists")
                    artists = parse_artists(res)
                except Exception as e:
                    logger.error(f"Artists search failed: {e}")
            elif search_filter == "songs":
                try:
                    res = ytmusic.search(query, filter="songs")
                    songs = parse_tracks(res)
                except Exception as e:
                    logger.error(f"Songs search failed: {e}")
            elif search_filter == "videos":
                try:
                    res = ytmusic.search(query, filter="videos")
                    songs = parse_tracks(res)
                except Exception as e:
                    logger.error(f"Videos search failed: {e}")
            elif search_filter == "playlists":
                try:
                    res = ytmusic.search(query, filter="playlists")
                    playlists = parse_playlists(res)
                except Exception as e:
                    logger.error(f"Playlists search failed: {e}")
            else:
                try:
                    res = ytmusic.search(query, filter="songs")
                    songs = parse_tracks(res)
                except Exception as e:
                    logger.error(f"Songs search failed: {e}")
                try:
                    res_artists = ytmusic.search(query, filter="artists")
                    artists = parse_artists(res_artists)
                except Exception as e:
                    logger.error(f"Artists search failed in 'all': {e}")
                try:
                    res_playlists = ytmusic.search(query, filter="playlists")
                    playlists = parse_playlists(res_playlists)
                except Exception as e:
                    logger.error(f"Playlists search failed in 'all': {e}")
                    
            return {"songs": songs, "artists": artists, "playlists": playlists}
            
        loop = asyncio.get_event_loop()
        search_data = await loop.run_in_executor(None, perform_search_and_artists)
        
        _search_cache[cache_key] = (search_data, now)
        
        return web.json_response({
            "success": True, 
            "songs": search_data.get("songs", []), 
            "artists": search_data.get("artists", []),
            "playlists": search_data.get("playlists", []),
            "cached": False
        })
    except Exception as e:
        logger.error(f"Error searching music: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)
# Global cache store for extracted audio stream URLs (videoId -> {url, expiry})
_resolved_url_cache = {}

async def api_music_url(request):
    try:
        video_id = request.query.get("id", "").strip()
        if not video_id:
            return web.json_response({"success": False, "error": "ID requerido"}, status=400)
            
        now = time.time()
        direct_url = None
        if video_id in _resolved_url_cache:
            cache_entry = _resolved_url_cache[video_id]
            if now < cache_entry["expiry"]:
                direct_url = cache_entry["url"]

        if not direct_url:
            def get_ydl_opts():
                ydl_opts = {
                    'format': 'ba[ext=m4a]/ba/bestaudio/best',
                    'quiet': True,
                    'no_warnings': True,
                    'skip_download': True,
                    'extract_flat': False,
                    'check_formats': False,
                    'youtube_include_dash_manifest': False,
                    'youtube_include_hls_manifest': False,
                    'nocheckcertificate': True,
                    'buffersize': 1024 * 1024,
                    'http_chunk_size': 10485760
                }
                auth_file = "/root/dashboard/browser.json"
                if os.path.exists(auth_file):
                    try:
                        with open(auth_file) as f:
                            data = json.load(f)
                            cookie_str = data.get("Cookie") or data.get("cookie")
                            if cookie_str:
                                ydl_opts['http_headers'] = {'Cookie': cookie_str}
                    except Exception as e:
                        logger.error(f"Error loading cookies: {e}")
                
                po_token_file = "/root/dashboard/po_token.json"
                if os.path.exists(po_token_file):
                    try:
                        with open(po_token_file) as f:
                            po_data = json.load(f)
                            if "po_token" in po_data and "visitor_data" in po_data:
                                if 'extractor_args' not in ydl_opts:
                                    ydl_opts['extractor_args'] = {}
                                if 'youtube' not in ydl_opts['extractor_args']:
                                    ydl_opts['extractor_args']['youtube'] = {}
                                ydl_opts['extractor_args']['youtube'].update({
                                    'po_token': [f"{po_data['visitor_data']}:{po_data['po_token']}"]
                                })
                    except Exception as e:
                        logger.error(f"Error loading po_token: {e}")
                return ydl_opts

            def extract_url():
                with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                    return info.get('url')

            try:
                loop = asyncio.get_event_loop()
                direct_url = await loop.run_in_executor(None, extract_url)
                if direct_url:
                    _resolved_url_cache[video_id] = {
                        "url": direct_url,
                        "expiry": now + 1200
                    }
            except Exception as e:
                logger.error(f"Error resolving direct stream URL: {e}")

        fallback_proxy_url = f"/api/music/stream?id={video_id}&proxy=true"
        return web.json_response({
            "success": True, 
            "url": direct_url or fallback_proxy_url,
            "direct_url": direct_url,
            "proxy_url": fallback_proxy_url
        })
    except Exception as e:
        logger.error(f"Error extracting audio URL: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

_gdrive_cached_songs = set()
_last_gdrive_cache_sync = 0

async def sync_gdrive_cache_list():
    global _gdrive_cached_songs, _last_gdrive_cache_sync
    now = time.time()
    if now - _last_gdrive_cache_sync < 60:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "rclone", "lsf", "gdrive:music_cache/",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            lines = stdout.decode().splitlines()
            new_cache = set()
            for line in lines:
                if line.endswith(".m4a"):
                    video_id = line[:-4]
                    new_cache.add(video_id)
            _gdrive_cached_songs = new_cache
            _last_gdrive_cache_sync = now
            logger.info(f"Synced Google Drive cache. Found {len(_gdrive_cached_songs)} cached songs.")
    except Exception as e:
        logger.error(f"Error syncing Google Drive cache list: {e}")

_active_downloads = set()

async def cache_song_to_gdrive(video_id, title=None, artist=None):
    if video_id in _gdrive_cached_songs or video_id in _active_downloads:
        return
    _active_downloads.add(video_id)
    try:
        # Fetch metadata locally on the phone's safe residential IP
        if not title or not artist:
            try:
                ytmusic = get_ytmusic_client()
                loop = asyncio.get_event_loop()
                song_info = await loop.run_in_executor(None, lambda: ytmusic.get_song(video_id))
                title = song_info.get("videoDetails", {}).get("title", "")
                artist = song_info.get("videoDetails", {}).get("author", "")
            except Exception as e:
                logger.error(f"Failed to fetch metadata on phone: {e}")

        # Search for alternative audio/lyrics version directly
        target_id = video_id
        if title and artist:
            logger.info(f"Searching alternative audio version for {artist} - {title} locally on phone...")
            try:
                ytmusic = get_ytmusic_client()
                loop = asyncio.get_event_loop()
                def search_alt():
                    return ytmusic.search(f"{artist} {title} audio", filter="songs")
                search_results = await loop.run_in_executor(None, search_alt)
                if search_results and isinstance(search_results, list):
                    valid_results = [r for r in search_results if r.get("videoId") != video_id]
                    if valid_results:
                        target_id = valid_results[0].get("videoId")
                        logger.info(f"Alternative ID resolved (filtered): {target_id}")
            except Exception as se:
                logger.error(f"Error performing forced alternative search: {se}")

        import aiohttp
        import urllib.parse
        
        enc_t = urllib.parse.quote(title or "")
        enc_a = urllib.parse.quote(artist or "")
        worker_url = f"https://moto-music-worker.onrender.com/cache?id={video_id}&source_id={target_id}&title={enc_t}&artist={enc_a}"
        
        logger.info(f"Delegating song caching of {video_id} (using source {target_id}) to Render cloud worker...")
        timeout = aiohttp.ClientTimeout(total=180)
        success = False
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(worker_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success"):
                        success = True

        if success:
            logger.info(f"Successfully cached song {video_id} to Google Drive via Render!")
            _gdrive_cached_songs.add(video_id)
        else:
            logger.error(f"Render worker failed to cache {video_id}")
    except Exception as e:
        logger.error(f"Error calling Render worker for {video_id}: {e}")
    finally:
        _active_downloads.discard(video_id)

async def api_music_stream(request):
    video_id = request.query.get("id", "").strip()
    if not video_id:
        return web.Response(status=400, text="ID requerido")

    proxy_bytes = request.query.get("proxy", "").strip().lower() in ("true", "1")
    if proxy_bytes:
        logger.info(f"Ultra-fast turbo download for {video_id} directly to disk...")
        cache_dir = "/root/dashboard/temp_music_cache"
        os.makedirs(cache_dir, exist_ok=True)
        cached_file = os.path.join(cache_dir, f"{video_id}.m4a")

        # Auto-cleanup routine: Keep cache strictly under 500 MB / oldest files removed automatically
        try:
            files = [os.path.join(cache_dir, f) for f in os.listdir(cache_dir) if f.endswith('.m4a')]
            total_size = sum(os.path.getsize(f) for f in files if os.path.isfile(f))
            if total_size > 500 * 1024 * 1024: # 500 MB max threshold
                files.sort(key=lambda x: os.path.getmtime(x))
                while files and total_size > 300 * 1024 * 1024:
                    oldest = files.pop(0)
                    if os.path.exists(oldest):
                        sz = os.path.getsize(oldest)
                        os.remove(oldest)
                        total_size -= sz
        except Exception as cl_err:
            logger.error(f"Cache cleanup error: {cl_err}")

        if not os.path.exists(cached_file) or os.path.getsize(cached_file) == 0:
            def download_fast():
                ydl_opts = {
                    'format': 'ba[ext=m4a]/ba/bestaudio/best',
                    'outtmpl': cached_file,
                    'quiet': True,
                    'no_warnings': True,
                    'nocheckcertificate': True
                }
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
                except Exception as dl_ex:
                    # If age-restricted or format unavailable, resolve alternative audio track automatically
                    logger.warn(f"Direct ID {video_id} restricted ({dl_ex}), searching alternative audio track...")
                    try:
                        ytmusic = get_ytmusic_client()
                        song_info = ytmusic.get_song(video_id)
                        title = song_info.get("videoDetails", {}).get("title", "")
                        artist = song_info.get("videoDetails", {}).get("author", "")
                        if title and artist:
                            search_res = ytmusic.search(f"{artist} {title} audio", filter="songs")
                            if search_res and isinstance(search_res, list):
                                alt_id = search_res[0].get("videoId")
                                if alt_id and alt_id != video_id:
                                    logger.info(f"Downloading alternative track: {alt_id} for {title}")
                                    with yt_dlp.YoutubeDL(ydl_opts) as ydl_alt:
                                        ydl_alt.download([f"https://www.youtube.com/watch?v={alt_id}"])
                    except Exception as alt_err:
                        logger.error(f"Alternative resolution failed: {alt_err}")

            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, download_fast)
            except Exception as dl_err:
                logger.error(f"yt-dlp fast download error: {dl_err}")

        if os.path.exists(cached_file) and os.path.getsize(cached_file) > 0:
            return web.FileResponse(
                cached_file,
                headers={
                    "Content-Type": "audio/mp4",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Expose-Headers": "Content-Length, Content-Type, Accept-Ranges",
                    "Accept-Ranges": "bytes"
                }
            )
        else:
            return web.Response(status=500, text="Error procesando pista")
    else:
        # Redirect the client's browser directly to the YouTube stream URL
        logger.info(f"Redirecting client directly to YouTube stream URL for {video_id} to bypass server proxying...")
        return web.HTTPFound(url)


async def api_music_auth_login(request):
    try:
        data = await request.json()
        username = data.get("username", "").strip().lower()
        password = data.get("password", "")
        
        if not username or not password:
            return web.json_response({"success": False, "error": "Usuario y contraseña requeridos"}, status=400)
            
        users = load_music_users()
        if username not in users:
            return web.json_response({"success": False, "error": "El usuario no existe"}, status=401)
            
        user_data = users[username]
        pass_hash = hashlib.sha256(password.encode()).hexdigest()
        if not secrets.compare_digest(pass_hash, user_data.get("password_hash", "")):
            return web.json_response({"success": False, "error": "Contraseña incorrecta"}, status=401)
            
        session_token = secrets.token_urlsafe(24)
        
        response = web.json_response({
            "success": True,
            "username": username,
            "artists": user_data.get("artists", []),
            "session_token": session_token
        })
        response.set_cookie("motomusic_session", session_token, max_age=30*86400, path="/", httponly=False, samesite="Lax")
        response.set_cookie("motomusic_username", username, max_age=30*86400, path="/", httponly=False, samesite="Lax")
        
        return response
    except Exception as e:
        logger.error(f"Error logging in music profile: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_auth_step1(request):
    try:
        data = await request.json()
        username = data.get("username", "").strip().lower()
        password = data.get("password", "")
        
        if not username or not password:
            return web.json_response({"success": False, "error": "Usuario y contraseña son requeridos"}, status=400)
            
        # Ensure user doesn't already exist
        users = load_music_users()
        if username in users:
            return web.json_response({"success": False, "error": "El nombre de usuario ya está registrado"}, status=400)
            
        # Validate Master Password
        cfg = security.load_config()
        pass_hash = hashlib.sha256(password.encode()).hexdigest()
        if not secrets.compare_digest(pass_hash, cfg.get("master_password_hash", "")):
            return web.json_response({"success": False, "error": "Contraseña maestra incorrecta"}, status=401)
            
        # Generate 2FA OTP
        otp = f"{secrets.randbelow(900000) + 100000}"
        challenge_id = secrets.token_urlsafe(16)
        
        _music_pending_otps[challenge_id] = {
            "otp": otp,
            "username": username,
            "expires_at": time.time() + 180
        }
        
        telegram_message = (
            f"🎵 <b>MOTO MUSIC: REGISTRO DE PERFIL</b>\n\n"
            f"Se ha solicitado un registro para el nuevo perfil: <b>{username}</b>\n"
            f"🔑 <b>Código OTP:</b> <code>{otp}</code>\n\n"
            f"⏱️ <i>Válido por 3 minutos.</i>"
        )
        asyncio.create_task(security.send_telegram_message(telegram_message))
        
        return web.json_response({
            "success": True,
            "challenge_id": challenge_id,
            "expires_in": 180
        })
    except Exception as e:
        logger.error(f"Error in music auth step 1: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_auth_step2(request):
    try:
        data = await request.json()
        challenge_id = data.get("challenge_id", "").strip()
        otp = data.get("otp", "").strip()
        username = data.get("username", "").strip().lower()
        personal_password = data.get("personal_password", "")
        artists = data.get("artists", [])
        
        if not challenge_id or not otp or not username or not personal_password or not isinstance(artists, list) or len(artists) < 3:
            return web.json_response({"success": False, "error": "Datos incompletos para el registro"}, status=400)
            
        if challenge_id not in _music_pending_otps:
            return web.json_response({"success": False, "error": "Solicitud de verificación inválida o expirada"}, status=400)
            
        ch = _music_pending_otps[challenge_id]
        
        if time.time() > ch["expires_at"]:
            del _music_pending_otps[challenge_id]
            return web.json_response({"success": False, "error": "Código OTP expirado"}, status=400)
            
        if ch["otp"] != otp or ch["username"] != username:
            return web.json_response({"success": False, "error": "Código OTP incorrecto"}, status=401)
            
        del _music_pending_otps[challenge_id]
        
        # Save profile
        users = load_music_users()
        personal_pass_hash = hashlib.sha256(personal_password.encode()).hexdigest()
        users[username] = {
            "password_hash": personal_pass_hash,
            "artists": [a.strip() for a in artists]
        }
        save_music_users(users)
        
        session_token = secrets.token_urlsafe(24)
        
        response = web.json_response({
            "success": True,
            "username": username,
            "artists": artists,
            "session_token": session_token
        })
        response.set_cookie("motomusic_session", session_token, max_age=30*86400, path="/", httponly=False, samesite="Lax")
        response.set_cookie("motomusic_username", username, max_age=30*86400, path="/", httponly=False, samesite="Lax")
        
        return response
    except Exception as e:
        logger.error(f"Error in music auth step 2: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

def make_svg_cover(title, gradient_from, gradient_to):
    import urllib.parse
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300" width="300" height="300">
        <defs>
            <linearGradient id="glow" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="{gradient_from}"/>
                <stop offset="100%" stop-color="{gradient_to}"/>
            </linearGradient>
            <clipPath id="circleClip">
                <circle cx="150" cy="110" r="65" />
            </clipPath>
        </defs>
        
        <!-- Deep Spotify Dark Textured Background -->
        <rect width="100%" height="100%" fill="#121212"/>
        
        <!-- Abstract gradient fluid sphere background -->
        <circle cx="150" cy="110" r="70" fill="url(#glow)" opacity="0.85" filter="blur(8px)" />
        <circle cx="150" cy="110" r="65" fill="#18181b"/>
        
        <!-- Integrated Musical Icon -->
        <path d="M152 75v42c-2.5-1.5-6-2.5-9.5-1.2-5 1.8-7 6.5-4.5 10.5s7.5 5 12.5 3.2c3-1 5.5-4.2 5.5-7V88h22v-13z" fill="url(#glow)"/>
        
        <!-- Minimalist typography layout -->
        <rect x="25" y="195" width="250" height="2" fill="url(#glow)" opacity="0.8"/>
        
        <text x="50%" y="225" font-family="'Montserrat', 'Inter', -apple-system, sans-serif" font-size="20" font-weight="900" fill="#ffffff" text-anchor="middle" letter-spacing="0.5">{title.upper()}</text>
        <text x="50%" y="250" font-family="'Inter', -apple-system, sans-serif" font-size="9" font-weight="700" fill="url(#glow)" text-anchor="middle" letter-spacing="3">DAILY MIX</text>
    </svg>"""
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)

async def api_music_recommendations(request):
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        if not username:
            return web.json_response({"success": False, "error": "No hay sesión activa"}, status=401)
            
        users = load_music_users()
        if username not in users:
            return web.json_response({"success": False, "error": "Usuario no registrado"}, status=401)
            
        user_data = users[username]
        artists = user_data.get("artists", [])
        if not artists or len(artists) < 3:
            return web.json_response({"success": False, "error": "El usuario debe tener al menos 3 artistas favoritos"}, status=400)
            
        # Parse favorites, recents, and hour from request body (optional POST)
        favorites = []
        recents = []
        import datetime
        hour = datetime.datetime.now().hour
        if request.method == "POST":
            try:
                post_data = await request.json()
                favorites = post_data.get("favorites", [])
                recents = post_data.get("recents", [])
                hour = post_data.get("hour", hour)
            except:
                pass

        # Define active Vibe based on local Hour
        if 6 <= hour < 12:
            vibe_title = "Mix de Energía"
            vibe_desc = "Temas enérgicos e inspiradores para empezar tu mañana."
            vibe_g1, vibe_g2 = "#ff5e62", "#ff9966"
            vibe_search_suffix = " upbeat rock pop"
            vibe_genre_query = "rock classics upbeat hits"
        elif 12 <= hour < 18:
            vibe_title = "Mix de Enfoque"
            vibe_desc = "Música perfecta para concentrarte y estudiar por la tarde."
            vibe_g1, vibe_g2 = "#11998e", "#38ef7d"
            vibe_search_suffix = " lofi chill instrumental"
            vibe_genre_query = "lofi hip hop study beats"
        elif 18 <= hour < 24:
            vibe_title = "Mix de Tarde Relajada"
            vibe_desc = "Melodías acústicas y suaves para desconectar por la noche."
            vibe_g1, vibe_g2 = "#8a2387", "#e94057"
            vibe_search_suffix = " acoustic acoustic chill"
            vibe_genre_query = "indie folk acoustic"
        else:
            vibe_title = "Mix de Medianoche"
            vibe_desc = "Canciones profundas y ambientales para descansar."
            vibe_g1, vibe_g2 = "#0f2027", "#203a43"
            vibe_search_suffix = " sleep ambient deep lofi"
            vibe_genre_query = "sleep ambient piano sounds"

        playlists = []
        songs = []

        # Helper to fetch artist songs from YTM API
        async def fetch_artist_songs(artist_name, limit=8):
            try:
                def run_search():
                    return ytmusic.search(artist_name, filter="songs")
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(None, run_search)
                if not results:
                    results = []
                artist_songs = []
                for r in results:
                    if not r or not isinstance(r, dict):
                        continue
                    video_id = r.get('videoId')
                    if not video_id:
                        continue
                        
                    duration = r.get('duration_seconds', 0)
                    if duration > 600: # 10 minutes limit
                        continue
                        
                    title = clean_track_title(r.get('title', ''))
                    
                    # Skip remixes and sets
                    blacklist = ["remix", "set", "full album", "album completo", "live set", "dj set", "lofi mix", "1 hour", "2 hour", "90 min", "compilation"]
                    if any(word in title.lower() for word in blacklist):
                        continue
                        
                    artists_list = r.get('artists', [])
                    artists_str = ", ".join([(a.get('name') or 'Artista') for a in artists_list if isinstance(a, dict)])
                    thumbnails = r.get('thumbnails', [])
                    thumb = thumbnails[-1].get('url', '') if thumbnails else f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                    if thumb and "=w60-h60" in thumb:
                        thumb = thumb.replace("=w60-h60", "=w500-h500")
                    elif thumb and "=w120-h120" in thumb:
                        thumb = thumb.replace("=w120-h120", "=w500-h500")
                        
                    artist_songs.append({
                        "id": video_id,
                        "title": title,
                        "artist": artists_str,
                        "album": r.get('album', {}).get('name', 'Single') if r.get('album') else 'Single',
                        "duration": duration,
                        "thumbnail": thumb
                    })
                    
                    if len(artist_songs) >= limit:
                        break
                return artist_songs
            except Exception as e:
                logger.error(f"Error fetching recommendations for artist {artist_name}: {e}")
                return []

        # Helper to fetch artist details and their related artists for multi-artist mixes
        async def fetch_artist_mix_songs(artist_name):
            main_songs = await fetch_artist_songs(artist_name, limit=5)
            try:
                def get_related_names():
                    try:
                        search_results = ytmusic.search(artist_name, filter="artists")
                        if not search_results:
                            return []
                        browse_id = search_results[0].get("browseId")
                        if not browse_id:
                            return []
                        artist_data = ytmusic.get_artist(browse_id)
                        related_results = artist_data.get("related", {}).get("results", [])
                        return [(r.get("title") or r.get("name")) for r in related_results[:2] if r.get("title") or r.get("name")]
                    except Exception as ex:
                        logger.error(f"Failed to get related artists names for {artist_name}: {ex}")
                        return []
                loop = asyncio.get_event_loop()
                related_names = await loop.run_in_executor(None, get_related_names)
            except:
                related_names = []
                
            related_songs_list = []
            if related_names:
                related_tasks = [fetch_artist_songs(name, limit=3) for name in related_names]
                related_songs_list = await asyncio.gather(*related_tasks)
                
            combined = []
            max_len = max(len(main_songs), *(len(lst) for lst in related_songs_list)) if related_songs_list else len(main_songs)
            for i in range(max_len):
                if i < len(main_songs):
                    combined.append(main_songs[i])
                for lst in related_songs_list:
                    if i < len(lst):
                        combined.append(lst[i])
            return combined

        # Fetch artist mixes for ALL selected artists dynamically, plus contextual vibe songs
        mix_tasks = [fetch_artist_mix_songs(artist) for artist in artists]
        vibe_tasks = [
            fetch_artist_songs(artists[2] + vibe_search_suffix if len(artists) > 2 else artists[0] + vibe_search_suffix),
            fetch_artist_songs(vibe_genre_query, limit=6)
        ]
        
        all_results = await asyncio.gather(*(mix_tasks + vibe_tasks))
        
        # Split results
        artist_results = all_results[:len(artists)]
        vibe_songs = all_results[len(artists)] if len(all_results) > len(artists) else []
        genre_songs = all_results[len(artists) + 1] if len(all_results) > len(artists) + 1 else []
        
        # 1. Append Mix playlists for each artist dynamically
        for idx, artist in enumerate(artists):
            art_songs = artist_results[idx]
            if art_songs:
                # Deterministic color selection for the covers
                gradients = [
                    ("#fc3c44", "#9b000e"),
                    ("#007aff", "#00259b"),
                    ("#34c759", "#0e6b24"),
                    ("#af52de", "#581b7a"),
                    ("#ff9500", "#9b5500")
                ]
                g_c1, g_c2 = gradients[idx % len(gradients)]
                playlists.append({
                    "id": f"mix_{artist.lower().replace(' ', '_')}",
                    "title": f"Mix de {artist} y rel.",
                    "description": f"Temas de {artist} y artistas similares.",
                    "cover": make_svg_cover(artist, g_c1, g_c2),
                    "songs": art_songs
                })

        # 2. Playlist: Temporal Vibe Contextual Mix (Discovery!)
        combined_vibe_songs = []
        for i in range(max(len(vibe_songs), len(genre_songs))):
            if i < len(vibe_songs): combined_vibe_songs.append(vibe_songs[i])
            if i < len(genre_songs): combined_vibe_songs.append(genre_songs[i])

        if combined_vibe_songs:
            playlists.append({
                "id": "mix_temporal_vibe",
                "title": vibe_title,
                "description": vibe_desc,
                "cover": make_svg_cover(vibe_title, vibe_g1, vibe_g2),
                "songs": combined_vibe_songs
            })

        # Playlist 4: Mi Mix Diario (Dynamic Radio based on Local History + YouTube Music watch playlist)
        daily_songs = []
        
        # Extract high-scoring seeds from user history
        user_history = user_data.get("history", {})
        high_score_seeds = [tid for tid, info in user_history.items() if info.get("score", 0) > 0]
        
        # Fallback to favorites if no history scores exist
        if not high_score_seeds and favorites:
            high_score_seeds = [f.get("id") for f in favorites if f.get("id")]
            
        if high_score_seeds:
            import random
            # Select up to 3 random seeds from favorites/history to fetch recommendations
            selected_seeds = random.sample(high_score_seeds, min(3, len(high_score_seeds)))
            
            async def fetch_radio_songs(video_id):
                try:
                    def run_radio():
                        return ytmusic.get_watch_playlist(videoId=video_id)
                    loop = asyncio.get_event_loop()
                    radio_data = await loop.run_in_executor(None, run_radio)
                    if not radio_data:
                        radio_data = {}
                    tracks = radio_data.get("tracks", [])
                    if not tracks:
                        tracks = []
                    radio_songs = []
                    for t in tracks[:8]:
                        if not t or not isinstance(t, dict):
                            continue
                        vid_id = t.get("videoId")
                        if not vid_id or vid_id == video_id:
                            continue
                        title = clean_track_title(t.get("title", ""))
                        artists_list = t.get("artists", [])
                        artists_str = ", ".join([(a.get("name") or "Artista") for a in artists_list if isinstance(a, dict)])
                        thumbnails = t.get("thumbnails", [])
                        thumb = thumbnails[-1].get("url", "") if thumbnails else f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
                        if thumb and "=w60-h60" in thumb:
                            thumb = thumb.replace("=w60-h60", "=w500-h500")
                        elif thumb and "=w120-h120" in thumb:
                            thumb = thumb.replace("=w120-h120", "=w500-h500")
                            
                        radio_songs.append({
                            "id": vid_id,
                            "title": title,
                            "artist": artists_str,
                            "album": t.get("album", {}).get("name", "Single") if t.get("album") else "Single",
                            "duration": t.get("length", 0) or 0,
                            "thumbnail": thumb
                        })
                    return radio_songs
                except Exception as e:
                    logger.error(f"Error fetching watch playlist radio for {video_id}: {e}")
                    return []
            
            radio_tasks = [fetch_radio_songs(sid) for sid in selected_seeds]
            radio_results = await asyncio.gather(*radio_tasks)
            
            # Interleave results from the selected seeds
            interleaved_daily = []
            max_radio_len = max((len(lst) for lst in radio_results), default=0)
            for i in range(max_radio_len):
                for lst in radio_results:
                    if i < len(lst):
                        interleaved_daily.append(lst[i])
            daily_songs = interleaved_daily[:15]
            
        if not daily_songs:
            # Fallback using tracks from first resolved artist results
            daily_songs = artist_results[0][:8] if (artist_results and len(artist_results) > 0) else []
            
        if daily_songs:
            playlists.append({
                "id": "mix_daily",
                "title": "Mi Mix Diario",
                "description": "Una mezcla diaria personalizada basada en tus gustos locales.",
                "cover": make_svg_cover("Mix Diario", "#34c759", "#0c611f"),
                "songs": daily_songs
            })

        # Playlist 5, 6, 7: Genre Playlists (Cached)
        global _genre_playlists_cache, _genre_cache_time
        now_time = datetime.datetime.now()
        if not _genre_playlists_cache or not _genre_cache_time or (now_time - _genre_cache_time).total_seconds() > 3600:
            try:
                async def fetch_genres_data():
                    genres = ["Rock Classics", "Pop Hits", "Lo-Fi Chill"]
                    genre_tasks = [fetch_artist_songs(g, limit=12) for g in genres]
                    genre_res = await asyncio.gather(*genre_tasks)
                    return {genres[i]: genre_res[i] for i in range(len(genres))}
                _genre_playlists_cache = await fetch_genres_data()
                _genre_cache_time = now_time
            except Exception as e:
                logger.error(f"Error fetching cached genre playlists: {e}")
                
        if _genre_playlists_cache:
            for genre_name, genre_songs in _genre_playlists_cache.items():
                if genre_songs:
                    if "Rock" in genre_name:
                        g1, g2 = "#7f0c0d", "#ff416c"
                    elif "Pop" in genre_name:
                        g1, g2 = "#ff007f", "#ff758c"
                    else:
                        g1, g2 = "#4b6cb7", "#182848"
                        
                    playlists.append({
                        "id": f"genre_{genre_name.lower().replace(' ', '_')}",
                        "title": f"Mix {genre_name}",
                        "description": f"Los mejores éxitos de {genre_name} seleccionados para ti.",
                        "cover": make_svg_cover(genre_name, g1, g2),
                        "songs": genre_songs
                    })

        # Interleave mixed track results to create the main dynamic feed
        max_artist_len = max((len(lst) for lst in artist_results), default=0)
        max_len = max(max_artist_len, len(combined_vibe_songs), len(daily_songs))
        for i in range(max_len):
            for art_songs in artist_results:
                if i < len(art_songs): songs.append(art_songs[i])
            if i < len(combined_vibe_songs): songs.append(combined_vibe_songs[i])
            if i < len(daily_songs): songs.append(daily_songs[i])

        # Filter out duplicates from main songs list while preserving order
        seen_ids = set()
        unique_songs = []
        for s in songs:
            if s["id"] not in seen_ids:
                seen_ids.add(s["id"])
                unique_songs.append(s)

        # 3. GLOBAL FALLBACK: If the list is empty or very short, fetch global trends & chart artists
        if len(unique_songs) < 8 or len(playlists) <= 1:
            try:
                # Resolve hot/trending artists and tracks of the moment from YouTube Music charts
                def get_trending():
                    try:
                        return ytmusic.get_charts(country="MX") # Fallback to local region trends
                    except:
                        return {}
                loop = asyncio.get_event_loop()
                charts_data = await loop.run_in_executor(None, get_trending)
                
                # Fetch tracks from trending list
                trending_tracks = charts_data.get("videos", {}).get("items", []) or charts_data.get("songs", {}).get("items", []) or []
                fallback_songs = []
                for t in trending_tracks[:12]:
                    vid_id = t.get("videoId")
                    if not vid_id or vid_id in seen_ids:
                        continue
                    title = clean_track_title(t.get("title", ""))
                    artists_list = t.get("artists", [])
                    artists_str = ", ".join([(a.get("name") or "Artista") for a in artists_list if isinstance(a, dict)])
                    thumbnails = t.get("thumbnails", [])
                    thumb = thumbnails[-1].get("url", "") if thumbnails else f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
                    fallback_songs.append({
                        "id": vid_id,
                        "title": title,
                        "artist": artists_str,
                        "album": "Éxitos del Momento",
                        "duration": t.get("length", 0) or 0,
                        "thumbnail": thumb
                    })
                    seen_ids.add(vid_id)
                
                if fallback_songs:
                    unique_songs.extend(fallback_songs)
                    playlists.append({
                        "id": "mix_trending_hits",
                        "title": "Éxitos del Momento",
                        "description": "Los artistas nuevos y las canciones que todo el mundo está escuchando ahora mismo.",
                        "cover": make_svg_cover("Top Éxitos", "#af52de", "#fc3c44"),
                        "songs": fallback_songs
                    })
            except Exception as trend_err:
                logger.error(f"Failed to fetch trending fallback recommendations: {trend_err}")

        return web.json_response({
            "success": True, 
            "songs": unique_songs,
            "playlists": playlists
        })
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_search_artists(request):
    try:
        query = request.query.get("q", "").strip()
        if not query:
            return web.json_response({"success": False, "error": "Query requerido"}, status=400)
            
        def perform_search():
            try:
                results = ytmusic.search(query, filter="artists")
            except Exception as e:
                logger.error(f"YTM artists search failed: {e}")
                results = []
            
            artists = []
            for r in results[:12]:
                artist_name = r.get('artist', '')
                if not artist_name:
                    artist_name = r.get('name', 'Artista')
                thumbnails = r.get('thumbnails', [])
                thumb = thumbnails[-1].get('url', '') if thumbnails else ""
                
                if thumb and "=w60-h60" in thumb:
                    thumb = thumb.replace("=w60-h60", "=w180-h180")
                elif thumb and "=w120-h120" in thumb:
                    thumb = thumb.replace("=w120-h120", "=w180-h180")
                
                artists.append({
                    "id": r.get('browseId') or r.get('channelId'),
                    "name": artist_name,
                    "thumbnail": thumb
                })
            return artists
            
        loop = asyncio.get_event_loop()
        artists = await loop.run_in_executor(None, perform_search)
        return web.json_response({"success": True, "artists": artists})
    except Exception as e:
        logger.error(f"Error searching artists: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_related_artists(request):
    try:
        browse_id = request.query.get("id", "").strip()
        if not browse_id:
            return web.json_response({"success": False, "error": "ID requerido"}, status=400)
            
        def get_related():
            try:
                artist_data = ytmusic.get_artist(browse_id)
                related_section = artist_data.get("related", {})
                results = related_section.get("results", [])
            except Exception as e:
                logger.error(f"YTM get_artist failed: {e}")
                results = []
                
            artists = []
            for r in results[:4]:
                artist_name = r.get('title', '')
                if not artist_name:
                    artist_name = r.get('name', 'Artista')
                thumbnails = r.get('thumbnails', [])
                thumb = thumbnails[-1].get('url', '') if thumbnails else ""
                
                if thumb and "=w60-h60" in thumb:
                    thumb = thumb.replace("=w60-h60", "=w180-h180")
                elif thumb and "=w120-h120" in thumb:
                    thumb = thumb.replace("=w120-h120", "=w180-h180")
                    
                artists.append({
                    "id": r.get("browseId"),
                    "name": artist_name,
                    "thumbnail": thumb
                })
            return artists
            
        loop = asyncio.get_event_loop()
        related = await loop.run_in_executor(None, get_related)
        return web.json_response({"success": True, "artists": related})
    except Exception as e:
        logger.error(f"Error getting related artists: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

_genre_playlists_cache = {}
_genre_cache_time = None
_popular_artists_cache = None

async def api_music_popular_artists(request):
    try:
        global _popular_artists_cache
        if _popular_artists_cache:
            return web.json_response({"success": True, "artists": _popular_artists_cache})
            
        default_names = ["Soda Stereo", "Luis Miguel", "Daft Punk", "The Weeknd", "Coldplay", "Billie Eilish", "Queen", "Bad Bunny", "Metallica", "Dua Lipa", "Gorillaz", "Eminem", "Shakira", "Taylor Swift", "Michael Jackson", "Iron Maiden", "Bruno Mars", "Guns N' Roses"]
        
        async def resolve_artist(name):
            try:
                def run_search():
                    return ytmusic.search(name, filter="artists")
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(None, run_search)
                if results:
                    r = results[0]
                    artist_name = r.get('artist', '') or r.get('name', name)
                    thumbnails = r.get('thumbnails', [])
                    thumb = thumbnails[-1].get('url', '') if thumbnails else ""
                    if thumb and "=w60-h60" in thumb:
                        thumb = thumb.replace("=w60-h60", "=w180-h180")
                    elif thumb and "=w120-h120" in thumb:
                        thumb = thumb.replace("=w120-h120", "=w180-h180")
                    return {
                        "id": r.get('browseId') or r.get('channelId'),
                        "name": artist_name,
                        "thumbnail": thumb
                    }
            except Exception as e:
                logger.error(f"Error resolving popular artist {name}: {e}")
            return None

        tasks = [resolve_artist(name) for name in default_names]
        resolved = await asyncio.gather(*tasks)
        artists = [r for r in resolved if r]
        
        _popular_artists_cache = artists
        return web.json_response({"success": True, "artists": artists})
    except Exception as e:
        logger.error(f"Error getting popular artists: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_lyrics(request):
    try:
        video_id = request.query.get("id", "").strip()
        if not video_id:
            return web.json_response({"success": False, "error": "ID requerido"}, status=400)
            
        def fetch_lyrics():
            try:
                playlist = ytmusic.get_watch_playlist(videoId=video_id)
                lyrics_id = playlist.get("lyrics")
                if not lyrics_id:
                    return None
                lyrics_data = ytmusic.get_lyrics(lyrics_id)
                return lyrics_data.get("lyrics", "")
            except Exception as e:
                logger.error(f"Error fetching YTM lyrics: {e}")
                return None
                
        loop = asyncio.get_event_loop()
        lyrics = await loop.run_in_executor(None, fetch_lyrics)
        if not lyrics:
            return web.json_response({"success": True, "lyrics": "Letras no disponibles para este tema."})
        return web.json_response({"success": True, "lyrics": lyrics})
    except Exception as e:
        logger.error(f"Error in lyrics API: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_autoplay(request):
    try:
        video_id = request.query.get("id", "").strip()
        if not video_id:
            return web.json_response({"success": False, "error": "ID requerido"}, status=400)
            
        def fetch_watch_playlist():
            try:
                return ytmusic.get_watch_playlist(videoId=video_id)
            except Exception as e:
                logger.error(f"Error fetching watch playlist for autoplay: {e}")
                return None
                
        loop = asyncio.get_event_loop()
        playlist_data = await loop.run_in_executor(None, fetch_watch_playlist)
        if not playlist_data:
            return web.json_response({"success": True, "songs": []})
            
        tracks = playlist_data.get("tracks", [])
        if not tracks:
            return web.json_response({"success": True, "songs": []})
            
        original_artist = ""
        if tracks:
            first_artists = tracks[0].get("artists", [])
            if first_artists and isinstance(first_artists, list):
                original_artist = (first_artists[0].get("name") or "").strip().lower()

        songs = []
        for t in tracks[1:]:
            if not t or not isinstance(t, dict):
                continue
            vid_id = t.get("videoId")
            if not vid_id or vid_id == video_id:
                continue
            title = clean_track_title(t.get("title", ""))
            artists_list = t.get("artists", [])
            artists_str = ", ".join([(a.get("name") or "Artista") for a in artists_list if isinstance(a, dict)])
            
            if original_artist:
                track_first_artist = (artists_list[0].get("name") or "").strip().lower() if artists_list else ""
                if track_first_artist == original_artist:
                    continue
                    
            thumbnails = t.get("thumbnails", [])
            thumb = thumbnails[-1].get("url", "") if thumbnails else f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
            if thumb and "=w60-h60" in thumb:
                thumb = thumb.replace("=w60-h60", "=w500-h500")
            elif thumb and "=w120-h120" in thumb:
                thumb = thumb.replace("=w120-h120", "=w500-h500")
                
            songs.append({
                "id": vid_id,
                "title": title,
                "artist": artists_str,
                "album": t.get("album", {}).get("name", "Single") if t.get("album") else "Single",
                "duration": t.get("length", 0) or 0,
                "thumbnail": thumb
            })
            
        unique_artist_songs = []
        seen_artists = set()
        for s in songs:
            primary_artist = s["artist"].split(",")[0].strip().lower()
            if primary_artist not in seen_artists:
                seen_artists.add(primary_artist)
                unique_artist_songs.append(s)
                
        if len(unique_artist_songs) < 8:
            seen_ids = {s["id"] for s in unique_artist_songs}
            for s in songs:
                if s["id"] not in seen_ids:
                    unique_artist_songs.append(s)
                    seen_ids.add(s["id"])

        return web.json_response({"success": True, "songs": unique_artist_songs[:15]})
    except Exception as e:
        logger.error(f"Error in api_music_autoplay: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_artist_details(request):
    try:
        artist_id = request.query.get("id", "").strip()
        if not artist_id:
            return web.json_response({"success": False, "error": "ID de artista requerido"}, status=400)
            
        def fetch_artist():
            try:
                data = ytmusic.get_artist(artist_id)
                songs_section = data.get("songs", {})
                songs_results = songs_section.get("results", [])
                
                if "browseId" in songs_section and songs_section.get("browseId"):
                    try:
                        more_songs = ytmusic.get_playlist(songs_section["browseId"])
                        songs_results = more_songs.get("tracks", [])
                    except:
                        pass
                
                songs = []
                seen_ids = set()
                for r in songs_results[:8]:
                    if not r or not isinstance(r, dict):
                        continue
                    video_id = r.get("videoId")
                    if not video_id or video_id in seen_ids:
                        continue
                    seen_ids.add(video_id)
                    title = clean_track_title(r.get("title", ""))
                    artists_list = r.get("artists", [])
                    artists_str = ", ".join([(a.get("name") or "Artista") for a in artists_list if isinstance(a, dict)])
                    thumbnails = r.get("thumbnails", [])
                    thumb = thumbnails[-1].get("url", "") if thumbnails else f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                    if thumb and "=w60-h60" in thumb:
                        thumb = thumb.replace("=w60-h60", "=w500-h500")
                    elif thumb and "=w120-h120" in thumb:
                        thumb = thumb.replace("=w120-h120", "=w500-h500")
                        
                    songs.append({
                        "id": video_id,
                        "title": title,
                        "artist": artists_str or data.get("name", "Artista"),
                        "album": r.get("album", {}).get("name", "Single") if r.get("album") else "Single",
                        "duration": r.get("duration_seconds", 0),
                        "thumbnail": thumb
                    })
                    
                albums_section = data.get("albums", {})
                albums_results = albums_section.get("results", [])
                
                if "browseId" in albums_section and albums_section.get("browseId"):
                    try:
                        raw_data = ytmusic._send_request('browse', {'browseId': albums_section["browseId"]})
                        if raw_data:
                            tabs = raw_data.get('contents', {}).get('singleColumnBrowseResultsRenderer', {}).get('tabs', [{}])
                            if tabs:
                                content_renderer = tabs[0].get('tabRenderer', {}).get('content', {})
                                contents = content_renderer.get('sectionListRenderer', {}).get('contents', [{}])
                                if contents:
                                    grid_items = contents[0].get('gridRenderer', {}).get('items', [])
                                    custom_results = []
                                    for item in grid_items:
                                        renderer = item.get('musicTwoRowItemRenderer', {})
                                        if not renderer:
                                            continue
                                        browse_endpoint = renderer.get('navigationEndpoint', {}).get('browseEndpoint', {})
                                        b_id = browse_endpoint.get('browseId')
                                        if not b_id:
                                            continue
                                        title_runs = renderer.get('title', {}).get('runs', [])
                                        title_str = title_runs[0].get('text', 'Álbum') if title_runs else 'Álbum'
                                        sub_runs = renderer.get('subtitle', {}).get('runs', [])
                                        year_str = ""
                                        for r_item in sub_runs:
                                            text_val = r_item.get('text', '')
                                            if text_val.isdigit() and len(text_val) == 4:
                                                year_str = text_val
                                        thumb_renderer = renderer.get('thumbnail', {}).get('musicThumbnailRenderer', {})
                                        thumbs_list = thumb_renderer.get('thumbnail', {}).get('thumbnails', [])
                                        t_url = thumbs_list[-1].get('url', '') if thumbs_list else ""
                                        
                                        custom_results.append({
                                            "browseId": b_id,
                                            "title": title_str,
                                            "year": year_str,
                                            "thumbnails": [{"url": t_url}] if t_url else []
                                        })
                                    if custom_results:
                                        albums_results = custom_results
                    except Exception as parse_ex:
                        logger.error(f"Custom manual parse of albums page failed: {parse_ex}")

                # Combine with singles
                singles_section = data.get("singles", {})
                singles_results = singles_section.get("results", [])
                
                if "browseId" in singles_section and singles_section.get("browseId"):
                    try:
                        raw_singles_data = ytmusic._send_request('browse', {'browseId': singles_section["browseId"]})
                        if raw_singles_data:
                            tabs = raw_singles_data.get('contents', {}).get('singleColumnBrowseResultsRenderer', {}).get('tabs', [{}])
                            if tabs:
                                content_renderer = tabs[0].get('tabRenderer', {}).get('content', {})
                                contents = content_renderer.get('sectionListRenderer', {}).get('contents', [{}])
                                if contents:
                                    grid_items = contents[0].get('gridRenderer', {}).get('items', [])
                                    custom_singles = []
                                    for item in grid_items:
                                        renderer = item.get('musicTwoRowItemRenderer', {})
                                        if not renderer:
                                            continue
                                        browse_endpoint = renderer.get('navigationEndpoint', {}).get('browseEndpoint', {})
                                        b_id = browse_endpoint.get('browseId')
                                        if not b_id:
                                            continue
                                        title_runs = renderer.get('title', {}).get('runs', [])
                                        title_str = title_runs[0].get('text', 'Sencillo') if title_runs else 'Sencillo'
                                        sub_runs = renderer.get('subtitle', {}).get('runs', [])
                                        year_str = ""
                                        for r_item in sub_runs:
                                            text_val = r_item.get('text', '')
                                            if text_val.isdigit() and len(text_val) == 4:
                                                year_str = text_val
                                        thumb_renderer = renderer.get('thumbnail', {}).get('musicThumbnailRenderer', {})
                                        thumbs_list = thumb_renderer.get('thumbnail', {}).get('thumbnails', [])
                                        t_url = thumbs_list[-1].get('url', '') if thumbs_list else ""
                                        
                                        custom_singles.append({
                                            "browseId": b_id,
                                            "title": title_str,
                                            "year": year_str,
                                            "thumbnails": [{"url": t_url}] if t_url else []
                                        })
                                    if custom_singles:
                                        singles_results = custom_singles
                    except Exception as parse_ex:
                        logger.error(f"Custom manual parse of singles page failed: {parse_ex}")

                # Combine results
                all_releases = albums_results + singles_results
                
                albums = []
                for a in all_releases:
                    if not a or not isinstance(a, dict):
                        continue
                    album_id = a.get("browseId")
                    if not album_id:
                        continue
                    album_title = a.get("title", "Álbum")
                    thumbnails = a.get("thumbnails", [])
                    thumb = thumbnails[-1].get("url", "") if thumbnails else ""
                    if thumb and "=w60-h60" in thumb:
                        thumb = thumb.replace("=w60-h60", "=w300-h300")
                    elif thumb and "=w120-h120" in thumb:
                        thumb = thumb.replace("=w120-h120", "=w300-h300")
                        
                    albums.append({
                        "id": album_id,
                        "title": album_title,
                        "year": a.get("year", ""),
                        "thumbnail": thumb
                    })
                    
                # Fetch biography description
                description = data.get("description", "")
                
                # Fetch related artists
                related_section = data.get("related", {})
                related_results = related_section.get("results", [])
                related_artists = []
                for r in related_results[:6]:
                    r_id = r.get("browseId")
                    if not r_id:
                        continue
                    r_name = r.get("title", "Artista Relacionado")
                    r_thumbs = r.get("thumbnails", [])
                    r_thumb = r_thumbs[-1].get("url", "") if r_thumbs else ""
                    if r_thumb and "=w60-h60" in r_thumb:
                        r_thumb = r_thumb.replace("=w60-h60", "=w180-h180")
                    elif r_thumb and "=w120-h120" in r_thumb:
                        r_thumb = r_thumb.replace("=w120-h120", "=w180-h180")
                    related_artists.append({
                        "id": r_id,
                        "name": r_name,
                        "thumbnail": r_thumb
                    })

                thumbnails = data.get("thumbnails", [])
                artist_thumb = thumbnails[-1].get("url", "") if thumbnails else ""
                if artist_thumb and "=w120-h120" in artist_thumb:
                    artist_thumb = artist_thumb.replace("=w120-h120", "=w500-h500")
                elif artist_thumb and "=w60-h60" in artist_thumb:
                    artist_thumb = artist_thumb.replace("=w60-h60", "=w500-h500")
                
                return {
                    "name": data.get("name", "Artista"),
                    "thumbnail": artist_thumb,
                    "description": description,
                    "songs": songs,
                    "albums": albums,
                    "related": related_artists
                }
            except Exception as e:
                logger.error(f"Error resolving artist details for {artist_id}: {e}")
                return None
                
        loop = asyncio.get_event_loop()
        artist_details = await loop.run_in_executor(None, fetch_artist)
        if not artist_details:
            return web.json_response({"success": False, "error": "No se pudo obtener información del artista"}, status=500)
            
        return web.json_response({"success": True, "artist": artist_details})
    except Exception as e:
        logger.error(f"Error in api_music_artist_details: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_album_details(request):
    try:
        album_id = request.query.get("id", "").strip()
        if not album_id:
            return web.json_response({"success": False, "error": "ID de álbum requerido"}, status=400)
            
        def fetch_album():
            try:
                data = ytmusic.get_album(album_id)
                tracks = data.get("tracks", [])
                songs = []
                album_title = data.get("title", "Álbum")
                artists_list = data.get("artists", [])
                artist_name = ", ".join([(a.get("name") or "Artista") for a in artists_list if isinstance(a, dict)]) or "Artista"
                thumbnails = data.get("thumbnails", [])
                album_thumb = thumbnails[-1].get("url", "") if thumbnails else ""
                if album_thumb and "=w60-h60" in album_thumb:
                    album_thumb = album_thumb.replace("=w60-h60", "=w500-h500")
                elif album_thumb and "=w120-h120" in album_thumb:
                    album_thumb = album_thumb.replace("=w120-h120", "=w500-h500")
                    
                for r in tracks:
                    if not r or not isinstance(r, dict):
                        continue
                    video_id = r.get("videoId")
                    if not video_id:
                        continue
                    songs.append({
                        "id": video_id,
                        "title": clean_track_title(r.get("title", "")),
                        "artist": artist_name,
                        "album": album_title,
                        "duration": r.get("duration_seconds", 0),
                        "thumbnail": album_thumb
                    })
                return songs
            except Exception as e:
                logger.error(f"Error resolving album {album_id}: {e}")
                return []
                
        loop = asyncio.get_event_loop()
        songs = await loop.run_in_executor(None, fetch_album)
        return web.json_response({"success": True, "songs": songs})
    except Exception as e:
        logger.error(f"Error in api_music_album_details: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_playlist_details(request):
    try:
        playlist_id = request.query.get("id", "").strip()
        if not playlist_id:
            return web.json_response({"success": False, "error": "ID de playlist requerido"}, status=400)
            
        def fetch_playlist_tracks():
            try:
                data = ytmusic.get_playlist(playlist_id)
                tracks = data.get("tracks", [])
                songs = []
                playlist_title = data.get("title", "Playlist")
                
                for r in tracks:
                    if not r or not isinstance(r, dict):
                        continue
                    video_id = r.get("videoId")
                    if not video_id:
                        continue
                    
                    # Skip hour-long video mixes / album compilations (longer than 15 minutes)
                    duration_sec = r.get("duration_seconds")
                    if duration_sec is None:
                        # Fallback parsing string duration if seconds field is absent
                        dur_str = r.get("duration", "")
                        if dur_str and ":" in dur_str:
                            parts = dur_str.split(":")
                            if len(parts) > 2: # hh:mm:ss format
                                duration_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                            elif len(parts) == 2: # mm:ss format
                                duration_sec = int(parts[0]) * 60 + int(parts[1])
                    
                    if duration_sec and duration_sec > 900:
                        continue
                        
                    # Parse artist name
                    artists_list = r.get("artists", [])
                    if isinstance(artists_list, list) and artists_list:
                        artist = ", ".join([(a.get("name") or "Artista") for a in artists_list if isinstance(a, dict)])
                    else:
                        artist = r.get("author", "Artista Desconocido")
                    # Parse thumbnail
                    thumbnails = r.get("thumbnails", [])
                    thumb = thumbnails[-1].get("url", "") if thumbnails else f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                    
                    songs.append({
                        "id": video_id,
                        "title": clean_track_title(r.get("title", "")),
                        "artist": artist,
                        "album": playlist_title,
                        "duration": duration_sec or 0,
                        "thumbnail": thumb
                    })
                return songs
            except Exception as e:
                logger.error(f"Error resolving youtube music playlist {playlist_id}: {e}")
                return []
                
        loop = asyncio.get_event_loop()
        songs = await loop.run_in_executor(None, fetch_playlist_tracks)
        return web.json_response({"success": True, "songs": songs})
    except Exception as e:
        logger.error(f"Error in api_music_playlist_details: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_feedback(request):
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        if not username:
            return web.json_response({"success": False, "error": "No hay sesión activa"}, status=401)
            
        data = await request.json()
        track_id = data.get("track_id")
        action = data.get("action") # 'listened', 'skipped', 'favorited', 'unfavorited'
        track_obj = data.get("track") # Optional track details payload
        
        if not track_id or not action:
            # Fallback to check nested track object
            if isinstance(track_obj, dict) and track_obj.get("id"):
                track_id = track_obj.get("id")
                # Treat feedback POSTs with track detail payloads as favorited/likes
                action = 'favorited'
            else:
                return web.json_response({"success": False, "error": "Datos incompletos"}, status=400)
            
        users = load_music_users()
        if username not in users:
            return web.json_response({"success": False, "error": "Usuario no encontrado"}, status=404)
            
        user_data = users[username]
        
        # Initialize telemetry structures if they do not exist
        if "history" not in user_data:
            user_data["history"] = {}
        if "favorites" not in user_data:
            user_data["favorites"] = []
            
        track_history = user_data["history"].get(track_id, {"listened": 0, "skipped": 0, "score": 0})
        
        if action == 'listened':
            track_history["listened"] += 1
            track_history["score"] += 1
        elif action == 'skipped':
            track_history["skipped"] += 1
            track_history["score"] -= 1
        elif action == 'favorited':
            track_history["score"] += 3
            # Append track object metadata to user profile
            if track_obj and isinstance(track_obj, dict):
                if not any(f.get("id") == track_id for f in user_data["favorites"]):
                    user_data["favorites"].append(track_obj)
            else:
                # If we don't have track_obj, construct a minimal one using video_id
                if not any(f.get("id") == track_id for f in user_data["favorites"]):
                    user_data["favorites"].append({
                        "id": track_id,
                        "title": "Tema " + track_id,
                        "artist": "Artista",
                        "album": "Single",
                        "duration": 0,
                        "thumbnail": f"https://img.youtube.com/vi/{track_id}/hqdefault.jpg"
                    })
            # Automatically start caching to Google Drive in the background
            asyncio.create_task(cache_song_to_gdrive(track_id))
        elif action == 'unfavorited':
            track_history["score"] -= 3
            user_data["favorites"] = [f for f in user_data["favorites"] if f.get("id") != track_id]
            
        user_data["history"][track_id] = track_history
        save_music_users(users)
        
        return web.json_response({"success": True, "score": track_history["score"]})
    except Exception as e:
        logger.error(f"Error saving music feedback: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_favorites_list(request):
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        if not username:
            return web.json_response({"success": False, "error": "No hay sesión activa"}, status=401)
            
        users = load_music_users()
        if username not in users:
            return web.json_response({"success": False, "error": "Usuario no encontrado"}, status=404)
            
        user_favorites = users[username].get("favorites", [])
        return web.json_response({"success": True, "favorites": user_favorites})
    except Exception as e:
        logger.error(f"Error listing favorites: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_search_suggestions(request):
    try:
        query = request.query.get("q", "").strip()
        if not query:
            return web.json_response({"success": True, "suggestions": []})
            
        def fetch_suggestions():
            try:
                return ytmusic.get_search_suggestions(query)
            except Exception as e:
                logger.error(f"Error fetching suggestions: {e}")
                return []
                
        loop = asyncio.get_event_loop()
        suggestions = await loop.run_in_executor(None, fetch_suggestions)
        return web.json_response({"success": True, "suggestions": suggestions})
    except Exception as e:
        logger.error(f"Error in search suggestions API: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_playlists_list(request):
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        if not username:
            return web.json_response({"success": False, "error": "No hay sesión activa"}, status=401)
            
        users = load_music_users()
        if username not in users:
            return web.json_response({"success": False, "error": "Usuario no encontrado"}, status=404)
            
        user_playlists = users[username].get("playlists", [])
        return web.json_response({"success": True, "playlists": user_playlists})
    except Exception as e:
        logger.error(f"Error listing playlists: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_playlists_create(request):
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        if not username:
            return web.json_response({"success": False, "error": "No hay sesión activa"}, status=401)
            
        data = await request.json()
        name = data.get("name", "").strip()
        if not name:
            return web.json_response({"success": False, "error": "Nombre de playlist requerido"}, status=400)
            
        users = load_music_users()
        if username not in users:
            return web.json_response({"success": False, "error": "Usuario no encontrado"}, status=404)
            
        user_data = users[username]
        if "playlists" not in user_data:
            user_data["playlists"] = []
            
        # Check if already exists
        if any(p["name"].lower() == name.lower() for p in user_data["playlists"]):
            return web.json_response({"success": False, "error": "Ya existe una lista con este nombre"}, status=400)
            
        new_playlist = {
            "id": "playlist_" + secrets.token_hex(6),
            "name": name,
            "songs": []
        }
        
        user_data["playlists"].append(new_playlist)
        save_music_users(users)
        
        return web.json_response({"success": True, "playlist": new_playlist})
    except Exception as e:
        logger.error(f"Error creating playlist: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_playlists_delete(request):
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        if not username:
            return web.json_response({"success": False, "error": "No hay sesión activa"}, status=401)
            
        data = await request.json()
        playlist_id = data.get("playlist_id")
        
        users = load_music_users()
        if username not in users:
            return web.json_response({"success": False, "error": "Usuario no encontrado"}, status=404)
            
        user_data = users[username]
        if "playlists" not in user_data:
            return web.json_response({"success": False, "error": "No se encontraron listas"}, status=404)
            
        user_data["playlists"] = [p for p in user_data["playlists"] if p["id"] != playlist_id]
        save_music_users(users)
        
        return web.json_response({"success": True})
    except Exception as e:
        logger.error(f"Error deleting playlist: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_playlists_add_track(request):
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        if not username:
            return web.json_response({"success": False, "error": "No hay sesión activa"}, status=401)
            
        data = await request.json()
        playlist_id = data.get("playlist_id")
        track = data.get("track") # Dict representing the track
        
        if not playlist_id or not track or "id" not in track:
            return web.json_response({"success": False, "error": "Datos incompletos"}, status=400)
            
        users = load_music_users()
        if username not in users:
            return web.json_response({"success": False, "error": "Usuario no encontrado"}, status=404)
            
        user_data = users[username]
        playlists = user_data.get("playlists", [])
        
        target_playlist = next((p for p in playlists if p["id"] == playlist_id), None)
        if not target_playlist:
            return web.json_response({"success": False, "error": "Lista de reproducción no encontrada"}, status=404)
            
        # Avoid adding duplicate tracks to same playlist
        if any(t["id"] == track["id"] for t in target_playlist["songs"]):
            return web.json_response({"success": True, "message": "El tema ya está en la lista"})
            
        target_playlist["songs"].append({
            "id": track["id"],
            "title": track.get("title", "Canción"),
            "artist": track.get("artist", "Artista"),
            "album": track.get("album", "Single"),
            "duration": track.get("duration", 0),
            "thumbnail": track.get("thumbnail", "")
        })
        
        save_music_users(users)
        return web.json_response({"success": True, "playlist": target_playlist})
    except Exception as e:
        logger.error(f"Error adding track to playlist: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_playlists_remove_track(request):
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        if not username:
            return web.json_response({"success": False, "error": "No hay sesión activa"}, status=401)
            
        data = await request.json()
        playlist_id = data.get("playlist_id")
        track_id = data.get("track_id")
        
        if not playlist_id or not track_id:
            return web.json_response({"success": False, "error": "Datos incompletos"}, status=400)
            
        users = load_music_users()
        if username not in users:
            return web.json_response({"success": False, "error": "Usuario no encontrado"}, status=404)
            
        user_data = users[username]
        playlists = user_data.get("playlists", [])
        
        target_playlist = next((p for p in playlists if p["id"] == playlist_id), None)
        if not target_playlist:
            return web.json_response({"success": False, "error": "Lista de reproducción no encontrada"}, status=404)
            
        target_playlist["songs"] = [t for t in target_playlist["songs"] if t["id"] != track_id]
        save_music_users(users)
        
        return web.json_response({"success": True, "playlist": target_playlist})
    except Exception as e:
        logger.error(f"Error removing track from playlist: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_clone_favorites(request):
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        if not username:
            return web.json_response({"success": False, "error": "No hay sesión activa"}, status=401)
            
        data = await request.json()
        playlist_url = data.get("url", "").strip()
        platform = data.get("platform", "").strip().lower()
        tracks = data.get("tracks", [])
        
        # If a URL is passed, we resolve it into actual tracks list
        if playlist_url:
            import urllib.parse
            import re
            
            # YouTube Music Playlist resolver
            if "youtube.com" in playlist_url or "youtu.be" in playlist_url:
                parsed_url = urllib.parse.urlparse(playlist_url)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                playlist_id = query_params.get("list", [None])[0]
                if not playlist_id and "list=" in playlist_url:
                    m = re.search(r"list=([A-Za-z0-9_-]+)", playlist_url)
                    if m:
                        playlist_id = m.group(1)
                
                if playlist_id:
                    def get_yt_playlist():
                        from ytmusicapi import YTMusic
                        import urllib.request
                        import json
                        
                        # 1. First attempt: Standard ytmusicapi fetch with fresh initialization
                        try:
                            # Re-instantiate standard user headers to bypass Google scraping filters
                            client = get_ytmusic_client()
                            return client.get_playlist(playlist_id, limit=None)
                        except Exception as ex:
                            logger.error(f"First YTM playlist fetch attempt failed: {ex}")
                            
                        # 2. Second attempt: Raw urllib fetch to YouTube's public playlist page to scrape the tracks JSON block securely
                        try:
                            url = f"https://www.youtube.com/playlist?list={playlist_id}"
                            req = urllib.request.Request(
                                url,
                                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                            )
                            with urllib.request.urlopen(req, timeout=15) as response:
                                html = response.read().decode('utf-8')
                                # Locate ytInitialData JSON structure
                                start_str = "var ytInitialData = "
                                if start_str in html:
                                    json_part = html.split(start_str)[1]
                                    # Locate end of JSON statement
                                    json_str = json_part.split(";</script>")[0].strip()
                                    yt_data = json.loads(json_str)
                                    
                                    # Extract tracks metadata from structural hierarchy
                                    try:
                                        tabs = yt_data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
                                        tab_content = tabs[0].get("content", {}) if tabs else {}
                                        section_list = tab_content.get("sectionListRenderer", {}).get("contents", [])
                                        item_section = section_list[0].get("itemSectionRenderer", {}).get("contents", []) if section_list else []
                                        playlist_renderer = item_section[0].get("playlistVideoListRenderer", {}) if item_section else {}
                                        videos = playlist_renderer.get("contents", [])
                                        
                                        tracks_list = []
                                        for v in videos:
                                            video_data = v.get("playlistVideoRenderer", {})
                                            if video_data:
                                                title_text = video_data.get("title", {}).get("runs", [{}])[0].get("text", "Tema")
                                                artist_runs = video_data.get("shortBylineText", {}).get("runs", [])
                                                artist_text = ", ".join([r.get("text", "") for r in artist_runs]) if artist_runs else "Artista"
                                                video_id = video_data.get("videoId")
                                                duration_secs = int(video_data.get("lengthSeconds", 0))
                                                thumb_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                                                
                                                tracks_list.append({
                                                    "videoId": video_id,
                                                    "title": title_text,
                                                    "artists": [{"name": artist_text}],
                                                    "album": {"name": "Single"},
                                                    "duration_seconds": duration_secs,
                                                    "thumbnails": [{"url": thumb_url}]
                                                })
                                        if tracks_list:
                                            return {"tracks": tracks_list}
                                    except Exception as inner_ex:
                                        logger.error(f"Error parsing raw ytInitialData structure: {inner_ex}")
                        except Exception as ex2:
                            logger.error(f"Raw scraper fetch attempt failed: {ex2}")
                            
                        # 3. Third attempt: Global fallback ytmusic library object
                        try:
                            return ytmusic.get_playlist(playlist_id, limit=None)
                        except Exception as ex3:
                            logger.error(f"Final fallback fetch failed: {ex3}")
                            return None
                    
                    loop = asyncio.get_event_loop()
                    playlist_data = await loop.run_in_executor(None, get_yt_playlist)
                    
                    if playlist_data and "tracks" in playlist_data:
                        tracks = []
                        for t in playlist_data["tracks"]:
                            artists_list = t.get('artists', [])
                            artist = ", ".join([a.get('name', 'Artista') for a in artists_list]) if artists_list else 'Artista'
                            thumbnails = t.get('thumbnails', [])
                            thumb = thumbnails[-1].get('url', '') if thumbnails else f"https://img.youtube.com/vi/{t.get('videoId')}/hqdefault.jpg"
                            tracks.append({
                                "id": t.get("videoId"),
                                "title": clean_track_title(t.get("title", "Tema")),
                                "artist": artist,
                                "album": t.get("album", {}).get("name", "Single") if isinstance(t.get("album"), dict) else "Single",
                                "duration": t.get("duration_seconds", 0),
                                "thumbnail": thumb,
                                "_direct_import": True # Flag to bypass resolving block
                            })
            
            # Spotify Public Web Scraper fallback
            elif "spotify.com" in playlist_url:
                # Use aiohttp client to fetch and parse html metadata
                import aiohttp
                from bs4 import BeautifulSoup
                async with aiohttp.ClientSession() as session:
                    headers = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" }
                    async with session.get(playlist_url, headers=headers) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            # Spotify Embed or Public page tracks markup search
                            meta_tracks = []
                            # Look for meta tags or script json
                            for row in soup.find_all("meta", property="music:song"):
                                song_url = row.get("content", "")
                                # Fetch song details or fallback to title scans
                            
                            # Fallback scan page titles/spans
                            title_meta = soup.find("meta", property="og:title")
                            desc_meta = soup.find("meta", property="og:description")
                            
                            # Many public Spotify pages serialize list items inside structural divs
                            track_rows = soup.find_all("div", class_=re.compile(r"tracklist-row|TrackRow"))
                            if not track_rows:
                                # Look for list elements
                                track_rows = soup.find_all("li")
                            
                            for row in track_rows:
                                text = row.get_text(separator=" - ").strip()
                                if " - " in text:
                                    parts = text.split(" - ")
                                    # Basic sanitize
                                    if len(parts) >= 2:
                                        meta_tracks.append({
                                            "title": parts[0].strip()[:60],
                                            "artist": parts[1].strip()[:60]
                                        })
                            if meta_tracks:
                                tracks = meta_tracks[:50] # Limit to 50 items

            # Deezer Public Web Scraper fallback
            elif "deezer.com" in playlist_url:
                import aiohttp
                from bs4 import BeautifulSoup
                async with aiohttp.ClientSession() as session:
                    headers = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" }
                    async with session.get(playlist_url, headers=headers) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            meta_tracks = []
                            for row in soup.find_all("div", class_="datagrid-row"):
                                title_el = row.find("span", class_="song-title")
                                artist_el = row.find("span", class_="artist-name")
                                if title_el and artist_el:
                                    meta_tracks.append({
                                        "title": title_el.get_text().strip(),
                                        "artist": artist_el.get_text().strip()
                                    })
                            if meta_tracks:
                                tracks = meta_tracks[:50]
                                
        if not isinstance(tracks, list) or not tracks:
            return web.json_response({"success": False, "error": "No se encontraron canciones en el enlace proporcionado. Asegúrate de que sea una lista de reproducción pública."}, status=400)
            
        cloned_songs = []
        
        async def resolve_track(t):
            if isinstance(t, dict) and t.get("_direct_import"):
                # YouTube Music metadata is already complete with videoId, skip lookup entirely!
                return {
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "artist": t.get("artist"),
                    "album": t.get("album"),
                    "duration": t.get("duration"),
                    "thumbnail": t.get("thumbnail")
                }
                
            if isinstance(t, dict):
                search_q = f"{t.get('title', '')} {t.get('artist', '')}".strip()
            else:
                search_q = str(t).strip()
                
            if not search_q:
                return None
                
            try:
                def query_api():
                    try:
                        # Re-instantiate locally to avoid global instance locking
                        from ytmusicapi import YTMusic
                        fresh_yt = get_ytmusic_client()
                        return fresh_yt.search(search_q, filter="songs")
                    except Exception as e:
                        logger.error(f"YTM clone lookup failed: {e}")
                        return []
                        
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(None, query_api)
                
                if results and isinstance(results, list):
                    top = results[0]
                    artists_list = top.get('artists', [])
                    artist = ", ".join([(a.get('name') or 'Artista') for a in artists_list if isinstance(a, dict)]) if artists_list else 'Artista'
                    thumbnails = top.get('thumbnails', [])
                    thumb = thumbnails[-1].get('url', '') if thumbnails else ""
                    return {
                        "id": top.get('videoId'),
                        "title": clean_track_title(top.get('title', 'Tema')),
                        "artist": artist,
                        "album": top.get('album', {}).get('name', 'Single') if isinstance(top.get('album'), dict) else 'Single',
                        "duration": top.get('duration_seconds', 0),
                        "thumbnail": thumb
                    }
            except Exception as ex:
                logger.error(f"Failed resolving track '{search_q}': {ex}")
            return None

        # Resolve tracks concurrently in small chunks to prevent both rate limits and timeouts
        # If we have direct import tracks (like YTM), this chunk loop executes instantly
        chunk_size = 15
        for i in range(0, len(tracks), chunk_size):
            chunk = tracks[i:i+chunk_size]
            tasks = [resolve_track(item) for item in chunk]
            results = await asyncio.gather(*tasks)
            for res in results:
                if res and res.get("id"):
                    cloned_songs.append(res)
            # Short sleep ONLY if we are performing actual web lookups
            if not any(item.get("_direct_import") for item in chunk if isinstance(item, dict)):
                await asyncio.sleep(0.4)
                    
        return web.json_response({"success": True, "songs": cloned_songs})
    except Exception as e:
        logger.error(f"Error in clone favorites endpoint: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_offline_sync(request):
    """Syncs/Backs up the offline downloaded tracks list to the user account in the cloud"""
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        data = await request.json()
        if not username:
            username = data.get("username", "").strip().lower()
        if not username:
            return web.json_response({"success": False, "error": "No hay sesión activa"}, status=401)
            
        tracks = data.get("tracks", [])
        if not isinstance(tracks, list):
            return web.json_response({"success": False, "error": "Formato de pistas inválido"}, status=400)
            
        users = load_music_users()
        if username not in users:
            return web.json_response({"success": False, "error": "Usuario no encontrado"}, status=404)
            
        # Merge or replace offline track list for this user account
        existing_offline = users[username].get("offline_tracks", [])
        existing_ids = {t["id"] for t in existing_offline if isinstance(t, dict) and "id" in t}
        
        merged = list(existing_offline)
        for t in tracks:
            if isinstance(t, dict) and t.get("id") and t["id"] not in existing_ids:
                merged.append(t)
                existing_ids.add(t["id"])
                
        users[username]["offline_tracks"] = merged
        users[username]["offline_updated_at"] = time.time()
        save_music_users(users)
        
        return web.json_response({
            "success": True, 
            "count": len(merged),
            "message": f"Biblioteca offline sincronizada ({len(merged)} canciones en tu cuenta)"
        })
    except Exception as e:
        logger.error(f"Error syncing offline tracks: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_offline_get(request):
    """Retrieves the cloud synced offline library for this user account to import on a second device"""
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        req_user = request.query.get("username", "").strip().lower()
        target_user = username or req_user
        if not target_user:
            return web.json_response({"success": False, "error": "No hay sesión activa"}, status=401)
            
        users = load_music_users()
        if target_user not in users:
            return web.json_response({"success": False, "error": "Usuario no encontrado"}, status=404)
            
        offline_tracks = users[target_user].get("offline_tracks", [])
        updated_at = users[target_user].get("offline_updated_at", 0)
        
        return web.json_response({
            "success": True,
            "username": target_user,
            "tracks": offline_tracks,
            "count": len(offline_tracks),
            "updated_at": updated_at
        })
    except Exception as e:
        logger.error(f"Error retrieving offline tracks: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

# --- WEBRTC P2P DIRECT SHARE SIGNALING SYSTEM ---
_p2p_transfer_rooms = {}

async def api_music_p2p_create_session(request):
    """Creates a local direct P2P pairing code for sending/receiving audio files directly between devices"""
    try:
        username = request.cookies.get("motomusic_username", "").strip().lower()
        data = await request.json()
        role = data.get("role", "sender") # 'sender' or 'receiver'
        custom_code = data.get("code")
        
        now = time.time()
        # Clean expired rooms (> 15 minutes)
        expired = [k for k, v in _p2p_transfer_rooms.items() if now - v.get("created_at", 0) > 900]
        for k in expired:
            _p2p_transfer_rooms.pop(k, None)

        if role == "sender":
            # Generate clean 6-digit numeric pairing PIN
            import random
            pin_code = str(random.randint(100000, 999999))
            _p2p_transfer_rooms[pin_code] = {
                "created_at": now,
                "username": username,
                "sender_signal": None,
                "receiver_signal": None,
                "candidates": [],
                "tracks": data.get("tracks", [])
            }
            return web.json_response({"success": True, "code": pin_code})
        else:
            code = str(custom_code).strip()
            if code not in _p2p_transfer_rooms:
                return web.json_response({"success": False, "error": "Código de transferencia no encontrado o expirado"}, status=404)
            room = _p2p_transfer_rooms[code]
            return web.json_response({
                "success": True, 
                "code": code, 
                "tracks_count": len(room.get("tracks", [])),
                "tracks": room.get("tracks", [])
            })
    except Exception as e:
        logger.error(f"P2P Create Session error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_music_p2p_signal(request):
    """Exchanges WebRTC SDP offer/answer/candidates for local direct WiFi transmission"""
    try:
        data = await request.json()
        code = str(data.get("code", "")).strip()
        action = data.get("action") # 'post_offer', 'get_offer', 'post_answer', 'get_answer', 'add_candidate', 'get_candidates'
        payload = data.get("payload")

        if not code or code not in _p2p_transfer_rooms:
            return web.json_response({"success": False, "error": "Sesión P2P inválida o expirada"}, status=404)

        room = _p2p_transfer_rooms[code]

        if action == "post_offer":
            room["sender_signal"] = payload
            return web.json_response({"success": True})
        elif action == "get_offer":
            return web.json_response({"success": True, "offer": room.get("sender_signal")})
        elif action == "post_answer":
            room["receiver_signal"] = payload
            return web.json_response({"success": True})
        elif action == "get_answer":
            return web.json_response({"success": True, "answer": room.get("receiver_signal")})
        elif action == "add_candidate":
            if payload:
                room.setdefault("candidates", []).append(payload)
            return web.json_response({"success": True})
        elif action == "get_candidates":
            return web.json_response({"success": True, "candidates": room.get("candidates", [])})
        else:
            return web.json_response({"success": False, "error": "Acción desconocida"}, status=400)
    except Exception as e:
        logger.error(f"P2P Signal error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


