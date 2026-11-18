"""Optional Spanish speech subtitles and synthetic narration for short MP4s.

Subtitles are derived from speech in each chosen excerpt using local Whisper tiny.
Robot narration is synthesized with Debian espeak-ng (not the Loquendo service).
Never synthesize facts or upload any media without the user's opt-in.
"""
import math
import re
import subprocess
import textwrap
from pathlib import Path

def _run(args, timeout=70):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr.decode("utf-8","replace")[-350:] or "No se pudo procesar audio.")
    return p

def _srt_time(seconds):
    millis=max(0,int(round(float(seconds)*1000)))
    h,rem=divmod(millis,3600000)
    m,rem=divmod(rem,60000)
    s,ms=divmod(rem,1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def _chunks(words, width=35):
    chunks=[]
    current=[]
    for word in words:
        if current and len(" ".join(current+[word]))>width:
            chunks.append(" ".join(current))
            current=[]
        current.append(word)
    if current:chunks.append(" ".join(current))
    return chunks

def make_subtitles(source: Path, start: float, length: float, target: Path):
    """Burn-ready SRT with relative timings. Return transcript and caption count."""
    import smart_engine as smart
    wav=target.with_suffix(".wav")
    try:
        _run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
              "-ss",str(start),"-i",str(source),"-t",str(min(length,60)),
              "-vn","-ac","1","-ar","16000","-c:a","pcm_s16le",str(wav)],timeout=48)
        with smart._MODEL_LOCK:
            if smart._MODEL is None:
                from faster_whisper import WhisperModel
                smart._MODEL=WhisperModel("tiny",device="cpu",compute_type="int8",
                                         cpu_threads=1,num_workers=1,download_root="/app/models")
            segments,_=smart._MODEL.transcribe(str(wav),beam_size=1,best_of=1,
                         condition_on_previous_text=False,vad_filter=True,language="es")
            captions=[]
            transcript=[]
            for seg in segments:
                raw=" ".join(str(seg.text).split())
                if not raw:
                    continue
                a=max(0.,float(seg.start))
                b=min(float(length),float(seg.end))
                if not math.isfinite(a) or not math.isfinite(b) or b-a<0.20:
                    continue
                transcript.append(raw)
                pieces=_chunks(raw.split(),36)
                for i,piece in enumerate(pieces):
                    left=a+(b-a)*i/len(pieces)
                    right=a+(b-a)*(i+1)/len(pieces)
                    if right-left<0.20:
                        continue
                    captions.append((left,right,piece))
                if len(captions)>=90:
                    break
        if not captions:
            return "",0
        blocks=[]
        for n,(a,b,piece) in enumerate(captions[:90],1):
            # SRT text is ordinary recognized speech, not HTML markup.
            safe=re.sub(r"[<>]", "",piece)
            blocks.append(f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{safe}\n")
        target.write_text("\n".join(blocks),encoding="utf-8")
        return " ".join(transcript)[:650],len(blocks)
    except Exception as exc:
        print("subtitle_generation_error:",type(exc).__name__,str(exc)[:160],flush=True)
        return "",0
    finally:
        try:wav.unlink(missing_ok=True)
        except OSError:pass

def make_robot_voice(text: str, target: Path):
    """Generate a robotic Spanish voice from the user's chosen narration text."""
    text=" ".join((text or "").split()).strip()[:180]
    if not text:
        raise ValueError("Introduce un texto para la narración.")
    # CLI arguments, not a shell command; user text cannot execute shell syntax.
    _run(["espeak-ng","-v","es-la","-s","155","-p","47","-a","165",
          "-w",str(target),text],timeout=40)
    if not target.is_file() or target.stat().st_size<1000:
        raise RuntimeError("No se pudo generar la narración robótica.")
    return target

# Filename always contains generated ASCII-only job id; no interpolated user input.
SUBTITLE_STYLE=("FontName=DejaVu Sans,FontSize=22,"
                "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                "BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=130")

def subtitle_filter(srt: Path):
    return "subtitles="+str(srt)+":force_style='"+SUBTITLE_STYLE+"'"
