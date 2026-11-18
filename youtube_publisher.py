"""Optional direct YouTube publisher using the official OAuth 2.0 / videos.insert APIs.

No account passwords, user API secrets or video files are exposed to third-party clients.
OAuth credentials are provisioned by the site owner in Render environment variables.
Each visitor's OAuth token is encrypted in an HttpOnly browser cookie, not stored
on Render's ephemeral disk. This module never posts without an explicit user click.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

PUBLIC_URL = os.environ.get("CLIPFORGE_PUBLIC_URL", "https://clipforge-web-dccq.onrender.com").rstrip("/")
CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
COOKIE_KEY = os.environ.get("SOCIAL_COOKIE_KEY", "").strip()
SESSION_COOKIE = "clipforge_youtube_session"
OAUTH_STATE_COOKIE = "clipforge_oauth_state"
OAUTH_VERIFIER_COOKIE = "clipforge_oauth_pkce"
OAUTH_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
CALLBACK = PUBLIC_URL + "/api/publish/youtube/callback"
SESSION_DAYS = 30
UPLOADS = {}
UPLOAD_LOCK = threading.RLock()
UPLOAD_SLOT = threading.BoundedSemaphore(1)
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def _cipher():
    try:
        return Fernet(COOKIE_KEY.encode("ascii"))
    except (ValueError, TypeError, AttributeError):
        return None


def is_configured():
    return bool(CLIENT_ID and CLIENT_SECRET and _cipher())


def _session(request):
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw or not is_configured():
        return None
    try:
        data = json.loads(_cipher().decrypt(raw.encode("ascii"), ttl=SESSION_DAYS * 86400))
        if (not isinstance(data, dict) or not data.get("refresh_token") or
                not data.get("csrf")):
            return None
        return data
    except (InvalidToken, UnicodeError, ValueError, TypeError):
        return None


def _session_cookie(response, data):
    value = _cipher().encrypt(json.dumps(data, separators=(",", ":")).encode("utf-8")).decode("ascii")
    response.set_cookie(
        SESSION_COOKIE, value, max_age=SESSION_DAYS * 86400,
        secure=True, httponly=True, samesite="lax", path="/"
    )


def _fail_google(error):
    if isinstance(error, urllib.error.HTTPError):
        try:
            content = json.loads(error.read(2048).decode("utf-8", "replace"))
            detail = content.get("error", {})
            if isinstance(detail, dict):
                detail = detail.get("message", "Error HTTP")
            return "Google rechazó la solicitud (" + str(error.code) + "): " + str(detail)[:150]
        except Exception:
            return "Google rechazó la solicitud (HTTP " + str(error.code) + ")."
    return "No se pudo contactar con Google. Intenta nuevamente."


def _token_request(params):
    payload = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=payload, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def _authorize_session(data):
    if time.time() < float(data.get("expires_at", 0)) - 120 and data.get("access_token"):
        return data, False
    updated = _token_request({
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "refresh_token": data["refresh_token"], "grant_type": "refresh_token"
    })
    if not updated.get("access_token"):
        raise RuntimeError("Google no devolvió un token válido. Vuelve a conectar la cuenta.")
    data = dict(data)
    data["access_token"] = updated["access_token"]
    data["expires_at"] = int(time.time()) + int(updated.get("expires_in", 3500))
    data["refresh_token"] = updated.get("refresh_token") or data["refresh_token"]
    return data, True


def _check_action(request, session):
    origin = request.headers.get("origin", "")
    if origin != PUBLIC_URL:
        raise HTTPException(403, "Solicitud de otro origen rechazada.")
    csrf = request.headers.get("x-clipforge-csrf", "")
    if not session or not csrf or not hmac.compare_digest(csrf, session["csrf"]):
        raise HTTPException(403, "Sesión no autorizada. Vuelve a conectar YouTube.")


def _youtube_upload(access_token, source, title, description, privacy, for_kids, altered_media, record, upload_id):
    """Google resumable upload in 4-MiB blocks; bounded memory on Render Free."""
    total = source.stat().st_size
    if total <= 0:
        raise RuntimeError("El Short ya no está disponible.")
    snippet = {"title": title, "description": description, "categoryId": "22"}
    metadata = {
        "snippet": snippet,
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": for_kids,
            "containsSyntheticMedia": altered_media
        }
    }
    meta_bytes = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": "Bearer " + access_token,
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(total)
    }
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet%2Cstatus",
        data=meta_bytes, method="POST", headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as reply:
            session_url = reply.headers.get("Location", "")
    except Exception as e:
        raise RuntimeError(_fail_google(e)) from None
    if not session_url.startswith("https://www.googleapis.com/upload/youtube/"):
        raise RuntimeError("Google no devolvió una sesión de subida válida.")

    chunk_size = 4 * 1024 * 1024
    offset = 0
    with source.open("rb") as fh:
        while offset < total:
            fh.seek(offset)
            chunk = fh.read(min(chunk_size, total - offset))
            if not chunk:
                raise RuntimeError("El archivo terminó antes de completar la subida.")
            end = offset + len(chunk) - 1
            req = urllib.request.Request(
                session_url, data=chunk, method="PUT",
                headers={
                    "Authorization": "Bearer " + access_token,
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes {offset}-{end}/{total}"
                }
            )
            try:
                with urllib.request.urlopen(req, timeout=110) as reply:
                    if reply.status not in (200, 201):
                        raise RuntimeError("Respuesta inesperada de YouTube.")
                    response = json.load(reply)
                    video_id = str(response.get("id", ""))
                    if not re.fullmatch(r"[A-Za-z0-9_-]{6,25}", video_id):
                        raise RuntimeError("YouTube no confirmó el identificador del video.")
                    return "https://www.youtube.com/watch?v=" + video_id
            except urllib.error.HTTPError as e:
                if e.code == 308:
                    # Resume Incomplete: acknowledge the bytes Google accepted.
                    ack = e.headers.get("Range", "")
                    found = re.fullmatch(r"bytes=0-(\d+)", ack)
                    next_offset = int(found.group(1)) + 1 if found else end + 1
                    if next_offset <= offset or next_offset > total:
                        raise RuntimeError("La sesión de carga se interrumpió.")
                    offset = next_offset
                    with UPLOAD_LOCK:
                        record["progress"] = min(99, int(offset * 100 / total))
                    continue
                raise RuntimeError(_fail_google(e)) from None
            except Exception as e:
                raise RuntimeError(_fail_google(e)) from None
    raise RuntimeError("La subida terminó sin confirmación de YouTube.")


def install_youtube_publisher(app, jobs, jobs_lock):
    @app.get("/api/publish/youtube/status")
    def youtube_status(request: Request):
        data = _session(request)
        return {
            "configured": is_configured(),
            "checks": {
                "google_client_id_present": bool(CLIENT_ID),
                "google_client_secret_present": bool(CLIENT_SECRET),
                "session_encryption_key_valid": bool(_cipher())
            },
            "connected": bool(data),
            "csrf": data["csrf"] if data else None,
            "setup_required": not is_configured(),
            "setup_docs_url": "https://console.cloud.google.com/apis/credentials",
            "redirect_uri": CALLBACK,
            "supported": True,
            "supports_auto_publish_after_generate": False,
            "note": "Publicación oficial, únicamente tras conectar Google y confirmar cada subida."
        }

    @app.get("/api/publish/youtube/connect")
    def youtube_connect(request: Request):
        if not is_configured():
            raise HTTPException(503, "El administrador debe configurar OAuth de YouTube en Render.")
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        state = secrets.token_urlsafe(32)
        url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": CLIENT_ID, "redirect_uri": CALLBACK,
            "response_type": "code", "scope": OAUTH_SCOPE,
            "access_type": "offline", "prompt": "consent",
            "code_challenge": challenge, "code_challenge_method": "S256",
            "state": state
        })
        response = RedirectResponse(url)
        response.set_cookie(OAUTH_STATE_COOKIE, state, max_age=600,
                            secure=True, httponly=True, samesite="lax", path="/")
        response.set_cookie(OAUTH_VERIFIER_COOKIE, verifier, max_age=600,
                            secure=True, httponly=True, samesite="lax", path="/")
        return response

    @app.get("/api/publish/youtube/callback")
    def youtube_callback(request: Request, code: str = "", state: str = "", error: str = ""):
        if not is_configured():
            raise HTTPException(503, "OAuth no está configurado.")
        saved_state = request.cookies.get(OAUTH_STATE_COOKIE, "")
        verifier = request.cookies.get(OAUTH_VERIFIER_COOKIE, "")
        if not saved_state or not verifier or not hmac.compare_digest(state, saved_state):
            raise HTTPException(403, "El estado OAuth no coincide. Vuelve a conectar YouTube.")
        response = RedirectResponse(PUBLIC_URL + "/?youtube=connected#social-hub", status_code=303)
        response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
        response.delete_cookie(OAUTH_VERIFIER_COOKIE, path="/")
        if error or not code:
            return RedirectResponse(PUBLIC_URL + "/?youtube=cancelled#social-hub", status_code=303)
        try:
            token = _token_request({
                "code": code, "code_verifier": verifier,
                "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                "redirect_uri": CALLBACK, "grant_type": "authorization_code"
            })
        except Exception as e:
            raise HTTPException(502, _fail_google(e)) from None
        if not token.get("access_token") or not token.get("refresh_token"):
            raise HTTPException(502, "Google no concedió acceso permanente. Intenta conectar de nuevo.")
        session = {
            "access_token": token["access_token"],
            "refresh_token": token["refresh_token"],
            "expires_at": int(time.time()) + int(token.get("expires_in", 3500)),
            "csrf": secrets.token_urlsafe(30)
        }
        _session_cookie(response, session)
        return response

    @app.post("/api/publish/youtube/disconnect")
    def youtube_disconnect(request: Request):
        session = _session(request)
        _check_action(request, session)
        response = JSONResponse({"connected": False})
        response.delete_cookie(SESSION_COOKIE, path="/")
        # This deletes local authentication, not the Google-granted authorization.
        return response

    @app.post("/api/publish/youtube")
    async def youtube_publish(request: Request):
        if not is_configured():
            raise HTTPException(503, "La conexión oficial de YouTube aún no está configurada en Render.")
        session = _session(request)
        _check_action(request, session)
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "La solicitud de publicación debe contener datos válidos.")
        jid = str(data.get("job_id", ""))
        num = data.get("number", None)
        title = str(data.get("title", "")).strip()
        description = str(data.get("description", "")).strip()
        privacy = str(data.get("privacy", "private"))
        for_kids = data.get("for_kids")
        altered_media = data.get("altered_media")
        if not re.fullmatch(r"[a-f0-9]{32}", jid) or type(num) is not int or not 1 <= num <= 12:
            raise HTTPException(400, "El identificador del clip no es válido.")
        if not 1 <= len(title) <= 100 or "<" in title or ">" in title:
            raise HTTPException(400, "El título debe tener entre 1 y 100 caracteres y no contener < ni >.")
        if len(description) > 5000:
            raise HTTPException(400, "La descripción supera 5.000 caracteres.")
        if privacy not in ("private", "unlisted", "public"):
            raise HTTPException(400, "Privacidad no válida.")
        if type(for_kids) is not bool or type(altered_media) is not bool:
            raise HTTPException(400, "Debes indicar si es contenido infantil y si contiene contenido sintético realista.")
        if data.get("confirmed") is not True:
            raise HTTPException(400, "Confirma que tienes derechos de publicación antes de continuar.")
        with jobs_lock:
            if jid not in jobs or jobs[jid].get("status") != "done":
                raise HTTPException(404, "Este clip ya no está disponible. Genéralo de nuevo.")
            if num > len(jobs[jid].get("clips", [])):
                raise HTTPException(404, "El Short seleccionado no existe.")
            source = Path(jobs[jid]["folder"]) / f"short_{num}.mp4"
        if not source.is_file():
            raise HTTPException(404, "El MP4 temporal ya no existe.")
        try:
            valid_session, renewed = _authorize_session(session)
        except Exception:
            raise HTTPException(401, "Google requiere una nueva autorización. Desconecta y conecta YouTube.")
        upload_id = secrets.token_hex(16)
        record = {"status": "queued", "progress": 0, "message": "En cola para YouTube", "url": None,
                  "created": time.time()}
        with UPLOAD_LOCK:
            # One active upload per instance; bound job metadata.
            if sum(x["status"] in ("queued", "working") for x in UPLOADS.values()) >= 2:
                raise HTTPException(429, "Ya hay dos subidas pendientes. Comprueba su progreso.")
            for k, v in list(UPLOADS.items()):
                if time.time() - v["created"] > 7200 and v["status"] in ("done", "error"):
                    del UPLOADS[k]
            UPLOADS[upload_id] = record

        def worker():
            with UPLOAD_SLOT:
                with UPLOAD_LOCK:
                    record.update(status="working", message="Subiendo el video a YouTube...")
                try:
                    url = _youtube_upload(valid_session["access_token"], source, title, description,
                                          privacy, for_kids, altered_media, record, upload_id)
                    with UPLOAD_LOCK:
                        record.update(status="done", progress=100, message="YouTube confirmó la subida.",
                                      url=url)
                except Exception as e:
                    with UPLOAD_LOCK:
                        record.update(status="error", message=str(e)[:240])
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        response = JSONResponse({"upload_id": upload_id, "status": "queued"}, status_code=202)
        if renewed:
            _session_cookie(response, valid_session)
        return response


    @app.post("/api/publish/youtube/batch")
    async def youtube_publish_batch(request: Request):
        """Explicitly authorized one-click upload of every clip from a completed job.

        Copy is generated per clip server-side, then uploads run sequentially.
        The accepted batch survives closing the browser while the Render worker stays alive.
        """
        if not is_configured():
            raise HTTPException(503, "Configura primero YouTube OAuth en Render.")
        session = _session(request)
        _check_action(request, session)
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "Configuración de publicación inválida.")
        jid = str(data.get("job_id", ""))
        privacy = str(data.get("privacy", "private"))
        for_kids = data.get("for_kids")
        altered_media = data.get("altered_media")
        style = str(data.get("style", "intriga"))
        topic = str(data.get("topic", "")).strip()[:95]
        if not re.fullmatch(r"[a-f0-9]{32}", jid):
            raise HTTPException(400, "El identificador del trabajo no es válido.")
        if privacy not in ("private", "unlisted", "public"):
            raise HTTPException(400, "Selecciona la privacidad de YouTube.")
        if type(for_kids) is not bool or type(altered_media) is not bool:
            raise HTTPException(400, "Indica los valores para menores y contenido sintético.")
        if style not in ("intriga", "emocion", "humor", "informativo"):
            raise HTTPException(400, "Estilo inválido.")
        if data.get("confirmed") is not True:
            raise HTTPException(400, "Confirma expresamente que autorizas publicar todos los Shorts.")
        with jobs_lock:
            job = jobs.get(jid)
            if not job or job.get("status") != "done":
                raise HTTPException(404, "Genera los Shorts antes de publicar.")
            source = Path(job["folder"])
            clip_data = [dict(c) for c in job.get("clips", [])]
            fallback_topic = str(job.get("topic_hint", ""))[:95]
        if not clip_data or len(clip_data) > 12:
            raise HTTPException(400, "No hay Shorts válidos para publicar.")
        paths = [source / f"short_{i + 1}.mp4" for i in range(len(clip_data))]
        if any(not path.is_file() for path in paths):
            raise HTTPException(404, "Un Short ha expirado: genera otra vez los clips.")
        try:
            valid_session, renewed = _authorize_session(session)
        except Exception:
            raise HTTPException(401, "Vuelve a conectar tu cuenta de Google.")
        owner = hashlib.sha256(session["csrf"].encode("ascii")).hexdigest()
        with UPLOAD_LOCK:
            # Deliberately reject duplicate batches; never post twice by double-click.
            for old in UPLOADS.values():
                if (old.get("kind") == "batch" and old.get("owner") == owner
                        and old.get("job_id") == jid
                        and (old.get("status") != "error" or old.get("completed", 0) > 0)):
                    raise HTTPException(409, "Los Shorts de este trabajo ya se enviaron o están en proceso.")
            if sum(x["status"] in ("queued", "working") for x in UPLOADS.values()) >= 2:
                raise HTTPException(429, "Ya hay dos publicaciones pendientes.")
            for k, v in list(UPLOADS.items()):
                if time.time() - v["created"] > 7200 and v["status"] in ("done", "error"):
                    del UPLOADS[k]
            upload_id = secrets.token_hex(16)
            record = {
                "kind": "batch", "owner": owner, "job_id": jid, "created": time.time(),
                "status": "queued", "progress": 0, "message": "Clips preparados para publicar.",
                "url": None, "videos": [], "completed": 0, "total": len(paths)
            }
            UPLOADS[upload_id] = record

        def worker():
            from social_studio import create_social_copy
            with UPLOAD_SLOT:
                try:
                    for i, source_path in enumerate(paths):
                        with UPLOAD_LOCK:
                            record.update(status="working", message=f"Publicando Short {i + 1} de {len(paths)}...",
                                          progress=int(i * 100 / len(paths)))
                        editorial = create_social_copy(clip_data[i], "youtube", style, topic or fallback_topic)
                        title = str(editorial.get("title", "")).replace("<", "").replace(">", "").strip()[:100]
                        if not title:
                            title = f"ClipForge Short {i + 1}"
                        # Avoid uploading near-identical titles for a longer batch.
                        previous_titles = {v["title"].casefold() for v in record["videos"]}
                        if title.casefold() in previous_titles:
                            suffix = f" | Momento {i + 1}"
                            title = title[:100 - len(suffix)].rstrip() + suffix
                        description = str(editorial.get("description", ""))[:5000]
                        part_progress = {"progress": 0}
                        link = _youtube_upload(valid_session["access_token"], source_path, title,
                                               description, privacy, for_kids, altered_media,
                                               part_progress, upload_id)
                        with UPLOAD_LOCK:
                            record["videos"].append({"number": i + 1, "title": title, "url": link})
                            record["completed"] = i + 1
                            record["progress"] = int((i + 1) * 100 / len(paths))
                    with UPLOAD_LOCK:
                        record.update(status="done", progress=100,
                                      message="YouTube confirmó todos los videos. Revisa su procesamiento.")
                except Exception as exc:
                    with UPLOAD_LOCK:
                        record.update(status="error", message=("Publicación incompleta: " + str(exc))[:240])

        threading.Thread(target=worker, daemon=True).start()
        response = JSONResponse({"upload_id": upload_id, "status": "queued", "total": len(paths)},
                                status_code=202)
        if renewed:
            _session_cookie(response, valid_session)
        return response

    @app.get("/api/publish/youtube/uploads/{upload_id}")
    def youtube_upload_status(request: Request, upload_id: str):
        session = _session(request)
        if not session:
            raise HTTPException(401, "Debes conectar YouTube para comprobar la publicación.")
        if not re.fullmatch(r"[a-f0-9]{32}", upload_id):
            raise HTTPException(404, "Publicación no encontrada.")
        with UPLOAD_LOCK:
            record = UPLOADS.get(upload_id)
            if not record:
                raise HTTPException(404, "Publicación no encontrada o servidor reiniciado.")
            return {k: record.get(k) for k in ("status", "progress", "message", "url", "videos", "completed", "total")}
