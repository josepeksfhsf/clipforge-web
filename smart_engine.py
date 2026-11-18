"""ClipForge: ranking experimental de clips; no predice probabilidad real de viralidad."""
import array
import json
import math
import re
import statistics
import subprocess
import threading
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

REGIONS = {"CL": "Chile", "US": "Estados Unidos", "MX": "México", "AR": "Argentina", "ES": "España"}
_CACHE = {}
_LOCK = threading.Lock()
TREND_URL = "https://trends.google.com/trending/rss?geo={region}"

def fetch_trends(region="CL"):
    region = region if region in REGIONS else "CL"
    with _LOCK:
        entry = _CACHE.get(region)
        if entry and time.time() - entry["time"] < 1200:
            return dict(entry["payload"])
    payload = {"region": region, "country": REGIONS[region], "source": "Google Trends: Trending Now (RSS)", "items": [], "available": False, "fetched_at": None}
    try:
        request = urllib.request.Request(TREND_URL.format(region=region), headers={"User-Agent": "ClipForge/2.0 (trend research for videos)"})
        with urllib.request.urlopen(request, timeout=8) as response:
            data = response.read(200_000)
        root = ET.fromstring(data)
        items = []
        ns = "{https://trends.google.com/trending/rss}"
        for item in root.findall(".//item")[:30]:
            title = (item.findtext("title") or "").strip()
            if title:
                items.append({"topic": title[:110], "traffic": (item.findtext(ns + "approx_traffic") or "").strip(), "published": (item.findtext("pubDate") or "").strip()})
        payload.update(items=items, available=bool(items), fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        with _LOCK:
            _CACHE[region] = {"time": time.time(), "payload": payload}
    except Exception:
        # Never invent live trend data; keep empty and mark unavailable.
        pass
    return payload

def _run(args, timeout=70):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[-320:])
    return p

def audio_profile(path, duration):
    """One RMS observation per second; silence-aware without loading full audio in memory."""
    try:
        args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path),
                "-vn", "-ac", "1", "-ar", "4000", "-f", "s16le", "pipe:1"]
        p = _run(args, timeout=min(120, max(25, int(duration*0.3))))
        pcm = array.array("h")
        pcm.frombytes(p.stdout[:(len(p.stdout)//2)*2])
        if not pcm:
            return []
        import sys
        if sys.byteorder == "big":
            pcm.byteswap()
        levels = []
        block = 4000
        for i in range(0, len(pcm), block):
            piece = pcm[i:i+block]
            if not piece:
                continue
            energy = math.sqrt(sum(int(x)*int(x) for x in piece) / len(piece))
            levels.append(math.log1p(energy))
        return levels
    except Exception:
        return []

def scene_profile(path, duration):
    """Downsampled scene boundary positions to keep the analysis light."""
    try:
        args=["ffmpeg","-nostdin","-hide_banner","-loglevel","info","-i",str(path),"-an",
              "-vf","fps=1/2,scale=160:90,select=gt(scene\\,0.10),showinfo",
              "-f","null","-"]
        p=subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=65)
        text=p.stderr.decode("utf-8","replace")
        return [float(v) for v in re.findall(r"pts_time:(\d+(?:\.\d+)?)",text) if float(v)<duration]
    except Exception:
        return []

def _basic_features(start, length, audio, scenes):
    beg = max(0, int(start))
    end = int(start+length)
    vals=audio[beg:end]
    if not vals:
        energy=0.38
        variety=0.35
    else:
        baseline = max(max(audio,default=0),1.0)
        energy=min(1.0,statistics.fmean(vals)/baseline)
        variety=min(1.0,(max(vals)-min(vals))/max(baseline,1))
    cuts=sum(start<=t<start+length for t in scenes)
    motion=min(1.,cuts/max(2.,length/12.))
    return energy,variety,motion,cuts

STOPWORDS={"para","sobre","como","cuando","donde","porque","tiene","tienen","este","esta","estos","estas","desde","hasta","estos","entre","otros","otras","todos","todas","ahora","nueva","nuevo","noticias","chile","today","with","about","from","that","this","your","their","video","shorts","clips"}

def _terms(s):
    s=unicodedata.normalize("NFKD",s.lower())
    s="".join(ch for ch in s if not unicodedata.combining(ch))
    return {x for x in re.findall(r"[a-z0-9]{4,}",s) if x not in STOPWORDS}

HOOKS=("no lo vas a creer","mira esto","no sabias","sabias que","increible","sorprendente","de repente","pero entonces","nunca imagine","nadie esperaba","no esperaba","secreto","sorpresa","ultimo segundo","lo peor","lo mejor","no puede ser","resulta que","que paso","por que","cuando vi","cuidado","espera","final","misterio","impactante","increible")
def text_score(text, trends):
    norm=unicodedata.normalize("NFKD",text.lower())
    norm="".join(ch for ch in norm if not unicodedata.combining(ch))
    hook = min(1., sum(1 for x in HOOKS if x in norm)/2.)
    spoken = min(1.,len(text.split())/35.)
    tokens=_terms(text)
    matches=[]
    for trend in trends:
        tr=_terms(trend.get("topic",""))
        if not tr:continue
        overlap=tokens & tr
        if (len(overlap)>=2 or (len(tr)==1 and bool(overlap))):
            matches.append(trend["topic"])
    return hook,spoken,list(dict.fromkeys(matches))[:3]

_MODEL = None
_MODEL_LOCK = threading.Lock()
def transcribe_excerpt(path, start, seconds=22):
    """Genuine local AI transcription (Whisper tiny, CPU int8), optional on constrained instances."""
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel
            _MODEL=WhisperModel("tiny",device="cpu",compute_type="int8",cpu_threads=1,num_workers=1,download_root="/app/models")
        model=_MODEL
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            audio=str(Path(root)/"sample.wav")
            _run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
                  "-ss",str(start),"-i",str(path),"-t",str(seconds),
                  "-vn","-ar","16000","-ac","1","-c:a","pcm_s16le",audio],timeout=30)
            segments,_=model.transcribe(audio,beam_size=1,best_of=1,condition_on_previous_text=False,vad_filter=False)
            text=" ".join(s.text.strip() for s in segments)
            return text[:650]


def sample_audio_excerpt(path, start, seconds=5):
    """Quick audio sampling at a seek point; avoids decoding entire hour-long sources."""
    try:
        p=_run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error",
                "-ss",str(round(start,2)),"-i",str(path),"-t",str(seconds),
                "-vn","-ac","1","-ar","2000","-f","s16le","pipe:1"],timeout=18)
        pcm=array.array("h")
        pcm.frombytes(p.stdout[:(len(p.stdout)//2)*2])
        if not pcm:return 0.30,0.20
        blocks=[]
        for i in range(0,len(pcm),500):
            a=pcm[i:i+500]
            if a:
                blocks.append(math.sqrt(sum(int(x)*int(x) for x in a)/len(a)))
        if not blocks:return 0.30,0.20
        energy=min(1.,math.log1p(statistics.fmean(blocks))/9.2)
        variation=min(1.,(max(blocks)-min(blocks))/max(1.,max(blocks)))
        return energy,variation
    except Exception:
        return 0.30,0.20

def choose_clips(path, duration, requested_length, count, region="CL", allow_speech=True):
    """Return ranked nonoverlapping clip suggestions with transparent evidence."""
    duration=float(duration)
    length=min(float(requested_length),duration-0.15)
    trends=fetch_trends(region)
    long_source=duration>900
    if long_source:
        # 24 seek-based excerpts distributed across the *whole* video.
        # Full-file scene/audio decoding can exceed free-tier CPU limits.
        audio=[]
        scenes=[]
        last=max(0.,duration-length)
        starts=[round(last*i/23,2) for i in range(24)]
    else:
        audio=audio_profile(path,duration)
        scenes=scene_profile(path,duration)
        step=max(3.,min(12.,length/3.))
        max_start=max(0.,duration-length)
        starts=[0.] if max_start<step else [round(float(x)*step,2) for x in range(int(max_start/step)+1)]
        if max_start>0 and (not starts or max_start-starts[-1]>1):starts.append(round(max_start,2))
        starts=starts[:110]
    candidates=[]
    for st in starts:
        if long_source:
            energy,variety=sample_audio_excerpt(path,st,4)
            motion,cuts=0.,0
        else:
            energy,variety,motion,cuts=_basic_features(st,length,audio,scenes)
        base=30+22*energy+10*variety+16*motion+5*(length<=45)
        candidates.append({"start":st,"energy":energy,"variety":variety,"motion":motion,"cuts":cuts,"base":base,"text":"","match":[],"hook":0,"speech":0,"ai":False})
    candidates.sort(key=lambda x:x["base"],reverse=True)
    shortlist=[]
    for c in candidates:
        if all(abs(c["start"]-p["start"])>=(max(length*.8,duration/(count*3))) for p in shortlist):
            shortlist.append(c)
        if len(shortlist)>=max(3,count):break
    # Whisper tiny is attempted only on shortlisted excerpts, never transcribes the whole source.
    if allow_speech:
        for c in shortlist:
            try:
                transcript=transcribe_excerpt(path,c["start"],min(20,length))
                c["text"]=transcript
                c["ai"]=bool(transcript.strip())
                c["hook"],c["speech"],c["match"]=text_score(transcript,trends["items"])
            except Exception:
                # Keep working even when speech recognition cannot run.
                c["ai"]=False
    for c in shortlist:
        matched=min(1.,len(c["match"])/2.)
        score=int(round(min(100,max(1,c["base"]+9*c["hook"]+6*c["speech"]+12*matched))))
        c["score"]=score
        reasons=[]
        if c["motion"]>.3:reasons.append("cambios visuales")
        if c["energy"]>.62:reasons.append("actividad sonora")
        if c["hook"]>.1:reasons.append("frase de intriga o sorpresa")
        if c["match"]:reasons.append("coincide con búsquedas en tendencia")
        if long_source:reasons.append("muestra analizada de un video largo")
        if not reasons:reasons.append("segmento candidato para revisión")
        c["reasons"]=reasons
    shortlist.sort(key=lambda x:x["score"],reverse=True)
    selected=shortlist[:count]
    if len(selected)<count:
        for c in candidates:
            if all(abs(c["start"]-p["start"])>=(max(length*.8,duration/(count*3))) for p in selected):
                c.update(score=int(round(min(100,c["base"]))),reasons=["candidato alternativo"],ai=False,match=[],text="")
                selected.append(c)
            if len(selected)>=count:break
    out=[]
    for c in selected:
        out.append({"start":c["start"],"score":c["score"],"reasons":c["reasons"],"transcript":c["text"][:260],
                    "matched_trends":c["match"],"speech_analyzed":c["ai"]})
    return out,trends
