import json, math, os, re, shutil, subprocess, tempfile, threading, time, uuid
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE=Path(__file__).parent
ROOT=Path(tempfile.gettempdir())/"clipforge_web"
ROOT.mkdir(exist_ok=True)
app=FastAPI(title="ClipForge")
jobs={}
mutex=threading.RLock()
slot=threading.BoundedSemaphore(1)
MAX_BYTES=140*1024*1024

def command(args,timeout=240):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[-350:] or "Falló el procesamiento.")
    return p.stdout

SUPPORTED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtube-nocookie.com", "www.youtube-nocookie.com", "youtu.be", "www.youtu.be",
    "tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    "instagram.com", "www.instagram.com",
    "facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com",
    "fb.watch", "www.fb.watch", "vimeo.com", "www.vimeo.com",
    "dailymotion.com", "www.dailymotion.com", "dai.ly", "www.dai.ly",
    "x.com", "www.x.com", "twitter.com", "www.twitter.com",
    "twitch.tv", "www.twitch.tv", "clips.twitch.tv",
    "streamable.com", "www.streamable.com"
}
YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtube-nocookie.com", "www.youtube-nocookie.com", "youtu.be", "www.youtu.be"
}
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")

def normalize_video_url(raw):
    """Allow public supported video hosts, not arbitrary URLs or private networks."""
    raw = (raw or "").strip()
    if len(raw) > 2500:
        raise HTTPException(400, "El enlace es demasiado largo.")
    if VIDEO_ID.fullmatch(raw):
        return "https://www.youtube.com/watch?v=" + raw
    match = re.search(
        r"(?:https?://|www\.|youtube\.com/|youtu\.be/|tiktok\.com/|instagram\.com/|facebook\.com/|vimeo\.com/)[^\s<>\"']+",
        raw, re.I)
    if not match:
        raise HTTPException(400, "Pega un enlace público de video compatible (YouTube, TikTok, Instagram, Facebook, Vimeo y otros).")
    url = match.group(0).strip("()[]{}<>,.;\"'")
    if not url.startswith(("https://", "http://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (parsed.scheme not in ("http", "https") or
                parsed.username is not None or parsed.password is not None or
                parsed.port is not None or host not in SUPPORTED_HOSTS):
            raise ValueError("host")
    except ValueError:
        raise HTTPException(400, "Este dominio no está admitido. Usa un enlace de video de una plataforma compatible.")
    if not parsed.path or parsed.path == "/":
        raise HTTPException(400, "Pega la dirección de un video concreto, no de una página principal.")
    if host in YOUTUBE_HOSTS:
        path = parsed.path.rstrip("/")
        if host.endswith("youtu.be"):
            if not VIDEO_ID.fullmatch(path.lstrip("/")):
                raise HTTPException(400, "El enlace corto de YouTube no incluye un ID de video válido.")
        elif path == "/watch":
            id_value = parse_qs(parsed.query).get("v", [""])[0]
            if not VIDEO_ID.fullmatch(id_value):
                raise HTTPException(400, "Ese enlace de YouTube no contiene un video válido.")
        elif path.startswith(("/shorts/", "/live/", "/embed/", "/v/")):
            if not VIDEO_ID.fullmatch(path.split("/")[2]):
                raise HTTPException(400, "El enlace de YouTube no contiene un ID de video válido.")
        elif path.startswith("/clip/"):
            pass  # Clip links may require special support from the platform
        else:
            raise HTTPException(400, "Pega un enlace a un video, Short o directo grabado de YouTube, no una lista ni un canal.")
    return parsed._replace(scheme="https", netloc=host).geturl()

def set_status(j,**kw):
    with mutex:jobs[j].update(kw)

def download_video(url,folder):
    import yt_dlp
    opts={"outtmpl":str(folder/"source.%(ext)s"),"format":"b[height<=720]/bv*[height<=720]+ba/b",
          "merge_output_format":"mp4","noplaylist":True,"quiet":True,"no_warnings":True,
          "socket_timeout":20,"retries":1,"max_filesize":MAX_BYTES}
    with yt_dlp.YoutubeDL(opts) as ydl:
        meta=ydl.extract_info(url,download=False)
        if meta.get("is_live") or float(meta.get("duration") or 0)>900:
            raise ValueError("El video debe estar grabado y durar hasta 15 minutos.")
        ydl.download([url])
    found=[p for p in folder.glob("source.*") if p.is_file() and not p.name.endswith(".part")]
    if not found:raise ValueError("No se pudo descargar ese video autorizado.")
    result=max(found,key=lambda p:p.stat().st_size)
    if result.stat().st_size>MAX_BYTES:raise ValueError("El video supera 140 MB.")
    return result

def render(j,url,uploaded,length,count,title):
    work=Path(jobs[j]["folder"])
    try:
        with slot:
            set_status(j,status="working",progress=10,message="Comprobando acceso al video...")
            source=Path(uploaded) if uploaded else download_video(url,work)
            set_status(j,progress=25,message="Analizando duración...")
            data=json.loads(command(["ffprobe","-v","error","-show_format","-show_streams","-of","json",str(source)],30))
            if not any(x.get("codec_type")=="video" for x in data.get("streams",[])):
                raise ValueError("El archivo no contiene video.")
            duration=float(data.get("format",{}).get("duration",0))
            if not math.isfinite(duration) or duration<2 or duration>900:
                raise ValueError("El video debe durar entre 2 segundos y 15 minutos.")
            actual=min(length,duration-0.1)
            count=min(count,max(1,int(duration//actual)))
            clips=[]
            for i in range(count):
                start=max(0,round((i+0.5)*duration/count-actual/2,2))
                set_status(j,progress=30+int(i/count*60),message=f"Creando clip {i+1} de {count}...")
                out=work/f"short_{i+1}.mp4"
                vf="scale=540:960:force_original_aspect_ratio=increase,crop=540:960,setsar=1,format=yuv420p"
                if title.strip():
                    (work/"caption.txt").write_text(title[:80],encoding="utf-8")
                    vf+=",drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile="+str(work/"caption.txt")+":fontcolor=white:fontsize=27:box=1:boxcolor=black@0.65:boxborderw=12:x=(w-text_w)/2:y=h*0.82"
                command(["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y","-ss",str(start),"-i",str(source),"-t",str(actual),"-map","0:v:0","-map","0:a:0?","-vf",vf,"-c:v","libx264","-preset","ultrafast","-crf","27","-threads","1","-c:a","aac","-b:a","96k","-movflags","+faststart",str(out)],230)
                clips.append({"name":f"Short {i+1}","start":start,"length":round(actual,1),"url":f"/api/jobs/{j}/clips/{i+1}"})
            set_status(j,status="done",progress=100,message="¡Clips listos!",clips=clips)
    except Exception as e:
        msg=str(e)
        lower=msg.lower()
        if "not a bot" in lower or "sign in to confirm" in lower:
            msg="YouTube bloqueó las descargas automáticas desde este servidor. Tu enlace es válido, pero debes subir el archivo del video desde tu dispositivo."
        elif "login" in lower or "sign in" in lower or "private" in lower:
            msg="La plataforma exige iniciar sesión o el video es privado. Prueba con un enlace público o sube un archivo propio."
        elif "unsupported url" in lower or "no suitable" in lower:
            msg="La plataforma no ofrece acceso a ese tipo de enlace. Prueba con el enlace directo al video o sube el archivo."
        elif "403" in lower or "429" in lower or "forbidden" in lower:
            msg="La plataforma rechazó el acceso automático al video desde Render. Prueba subiendo un archivo propio."
        elif "timed out" in lower or "timeout" in lower:
            msg="La plataforma no respondió a tiempo. Prueba más tarde o sube un archivo propio."
        elif "youtube" in lower and "error" in lower:
            msg="No fue posible obtener ese video desde YouTube. Puedes subir el archivo original."
        elif "error" in lower and "yt_dlp" in lower:
            msg="No fue posible descargar ese enlace. Puede estar restringido por la plataforma."
        set_status(j,status="error",progress=0,message=msg[:200])
    finally:
        if uploaded:
            try:Path(uploaded).unlink(missing_ok=True)
            except OSError:pass

@app.get("/api/health")
def health():return {"status":"ok","service":"ClipForge Web"}

@app.post("/api/jobs",status_code=202)
async def create(url:str=Form(""),file:UploadFile|None=File(None),
                 length:int=Form(30),count:int=Form(2),title:str=Form(""),rights:bool=Form(False)):
    if not rights:raise HTTPException(400,"Confirma que tienes derechos para utilizar el video.")
    if length not in (15,30,45,60) or count not in (1,2,3):raise HTTPException(400,"Parámetros incorrectos.")
    if bool(url.strip())==bool(file and file.filename):raise HTTPException(400,"Elige un enlace o un archivo.")
    normalized=normalize_video_url(url) if url.strip() else ""
    with mutex:
        now=time.time()
        for key,val in list(jobs.items()):
            if now-val["created"]>3600 and val["status"] not in ("queued","working"):
                shutil.rmtree(val["folder"],ignore_errors=True);del jobs[key]
        if sum(v["status"] in ("queued","working") for v in jobs.values())>=2:
            raise HTTPException(503,"Servidor ocupado. Vuelve a intentar.")
    j=uuid.uuid4().hex
    folder=ROOT/j
    folder.mkdir(mode=0o700)
    uploaded=None
    try:
        if file and file.filename:
            ext=Path(file.filename).suffix.lower()
            if ext not in (".mp4",".mov",".mkv",".webm",".m4v"):
                raise HTTPException(400,"Formato no admitido.")
            uploaded=folder/("source"+ext)
            size=0
            with uploaded.open("wb") as f:
                while chunk:=await file.read(1024*1024):
                    size+=len(chunk)
                    if size>MAX_BYTES:raise HTTPException(413,"Máximo 140 MB.")
                    f.write(chunk)
            if size<1024:raise HTTPException(400,"Archivo vacío.")
        with mutex:jobs[j]={"status":"queued","progress":0,"message":"En cola...","created":time.time(),"folder":str(folder),"clips":[]}
        threading.Thread(target=render,args=(j,normalized,str(uploaded) if uploaded else None,length,count,title),daemon=True).start()
    except Exception:
        shutil.rmtree(folder,ignore_errors=True)
        raise
    return {"id":j,"status":"queued"}

@app.get("/api/jobs/{j}")
def status(j:str):
    with mutex:
        if j not in jobs:raise HTTPException(404,"Trabajo no encontrado.")
        d=jobs[j]
        return {k:d[k] for k in ("status","progress","message","clips")}

@app.get("/api/jobs/{j}/clips/{number}")
def clip(j:str,number:int):
    with mutex:
        if j not in jobs or jobs[j]["status"]!="done" or number<1 or number>len(jobs[j]["clips"]):
            raise HTTPException(404,"Clip no encontrado.")
        path=Path(jobs[j]["folder"])/f"short_{number}.mp4"
    if not path.is_file():raise HTTPException(404,"Clip no disponible.")
    return FileResponse(path,media_type="video/mp4",filename=f"ClipForge_Short_{number}.mp4")

app.mount("/",StaticFiles(directory=str(BASE/"static"),html=True),name="site")
