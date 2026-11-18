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
            _MODEL=WhisperModel("tiny",device="cpu",compute_type="int8",cpu_threads=1,num_workers=1,download_root="/app/models",local_files_only=True)
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

def _speech_similarity(a, b):
    """Repeated speech detector: shared salient words and word-order shingles."""
    a=" ".join(str(a or "").lower().split())
    b=" ".join(str(b or "").lower().split())
    if not a or not b:
        return 0.0
    left=_terms(a)
    right=_terms(b)
    if len(left)>=4 and len(right)>=4:
        common=len(left & right)
        score=common/max(1,min(len(left),len(right)))
        if score>=0.82:
            return score
    aa=re.findall(r"\w+",a)
    bb=re.findall(r"\w+",b)
    if len(aa)<5 or len(bb)<5:
        return 0.0
    na={tuple(aa[i:i+4]) for i in range(len(aa)-3)}
    nb={tuple(bb[i:i+4]) for i in range(len(bb)-3)}
    return len(na & nb)/max(1,min(len(na),len(nb)))

def _spaced(start, chosen, length):
    """No repeated time ranges, even across user-requested 12 clips."""
    return all(abs(start-p["start"])>=length-0.001 for p in chosen)

def choose_clips(path, duration, requested_length, count, region="CL", allow_speech=True):
    """Choose non-overlapping, temporally spread-out moments with dialogue diversity.

    Selection is conservative: if the source is too short, fewer unique clips are
    returned; repeated spans are never fabricated to meet a requested count.
    """
    duration=float(duration)
    length=min(float(requested_length),duration-0.15)
    if length<=0:
        return [], fetch_trends(region)
    target=max(1,min(int(count),12,max(1,int((duration-0.1)//length))))
    trends=fetch_trends(region)
    long_source=duration>900
    max_start=max(0.,duration-length)

    if long_source:
        # Seek-based observations across the WHOLE source, not only the start.
        # CPU effort scales to the number of requested different clips.
        audio=[]
        scenes=[]
        samples=min(84,max(24,target*6))
        starts=[round(max_start*i/(samples-1),2) for i in range(samples)]
    else:
        audio=audio_profile(path,duration)
        scenes=scene_profile(path,duration)
        step=max(2.5,min(10.,length/4.))
        total=max(1,int(max_start/step))
        samples=min(240,total+1)
        starts=[round(max_start*i/max(1,samples-1),2) for i in range(samples)]
    # Include boundary-aligned and evenly spaced positions as fallbacks, so a
    # 3-minute video can yield twelve distinct 15-second clips if possible.
    for i in range(target):
        starts.append(round(min(max_start,i*length),2))
        if target>1:
            starts.append(round(max_start*i/(target-1),2))
    starts=sorted(set(starts))
    candidates=[]
    for st in starts:
        if long_source:
            energy,variety=sample_audio_excerpt(path,st,4)
            motion,cuts=0.,0
        else:
            energy,variety,motion,cuts=_basic_features(st,length,audio,scenes)
        base=30+22*energy+10*variety+16*motion+5*(length<=45)
        candidates.append({"start":st,"energy":energy,"variety":variety,
                           "motion":motion,"cuts":cuts,"base":base,"text":"",
                           "match":[],"hook":0,"speech":0,"ai":False})

    # For the high-cost speech model transcribe a bounded candidate pool.
    # Prioritize quality while spreading clips over the whole timeline.
    ranked=sorted(candidates,key=lambda x:x["base"],reverse=True)
    shortlist=[]
    preferred_gap=max(length,duration/max(2,target*2))
    for gap in (preferred_gap,length):
        for c in ranked:
            if c in shortlist:
                continue
            if all(abs(c["start"]-p["start"])>=gap-0.001 for p in shortlist):
                shortlist.append(c)
            if len(shortlist)>=min(18,target+5):
                break
        if len(shortlist)>=min(18,target+5):
            break
    if allow_speech:
        for c in shortlist:
            try:
                transcript=transcribe_excerpt(path,c["start"],min(18,length))
                c["text"]=transcript
                c["ai"]=bool(transcript.strip())
                c["hook"],c["speech"],c["match"]=text_score(transcript,trends["items"])
            except Exception:
                c["ai"]=False

    for c in candidates:
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

    selected=[]
    chronological_span=max(1.,duration-length)
    bins=min(target,6)
    for pool in (sorted(shortlist,key=lambda x:x["score"],reverse=True),ranked):
        while len(selected)<target:
            acceptable=[c for c in pool if c not in selected and _spaced(c["start"],selected,length)]
            # Reject near-duplicate dialogue, including different footage with same narration.
            distinct=[c for c in acceptable if all(_speech_similarity(c["text"],p["text"])<0.80
                     for p in selected)]
            if distinct:
                acceptable=distinct
            if not acceptable:
                break
            def weight(c):
                bucket=min(bins-1,int(c["start"]/chronological_span*bins))
                taken=sum(min(bins-1,int(p["start"]/chronological_span*bins))==bucket
                          for p in selected)
                return c["score"]-12*taken
            chosen=max(acceptable,key=lambda c:(weight(c),-c["start"]))
            selected.append(chosen)
        if len(selected)>=target:
            break

    if len(selected)<target:
        # Always return feasible, non-overlapping ranges instead of duplicates.
        # On a densely packed source, use exact slots with no overlap.
        extra=max(0.,duration-target*length)
        fallback=[i*(length+extra/max(1,target-1)) for i in range(target)]
        selected=[]
        for i,st in enumerate(fallback):
            st=round(min(max_start,st),2)
            closest=min(candidates,key=lambda c:abs(c["start"]-st))
            picked=dict(closest,start=st)
            if not _spaced(st,selected,length):
                continue
            picked["reasons"]=list(picked.get("reasons",[]))+["intervalo único sin solapamiento"]
            selected.append(picked)

    # Show chronological clips, not a list sorted by raw engagement heuristic.
    selected.sort(key=lambda c:c["start"])
    out=[]
    for c in selected[:target]:
        reasons=list(c["reasons"])
        if "momentos repartidos en el video" not in reasons:
            reasons.append("momentos repartidos en el video")
        out.append({"start":c["start"],"score":c["score"],"reasons":reasons,
                    "transcript":c["text"][:260],"matched_trends":c["match"],
                    "speech_analyzed":c["ai"]})
    return out,trends
