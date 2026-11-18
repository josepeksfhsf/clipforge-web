"""Official OAuth account connections for Instagram, TikTok and Facebook.

Does NOT grant publishing permissions. Production posting requires additional approved
API products and user consent. Never accept passwords or access tokens from the browser.
Tokens are encrypted into per-account HttpOnly Secure cookies (same pattern as YouTube);
Render's ephemeral filesystem is not used. Separate OAuth state cookies prevent login CSRF.
"""
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

PUBLIC_URL=os.environ.get("CLIPFORGE_PUBLIC_URL","https://clipforge-web-dccq.onrender.com").rstrip("/")
GRAPH_VERSION="v27.0"
SOCIALS=("instagram","tiktok","facebook")
LABELS={"instagram":"Instagram","tiktok":"TikTok","facebook":"Facebook"}
ENV={
    "instagram":("INSTAGRAM_CLIENT_ID","INSTAGRAM_CLIENT_SECRET"),
    "tiktok":("TIKTOK_CLIENT_KEY","TIKTOK_CLIENT_SECRET"),
    "facebook":("FACEBOOK_APP_ID","FACEBOOK_APP_SECRET"),
}
SETUP_DOC="https://github.com/josepeksfhsf/clipforge-web/blob/main/SOCIAL_CONNECTIONS_SETUP.md"
MAX_SESSION_DAYS=25

def _env(platform):
    a,b=ENV[platform]
    if platform=="instagram":
        return ((os.getenv(a) or os.getenv("INSTAGRAM_APP_ID") or "").strip(),
                (os.getenv(b) or os.getenv("INSTAGRAM_APP_SECRET") or "").strip())
    if platform=="facebook":
        return ((os.getenv(a) or os.getenv("META_APP_ID") or "").strip(),
                (os.getenv(b) or os.getenv("META_APP_SECRET") or "").strip())
    return ((os.getenv(a) or "").strip(),(os.getenv(b) or "").strip())

def _cipher():
    try:return Fernet(os.environ.get("SOCIAL_COOKIE_KEY","").strip().encode("ascii"))
    except (TypeError,ValueError,AttributeError):return None

def _configured(platform):
    cid,secret=_env(platform)
    return bool(cid and secret and _cipher())

def _callback(platform):
    return PUBLIC_URL+"/api/social/callback/"+platform

def _cookie_session(platform):
    return "clipforge_"+platform+"_account"

def _cookie_state(platform):
    return "clipforge_"+platform+"_state"

def _cookie_set(response,name,value,max_age):
    response.set_cookie(name,value,max_age=max_age,path="/",
                        httponly=True,secure=True,samesite="lax")

def _read_session(request,platform):
    if not _configured(platform):return None
    raw=request.cookies.get(_cookie_session(platform),"")
    if not raw:return None
    try:
        obj=json.loads(_cipher().decrypt(raw.encode("ascii"),
                  ttl=MAX_SESSION_DAYS*86400).decode("utf-8"))
        if (not isinstance(obj,dict) or obj.get("platform")!=platform or
            not obj.get("access_token") or not obj.get("csrf")):
            return None
        if float(obj.get("expires_at",0)) <= time.time()+20:
            if platform!="tiktok" or not obj.get("refresh_token"):
                return None
        return obj
    except (InvalidToken,ValueError,UnicodeError,TypeError):return None

def _write_session(response,platform,obj):
    encoded=json.dumps(obj,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    if len(encoded)>2500:
        raise HTTPException(400,"La sesión supera el tamaño admitido.")
    encrypted=_cipher().encrypt(encoded).decode("ascii")
    _cookie_set(response,_cookie_session(platform),encrypted,MAX_SESSION_DAYS*86400)

def _clear_session(response,platform):
    response.delete_cookie(_cookie_session(platform),path="/",secure=True,httponly=True,samesite="lax")

def _clear_state(response,platform):
    response.delete_cookie(_cookie_state(platform),path="/",secure=True,httponly=True,samesite="lax")

def _form(url,params):
    req=urllib.request.Request(url,data=urllib.parse.urlencode(params).encode("utf-8"),
        method="POST",headers={"Content-Type":"application/x-www-form-urlencoded",
                               "Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=25) as result:
        return json.load(result)

def _get(url,params=None,token=None):
    uri=url
    if params:
        uri+="?"+urllib.parse.urlencode(params)
    headers={"Accept":"application/json"}
    if token:
        headers["Authorization"]="Bearer "+token
    with urllib.request.urlopen(urllib.request.Request(uri,headers=headers),timeout=25) as result:
        return json.load(result)

def _authorized_url(platform,state):
    key,_=_env(platform)
    common={"client_id":key,"redirect_uri":_callback(platform),
            "response_type":"code","state":state}
    if platform=="instagram":
        common.update({"scope":"instagram_business_basic",
                       "enable_fb_login":"0","force_authentication":"1"})
        url="https://www.instagram.com/oauth/authorize"
    elif platform=="facebook":
        common.update({"scope":"pages_show_list",
                       "auth_type":"rerequest"})
        url="https://www.facebook.com/"+GRAPH_VERSION+"/dialog/oauth"
    else:
        common["client_key"]=common.pop("client_id")
        common["scope"]="user.info.basic"
        url="https://www.tiktok.com/v2/auth/authorize/"
    return url+"?"+urllib.parse.urlencode(common)

def _token_instagram(code):
    client_id,secret=_env("instagram")
    d=_form("https://api.instagram.com/oauth/access_token",
        {"client_id":client_id,"client_secret":secret,"grant_type":"authorization_code",
         "redirect_uri":_callback("instagram"),"code":code})
    token=d.get("access_token","")
    if not token:raise RuntimeError("Instagram no devolvió autorización.")
    expiry=3600
    try:
        long=_get("https://graph.instagram.com/access_token",
                  {"grant_type":"ig_exchange_token","client_secret":secret,"access_token":token})
        token=long.get("access_token") or token
        expiry=int(long.get("expires_in",expiry))
    except Exception:
        # Short-lived tokens work but will require reconnection sooner.
        pass
    profile=_get("https://graph.instagram.com/me",
                 {"fields":"id,username","access_token":token})
    if not profile.get("id"):raise RuntimeError("Instagram no permitió consultar la cuenta.")
    return {"access_token":token,"expires_at":time.time()+max(600,expiry),
            "account_id":str(profile["id"]),"display_name":str(profile.get("username","Cuenta de Instagram"))[:70],
            "account_kind":"professional"}

def _token_tiktok(code):
    key,secret=_env("tiktok")
    data=_form("https://open.tiktokapis.com/v2/oauth/token/",
      {"client_key":key,"client_secret":secret,"code":code,"grant_type":"authorization_code",
       "redirect_uri":_callback("tiktok")})
    if data.get("error"):raise RuntimeError("TikTok rechazó la autorización.")
    token=str(data.get("access_token") or "")
    if not token:raise RuntimeError("TikTok no devolvió autorización.")
    info=_get("https://open.tiktokapis.com/v2/user/info/",
              {"fields":"open_id,display_name"},token=token)
    if info.get("error",{}).get("code") not in (None,"ok"):
        raise RuntimeError("TikTok no permitió consultar el perfil.")
    user=info.get("data",{}).get("user") or {}
    if not user.get("open_id"):raise RuntimeError("TikTok no confirmó el usuario.")
    return {"access_token":token,
            "refresh_token":str(data.get("refresh_token") or ""),
            "expires_at":time.time()+int(data.get("expires_in",7200)),
            "refresh_expires_at":time.time()+int(data.get("refresh_expires_in",15552000)),
            "account_id":str(user["open_id"]),
            "display_name":str(user.get("display_name") or "Cuenta TikTok")[:70],
            "scope":str(data.get("scope") or "")[:200]}

def _token_facebook(code):
    client_id,secret=_env("facebook")
    data=_get("https://graph.facebook.com/"+GRAPH_VERSION+"/oauth/access_token",
        {"client_id":client_id,"client_secret":secret,"redirect_uri":_callback("facebook"),"code":code})
    token=data.get("access_token","")
    if not token:raise RuntimeError("Facebook no devolvió autorización.")
    expiry=int(data.get("expires_in",3600))
    try:
        long=_get("https://graph.facebook.com/"+GRAPH_VERSION+"/oauth/access_token",
            {"grant_type":"fb_exchange_token","client_id":client_id,
             "client_secret":secret,"fb_exchange_token":token})
        token=long.get("access_token") or token
        expiry=int(long.get("expires_in",expiry))
    except Exception:
        pass
    profile=_get("https://graph.facebook.com/"+GRAPH_VERSION+"/me",
                 {"fields":"id,name","access_token":token})
    if not profile.get("id"):raise RuntimeError("Facebook no confirmó la cuenta.")
    # Connects a Facebook identity; Pages require permissions and a managed Page.
    pages=[]
    try:
        result=_get("https://graph.facebook.com/"+GRAPH_VERSION+"/me/accounts",
                  {"fields":"id,name","limit":"25","access_token":token})
        pages=[{"id":str(p.get("id") or ""),"name":str(p.get("name") or "")[:65]}
               for p in result.get("data",[]) if p.get("id")]
    except Exception:
        pages=[]
    return {"access_token":token,"expires_at":time.time()+max(600,expiry),
            "account_id":str(profile["id"]),
            "display_name":str(profile.get("name","Cuenta Facebook"))[:70],
            "pages":pages[:25],"account_kind":"facebook"}

def _renew_tiktok(obj):
    if float(obj.get("expires_at",0))>time.time()+240:
        return obj,False
    if float(obj.get("refresh_expires_at",0))<time.time()+120:
        return None,False
    key,secret=_env("tiktok")
    data=_form("https://open.tiktokapis.com/v2/oauth/token/",
        {"client_key":key,"client_secret":secret,
         "grant_type":"refresh_token","refresh_token":obj["refresh_token"]})
    if not data.get("access_token"):return None,False
    new=dict(obj)
    new["access_token"]=data["access_token"]
    new["refresh_token"]=data.get("refresh_token") or new["refresh_token"]
    new["expires_at"]=time.time()+int(data.get("expires_in",7200))
    new["refresh_expires_at"]=time.time()+int(data.get("refresh_expires_in",15552000))
    return new,True

def _safe_error(exc):
    # Do not leak OAuth codes, secrets, access tokens, request paths, or provider payloads.
    if isinstance(exc,urllib.error.HTTPError):
        return "Proveedor rechazó la autorización (HTTP "+str(exc.code)+")."
    if isinstance(exc,RuntimeError):
        return str(exc)[:100]
    return "El proveedor no pudo completar la conexión."

def _public_info(platform,obj):
    return {
        "name":LABELS[platform],
        "configured":_configured(platform),
        "connected":bool(obj),
        "display_name":obj.get("display_name","") if obj else "",
        "account_id":obj.get("account_id","") if obj else "",
        "pages":[{"id":p["id"],"name":p["name"]} for p in obj.get("pages",[])] if obj and platform=="facebook" else [],
        "connect_url":"/api/social/connect/"+platform,
        "redirect_uri":_callback(platform),
        "publishing_enabled":False,
        "connection_note":{
            "instagram":"Requiere cuenta profesional (Empresa o Creador). Publicar exige un permiso adicional.",
            "facebook":"Conecta tu cuenta para consultar páginas administradas. Publicar en una página requiere permisos adicionales.",
            "tiktok":"Login Kit vincula la cuenta. Publicación directa requiere video.publish y aprobación de TikTok.",
        }[platform],
        "csrf":obj["csrf"] if obj else None,
    }

def install_social_connections(app):
    @app.get("/api/social/connections")
    def connections(request:Request):
        payload={}
        refreshed={}
        for platform in SOCIALS:
            session=_read_session(request,platform)
            if session and platform=="tiktok":
                try:
                    session,changed=_renew_tiktok(session)
                    if changed:refreshed[platform]=session
                except Exception:
                    session=None
            payload[platform]=_public_info(platform,session)
        resp=JSONResponse({"platforms":payload,"setup_docs":SETUP_DOC})
        for platform,obj in refreshed.items():_write_session(resp,platform,obj)
        resp.headers["Cache-Control"]="no-store"
        return resp

    @app.get("/api/social/connect/{platform}")
    def connect(platform:str,request:Request):
        if platform not in SOCIALS:raise HTTPException(404,"Plataforma no compatible.")
        if not _configured(platform):
            return RedirectResponse("/?social_setup="+platform+"#social-hub",status_code=302)
        state=secrets.token_urlsafe(32)
        response=RedirectResponse(_authorized_url(platform,state),status_code=302)
        _cookie_set(response,_cookie_state(platform),state,600)
        response.headers["Cache-Control"]="no-store"
        return response

    @app.get("/api/social/callback/{platform}")
    def callback(platform:str,request:Request,code:str="",state:str="",error:str=""):
        if platform not in SOCIALS:raise HTTPException(404,"Plataforma no compatible.")
        saved=request.cookies.get(_cookie_state(platform),"")
        if not saved or not state or not hmac.compare_digest(saved,state):
            raise HTTPException(403,"OAuth no coincide. Vuelve a conectar desde ClipForge.")
        if not _configured(platform):
            raise HTTPException(503,"El administrador no ha configurado OAuth.")
        if error or not code or len(code)>4096:
            response=RedirectResponse("/?social_cancelled="+platform+"#social-hub",status_code=302)
            _clear_state(response,platform)
            return response
        try:
            if platform=="instagram":session=_token_instagram(code)
            elif platform=="tiktok":session=_token_tiktok(code)
            else:session=_token_facebook(code)
        except Exception as exc:
            # Only stable public error category; never embed provider error strings.
            response=RedirectResponse("/?social_error="+platform+"#social-hub",status_code=302)
            _clear_state(response,platform)
            return response
        session["platform"]=platform
        session["csrf"]=secrets.token_urlsafe(24)
        response=RedirectResponse("/?social_connected="+platform+"#social-hub",status_code=302)
        _write_session(response,platform,session)
        _clear_state(response,platform)
        response.headers["Cache-Control"]="no-store"
        return response

    @app.post("/api/social/disconnect/{platform}")
    def disconnect(platform:str,request:Request):
        if platform not in SOCIALS:raise HTTPException(404,"Plataforma no compatible.")
        session=_read_session(request,platform)
        if not session:raise HTTPException(401,"La cuenta no está conectada.")
        origin=request.headers.get("origin","")
        csrf=request.headers.get("x-clipforge-csrf","")
        if origin!=PUBLIC_URL or not csrf or not hmac.compare_digest(csrf,session["csrf"]):
            raise HTTPException(403,"Solicitud no autorizada.")
        response=JSONResponse({"ok":True,"note":"Sesión local desconectada. Revoca el permiso en la red social si lo deseas."})
        _clear_session(response,platform)
        return response
