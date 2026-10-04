#!/usr/bin/env python3
import os
import json
import time
import urllib.request
import urllib.parse
import ssl

GDRIVE_FILE = "/root/dashboard/gdrive_accounts.json"
GDRIVE_CONFIG_FILE = "/root/dashboard/gdrive_config.json"

def get_active_account():
    if os.path.exists(GDRIVE_FILE):
        try:
            with open(GDRIVE_FILE, 'r') as f:
                accs = json.load(f)
                if accs and len(accs) > 0:
                    return accs[0]
        except Exception:
            pass
    return None

def refresh_token_sync(acc):
    expires_at = acc.get("expires_at", 0)
    if time.time() < (expires_at - 120):
        return acc.get("access_token")

    refresh_token = acc.get("refresh_token")
    if not refresh_token or not os.path.exists(GDRIVE_CONFIG_FILE):
        return acc.get("access_token")

    try:
        with open(GDRIVE_CONFIG_FILE, 'r') as f:
            cfg = json.load(f)

        token_url = "https://oauth2.googleapis.com/token"
        payload = urllib.parse.urlencode({
            "client_id": cfg.get("client_id"),
            "client_secret": cfg.get("client_secret"),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }).encode("utf-8")

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(token_url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                new_token = data.get("access_token")
                acc["access_token"] = new_token
                acc["expires_at"] = time.time() + data.get("expires_in", 3600)
                
                # Guardar cuenta actualizada
                with open(GDRIVE_FILE, 'r') as f: accounts = json.load(f)
                for i, a in enumerate(accounts):
                    if a.get("id") == acc.get("id"):
                        accounts[i] = acc
                        break
                with open(GDRIVE_FILE, 'w') as f: json.dump(accounts, f, indent=2)
                return new_token
    except Exception as e:
        print(f"Error refreshing token: {e}")
    return acc.get("access_token")

def upload_file_to_drive(file_path, folder_name="Facturas_SAT_Uber"):
    """
    Sube un archivo (foto ticket, xml, pdf) a Google Drive en la carpeta especificada.
    Retorna el link o ID de Drive y elimina el archivo local para no saturar la memoria del teléfono.
    """
    acc = get_active_account()
    if not acc:
        print("No hay cuenta de Google Drive vinculada.")
        return None

    token = refresh_token_sync(acc)
    if not token:
        return None

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # 1. Buscar o Crear la carpeta 'Facturas_SAT_Uber'
    folder_id = None
    try:
        q = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(q)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            files = data.get("files", [])
            if files:
                folder_id = files[0]["id"]
            else:
                # Crear carpeta
                meta_url = "https://www.googleapis.com/drive/v3/files"
                meta_body = json.dumps({
                    "name": folder_name,
                    "mimeType": "application/vnd.google-apps.folder"
                }).encode("utf-8")
                create_req = urllib.request.Request(meta_url, data=meta_body, headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                })
                with urllib.request.urlopen(create_req, timeout=10, context=ctx) as c_resp:
                    c_data = json.loads(c_resp.read().decode("utf-8"))
                    folder_id = c_data.get("id")
    except Exception as e:
        print(f"Error finding/creating Drive folder: {e}")

    # 2. Subir el archivo Multipart a Drive
    try:
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        boundary = "===============7330837073145344603=="
        metadata = {
            "name": filename
        }
        if folder_id:
            metadata["parents"] = [folder_id]

        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
        up_req = urllib.request.Request(upload_url, data=body, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary}"
        }, method="POST")

        with urllib.request.urlopen(up_req, timeout=20, context=ctx) as u_resp:
            result = json.loads(u_resp.read().decode("utf-8"))
            file_id = result.get("id")
            print(f"✅ Archivo '{filename}' subido exitosamente a Google Drive con ID: {file_id}")
            return {
                "success": True,
                "drive_file_id": file_id,
                "drive_name": filename,
                "folder": folder_name
            }
    except Exception as e:
        print(f"Error uploading file to Drive: {e}")
        return None
