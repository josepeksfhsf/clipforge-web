import json, math, os, re, shutil, subprocess, tempfile, threading, time, uuid
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Body
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from smart_engine import choose_clips, fetch_trends, REGIONS
from social_studio import create_social_copy, PLATFORMS, STYLES
from youtube_publisher import install_youtube_publisher
from social_connections import install_social_connections
from media_enhance import make_subtitles, make_robot_voice, subtitle_filter

BASE=Path(__file__).parent
ROOT=Path(tempfile.gettempdir())/"clipforge_web"
ROOT.mkdir(exist_ok=True)
app=FastAPI(title="ClipForge")
jobs={}
mutex=threading.RLock()
slot=threading.BoundedSemaphore(1)
MAX_DURATION_SECONDS=60*60
MAX_BYTES=500*1024*1024

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

def download_video(url,folder,output_quality="720"):
    import yt_dlp
    max_height=1080 if output_quality=="1080" else 720
    # Prefer best separated video+audio in chosen maximum quality; progressive as fallback.
    selected_format=f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b"
    opts={"outtmpl":str(folder/"source.%(ext)s"),"format":selected_format,
          "merge_output_format":"mp4","noplaylist":True,"quiet":True,"no_warnings":True,
          "socket_timeout":20,"retries":1,"max_filesize":MAX_BYTES,
          "js_runtimes":{"node":{"path":"/usr/local/bin/node"}}}
    with yt_dlp.YoutubeDL(opts) as ydl:
        meta=ydl.extract_info(url,download=False)
        if meta.get("is_live") or float(meta.get("duration") or 0)>MAX_DURATION_SECONDS:
            raise ValueError("El video debe estar grabado y durar como máximo 60 minutos.")
        ydl.download([url])
    found=[p for p in folder.glob("source.*") if p.is_file() and not p.name.endswith(".part")]
    if not found:raise ValueError("No se pudo descargar ese video autorizado.")
    result=max(found,key=lambda p:p.stat().st_size)
    if result.stat().st_size>MAX_BYTES:raise ValueError("El video supera el límite de 500 MB.")
    return result

def render(j,url,uploaded,length,count,title,manual_start,smart_mode,region,output_quality="720",subtitles=False,robot_voice=False,voice_text=""):
    work=Path(jobs[j]["folder"])
    try:
        with slot:
            set_status(j,status="working",progress=10,message="Comprobando acceso al video...")
            source=Path(uploaded) if uploaded else download_video(url,work,output_quality)
            set_status(j,progress=25,message="Analizando duración...")
            data=json.loads(command(["ffprobe","-v","error","-show_format","-show_streams","-of","json",str(source)],30))
            if not any(x.get("codec_type")=="video" for x in data.get("streams",[])):
                raise ValueError("El archivo no contiene video.")
            has_audio=any(x.get("codec_type")=="audio" for x in data.get("streams",[]))
            duration=float(data.get("format",{}).get("duration",0))
            if not math.isfinite(duration) or duration<2 or duration>MAX_DURATION_SECONDS:
                raise ValueError("El video debe durar entre 2 segundos y 60 minutos.")
            count=min(count,max(1,int(duration//min(length,duration-0.15))))
            smart_data=None
            if smart_mode and manual_start < 0:
                set_status(j,progress=26,message="Analizando audio, escenas, voz y tendencias actuales...")
                try:
                    picks,trends=choose_clips(source,duration,length,count,region,allow_speech=True)
                    smart_data={"region":trends["region"],"trend_source":trends["source"],
                                "trends_available":trends["available"],"speech_analyzed":any(p["speech_analyzed"] for p in picks),
                                "disclaimer":"Índice experimental 1-100. NO es probabilidad porcentual de viralidad."}
                    starts=[p["start"] for p in picks]
                    actual=min(length,duration-0.1)
                    count=len(starts)
                    set_status(j,analysis=smart_data,progress=30,message="Momentos seleccionados; generando Shorts...")
                except Exception:
                    # If signal analysis fails, fall back to normal cutting without a fake AI score.
                    smart_data={"unavailable":True,"disclaimer":"Análisis inteligente no disponible; cortes automáticos."}
                    set_status(j,analysis=smart_data)
                    smart_mode=False
            if smart_mode and manual_start < 0 and starts:
                pass
            elif manual_start >= 0:
                if manual_start >= duration-2:
                    raise ValueError("El segundo de inicio debe dejar al menos 2 segundos de video.")
                actual=min(length,duration-manual_start-0.1)
                count=min(count,max(1,int(math.ceil((duration-manual_start-2)/length))))
                starts=[round(manual_start+i*length,2) for i in range(count)]
            else:
                actual=min(length,duration-0.1)
                count=min(count,max(1,int(duration//actual)))
                starts=[max(0,round((i+0.5)*duration/count-actual/2,2)) for i in range(count)]
            output_width,output_height=(1080,1920) if output_quality=="1080" else (720,1280)
            clips=[]
            for i,start in enumerate(starts):
                clip_duration=round(min(actual,duration-start-0.1),2)
                if clip_duration < 2:
                    break
                set_status(j,progress=30+int(i/count*60),message=f"Creando clip {i+1} de {count}...")
                out=work/f"short_{i+1}.mp4"
                vf=(f"scale={output_width}:{output_height}:force_original_aspect_ratio=increase,"
                    f"crop={output_width}:{output_height},setsar=1,format=yuv420p")
                subtitle_text=""
                captions_count=0
                if subtitles:
                    set_status(j,message=f"Transcribiendo subtítulos del clip {i+1} de {count}...")
                    srt=work/f"subtitle_{i+1}.srt"
                    subtitle_text,captions_count=make_subtitles(source,start,clip_duration,srt)
                if title.strip():
                    (work/"caption.txt").write_text(title[:80],encoding="utf-8")
                    title_y="h*0.10" if captions_count else "h*0.82"
                    fontsize=46 if output_quality=="1080" else 32
                    border=17 if output_quality=="1080" else 12
                    vf+=",drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile="+str(work/"caption.txt")+f":fontcolor=white:fontsize={fontsize}:box=1:boxcolor=black@0.65:boxborderw={border}:x=(w-text_w)/2:y="+title_y
                if captions_count:
                    vf+=","+subtitle_filter(srt)
                audio_path=None
                if robot_voice:
                    audio_path=work/f"voice_{i+1}.wav"
                    narration=voice_text or title or "Mira este momento y cuéntame qué opinas."
                    make_robot_voice(narration,audio_path)
                cmd=["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
                     "-ss",str(start),"-i",str(source)]
                if audio_path:
                    cmd.extend(["-i",str(audio_path)])
                cmd.extend(["-t",str(clip_duration),"-map","0:v:0","-vf",vf,
                            "-c:v","libx264","-preset","veryfast","-crf",
                            "23" if output_quality=="1080" else "24","-threads","1"])
                if audio_path and has_audio:
                    cmd.extend(["-filter_complex",
                                "[0:a:0]volume=0.55[bg];[bg][1:a:0]amix=inputs=2:duration=first:dropout_transition=0:weights=1 2:normalize=1[mix]",
                                "-map","[mix]"])
                elif audio_path:
                    cmd.extend(["-map","1:a:0","-af","apad"])
                else:
                    cmd.extend(["-map","0:a:0?"])
                cmd.extend(["-c:a","aac","-b:a","96k","-movflags","+faststart",str(out)])
                command(cmd,230)
                result={"name":f"Short {i+1}","ordinal":i+1,"start":start,"length":round(clip_duration,1),"url":f"/api/jobs/{j}/clips/{i+1}","quality":output_quality+"p","width":output_width,"height":output_height,
                        "subtitles_added":bool(captions_count),"subtitle_blocks":captions_count,
                        "robot_voice_added":bool(audio_path)}
                if subtitle_text:
                    result["transcript"]=subtitle_text[:550]
                if smart_mode and smart_data and not smart_data.get("unavailable") and i<len(picks):
                    result.update({"score":picks[i]["score"],"reasons":picks[i]["reasons"],
                                   "matched_trends":picks[i]["matched_trends"],"transcript":result.get("transcript") or picks[i]["transcript"],
                                   "speech_analyzed":picks[i]["speech_analyzed"]})
                clips.append(result)
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
def health():return {"status":"ok","service":"ClipForge Web","smart_analysis":True,"max_duration_minutes":60,"max_file_mb":500,"subtitles_available":True,"robot_voice_available":True,"max_clips_per_job":12,"distinct_clips":True,"output_qualities":["720p","1080p"],"default_quality":"720p"}

@app.get("/api/trends")
def trends(region:str="CL"):
    if region not in REGIONS:
        raise HTTPException(400,"Región no admitida.")
    return fetch_trends(region)

@app.post("/api/jobs",status_code=202)
async def create(url:str=Form(""),file:UploadFile|None=File(None),
                 length:int=Form(30),count:int=Form(2),title:str=Form(""),output_quality:str=Form("720"),
                 start:float=Form(-1),smart:bool=Form(False),region:str=Form("CL"),
                 subtitles:bool=Form(False),robot_voice:bool=Form(False),voice_text:str=Form(""),
                 rights:bool=Form(False)):
    if not rights:raise HTTPException(400,"Confirma que tienes derechos para utilizar el video.")
    if length not in (15,30,45,60) or not 1 <= count <= 12:raise HTTPException(400,"Elige entre 1 y 12 clips de 15, 30, 45 o 60 segundos.")
    if output_quality not in ("720","1080"):raise HTTPException(400,"Calidad inválida. Elige 720p o 1080p.")
    if not math.isfinite(start) or start < -1 or start > MAX_DURATION_SECONDS:
        raise HTTPException(400,"El segundo de inicio no es válido.")
    if region not in REGIONS: raise HTTPException(400,"Región no válida.")
    if len(voice_text)>180: raise HTTPException(400,"La narración admite máximo 180 caracteres.")
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
                    if size>MAX_BYTES:raise HTTPException(413,"El archivo supera los 500 MB. Usa un archivo más comprimido.")
                    f.write(chunk)
            if size<1024:raise HTTPException(400,"Archivo vacío.")
        with mutex:jobs[j]={"status":"queued","progress":0,"message":"En cola...","created":time.time(),"folder":str(folder),"clips":[],"analysis":None,"topic_hint":title[:80],"copy_cache":{},"output_quality":output_quality}
        threading.Thread(target=render,args=(j,normalized,str(uploaded) if uploaded else None,length,count,title,start,smart,region,output_quality,subtitles,robot_voice,voice_text),daemon=True).start()
    except Exception:
        shutil.rmtree(folder,ignore_errors=True)
        raise
    return {"id":j,"status":"queued"}

@app.get("/api/jobs/{j}")
def status(j:str):
    with mutex:
        if j not in jobs:raise HTTPException(404,"Trabajo no encontrado.")
        d=jobs[j]
        return {k:d[k] for k in ("status","progress","message","clips","analysis")}


@app.get("/api/social/integrations")
def social_integrations():
    """Public capability description only; never exposes user account/token data."""
    return {
        "publishing_available": "youtube_after_oauth_setup",
        "note": "Los borradores están listos. La publicación automática desde esta web requiere autorización OAuth o una API aprobada; conectar Metricool a ChatGPT no autoriza al servidor ClipForge.",
        "metricool_connections_url": "https://app.metricool.com/brands/connections",
        "networks": [{"id": slug, "label": data["label"], "upload_url": data["url"], "state": "no_vinculada_a_clipforge"}
                     for slug, data in PLATFORMS.items()]
    }

@app.post("/api/jobs/{j}/copy")
def social_copy(j: str, params: dict = Body(...)):
    try:
        n = int(params.get("number", 1))
        platform = str(params.get("platform", "youtube"))
        style = str(params.get("style", "intriga"))
        hint = str(params.get("topic", ""))[:120].strip()
    except (ValueError, TypeError):
        raise HTTPException(400, "Datos para el texto inválidos.")
    if platform not in PLATFORMS or style not in STYLES or len(hint) > 100:
        raise HTTPException(400, "Selecciona una red social, un estilo y un tema válidos.")
    with mutex:
        if j not in jobs or jobs[j]["status"] != "done":
            raise HTTPException(404, "Primero genera un Short; este trabajo ya no está disponible.")
        job = jobs[j]
        if not 1 <= n <= len(job["clips"]):
            raise HTTPException(404, "Ese clip no está disponible.")
        clip = dict(job["clips"][n - 1])
        key = (n, platform, style, hint)
        cached = job["copy_cache"].get(key)
        job_hint = job.get("topic_hint", "")
    if cached:
        return cached
    try:
        result = create_social_copy(clip, platform, style, hint or job_hint)
    except Exception:
        raise HTTPException(503, "No fue posible generar el texto. Vuelve a intentarlo.")
    # Cache per job so repeated requests don't repeat an optional model call.
    with mutex:
        if j in jobs and len(jobs[j]["copy_cache"]) < 30:
            jobs[j]["copy_cache"][key] = result
    return result

@app.get("/api/jobs/{j}/clips/{number}")
def clip(j:str,number:int):
    with mutex:
        if j not in jobs or jobs[j]["status"]!="done" or number<1 or number>len(jobs[j]["clips"]):
            raise HTTPException(404,"Clip no encontrado.")
        path=Path(jobs[j]["folder"])/f"short_{number}.mp4"
    if not path.is_file():raise HTTPException(404,"Clip no disponible.")
    return FileResponse(path,media_type="video/mp4",filename=f"ClipForge_Short_{number}.mp4")

install_youtube_publisher(app,jobs,mutex)
install_social_connections(app)

app.mount("/",StaticFiles(directory=str(BASE/"static"),html=True),name="site")
