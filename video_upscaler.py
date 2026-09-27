#!/usr/bin/env python3
"""Video Upscaler CLI - safe FFmpeg video upscale/downscale and FPS conversion."""
from __future__ import annotations
import json, logging, os, re, shutil, signal, subprocess, sys, time
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

APP_NAME, VERSION = "Video Upscaler CLI", "1.0.0"
ROOT = Path(__file__).resolve().parent
INPUT_DIR, OUTPUT_DIR, LOG_DIR = ROOT/"Video", ROOT/"Output", ROOT/"logs"
CONFIG_FILE = ROOT/"config.json"
VIDEO_EXTENSIONS = {".mp4",".mkv",".mov",".avi",".webm",".m4v",".mts",".m2ts",".ts",".flv",".wmv",".mpg",".mpeg",".3gp"}
RESOLUTIONS = {"1":(854,480,"480p"),"2":(1280,720,"720p"),"3":(1920,1080,"1080p"),"4":(2560,1440,"1440p"),"5":(3840,2160,"2160p"),"6":(7680,4320,"4320p")}
FPS_OPTIONS = {"2":"23.976","3":"24","4":"25","5":"29.97","6":"30","7":"48","8":"50","9":"59.94","10":"60","11":"90","12":"120","13":"144","14":"180","15":"240"}
DEFAULT_CONFIG = {"output_container":"mp4","auto_profile":"balanced","preserve_metadata":True,"preserve_subtitles":True,"preserve_chapters":True,"overwrite":False,"scaler":"lanczos","audio_mode":"copy","validate_output":True,"keep_failed_temp":False,"minimum_free_space_gb":1.0}

@dataclass
class VideoInfo:
    path: Path
    width: int
    height: int
    fps: float
    duration: float
    codec: str
    pix_fmt: str
    color_transfer: str
    audio_streams: int
    subtitle_streams: int

@dataclass
class JobSettings:
    width: int|None
    height: int|None
    label: str
    fps: float|None
    profile: str
    codec: str
    quality: str
    scaler: str
    container: str
    interpolation: str="none"

CURRENT_PROCESS: subprocess.Popen|None = None

def setup_dirs():
    for d in (INPUT_DIR,OUTPUT_DIR,LOG_DIR): d.mkdir(parents=True,exist_ok=True)
    if not CONFIG_FILE.exists(): CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG,indent=2),encoding="utf-8")

def load_config():
    cfg=DEFAULT_CONFIG.copy()
    try: cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception: pass
    return cfg

def setup_logging():
    f=LOG_DIR/f"video_upscaler_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(filename=f,level=logging.INFO,format="%(asctime)s | %(levelname)s | %(message)s",encoding="utf-8")
    return f

def run_capture(cmd):
    return subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace",creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)

def dependency_check():
    ffmpeg,ffprobe=shutil.which("ffmpeg"),shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        print("\nERROR: FFmpeg/FFprobe tidak ditemukan di PATH.")
        print("Install FFmpeg lalu pastikan 'ffmpeg' dan 'ffprobe' dapat dijalankan.")
        sys.exit(1)
    return ffmpeg,ffprobe

def available_encoders(ffmpeg):
    p=run_capture([ffmpeg,"-hide_banner","-encoders"])
    return set(re.findall(r"^\s*V.....\s+([\w-]+)",p.stdout,re.MULTILINE))

def detect_encoder(encoders,codec="auto"):
    candidates={
      "h264":[("h264_nvenc","NVIDIA NVENC"),("h264_qsv","Intel QSV"),("h264_amf","AMD AMF"),("h264_videotoolbox","VideoToolbox"),("libx264","CPU libx264")],
      "hevc":[("hevc_nvenc","NVIDIA NVENC"),("hevc_qsv","Intel QSV"),("hevc_amf","AMD AMF"),("hevc_videotoolbox","VideoToolbox"),("libx265","CPU libx265")],
      "av1":[("av1_nvenc","NVIDIA NVENC"),("av1_qsv","Intel QSV"),("av1_amf","AMD AMF"),("libsvtav1","CPU SVT-AV1"),("libaom-av1","CPU AOM")]
    }
    order=[codec] if codec in candidates else ["hevc","h264","av1"]
    for family in order:
        for enc,label in candidates[family]:
            if enc in encoders: return enc,label
    raise RuntimeError("Tidak ada encoder video kompatibel pada FFmpeg.")

def parse_rate(value):
    if not value or value=="0/0": return 0.0
    try: return float(Fraction(value))
    except Exception: return 0.0

def probe_video(ffprobe,path):
    p=run_capture([ffprobe,"-v","error","-show_streams","-show_format","-of","json",str(path)])
    if p.returncode!=0: raise RuntimeError(p.stderr.strip() or "FFprobe gagal membaca file")
    data=json.loads(p.stdout); streams=data.get("streams",[])
    vs=next((s for s in streams if s.get("codec_type")=="video"),None)
    if not vs: raise RuntimeError("Video stream tidak ditemukan")
    duration=float(vs.get("duration") or data.get("format",{}).get("duration") or 0)
    return VideoInfo(path,int(vs.get("width",0)),int(vs.get("height",0)),parse_rate(vs.get("avg_frame_rate") or vs.get("r_frame_rate")),duration,vs.get("codec_name","unknown"),vs.get("pix_fmt","unknown"),vs.get("color_transfer","unknown"),sum(s.get("codec_type")=="audio" for s in streams),sum(s.get("codec_type")=="subtitle" for s in streams))

def scan_videos(ffprobe):
    infos,bad=[],[]
    for p in sorted(INPUT_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            try: infos.append(probe_video(ffprobe,p))
            except Exception as e: bad.append((p,str(e)))
    return infos,bad

def choose(prompt,valid):
    while True:
        v=input(prompt).strip().lower()
        if v in valid: return v
        print("Pilihan tidak valid.")

def choose_resolution():
    print("\nTARGET RESOLUTION\n"+"="*54)
    print("[1] 480p          854x480\n[2] 720p HD       1280x720\n[3] 1080p FHD     1920x1080\n[4] 1440p / 2K    2560x1440\n[5] 2160p / 4K    3840x2160\n[6] 4320p / 8K    7680x4320\n[7] Original / Preserve\n[8] Custom")
    c=choose("Pilih: ",set("12345678"))
    if c in RESOLUTIONS: return RESOLUTIONS[c]
    if c=="7": return None,None,"original"
    while True:
        try:
            w,h=int(input("Width : ")),int(input("Height: "))
            if w>=16 and h>=16: return w-w%2,h-h%2,f"{w}x{h}"
        except ValueError: pass
        print("Resolusi tidak valid.")

def choose_fps():
    print("\nTARGET FPS\n"+"="*54)
    print("[1] Original / Preserve (Recommended)\n[2] 23.976\n[3] 24\n[4] 25\n[5] 29.97\n[6] 30\n[7] 48\n[8] 50\n[9] 59.94\n[10] 60\n[11] 90\n[12] 120\n[13] 144\n[14] 180\n[15] 240\n[16] Custom")
    c=choose("Pilih: ",{str(i) for i in range(1,17)})
    if c=="1": return None
    if c in FPS_OPTIONS: return float(FPS_OPTIONS[c])
    while True:
        try:
            f=float(input("FPS custom: "))
            if 1<=f<=1000: return f
        except ValueError: pass
        print("FPS tidak valid.")

def choose_profile():
    print("\nAUTO PROFILE\n"+"="*54)
    print("[1] Balanced (Recommended) - kualitas/ukuran/kecepatan seimbang\n[2] Best Quality            - prioritas kualitas\n[3] Fast                    - prioritas kecepatan\n[4] Small File              - prioritas ukuran file\n[5] Preserve Quality        - perubahan minimum")
    return {"1":"balanced","2":"best","3":"fast","4":"small","5":"preserve"}[choose("Pilih: ",set("12345"))]

def choose_codec():
    print("\nVIDEO CODEC\n"+"="*54)
    print("[1] Auto / Recommended\n[2] H.264 (compatibility)\n[3] H.265 / HEVC (efficient)\n[4] AV1 (modern, slower)")
    return {"1":"auto","2":"h264","3":"hevc","4":"av1"}[choose("Pilih: ",set("1234"))]

def choose_quality():
    print("\nQUALITY\n"+"="*54)
    print("[1] Auto / Recommended\n[2] Maximum\n[3] High\n[4] Balanced\n[5] Small File")
    return {"1":"auto","2":"maximum","3":"high","4":"balanced","5":"small"}[choose("Pilih: ",set("12345"))]

def scale_filter(info,s):
    if not s.width or not s.height: return None
    return f"scale={s.width}:{s.height}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags={s.scaler}"

def encoder_args(encoder,profile,quality):
    q=quality if quality!="auto" else profile
    if encoder in {"libx264","libx265"}:
        crf={"maximum":"16","best":"17","high":"19","balanced":"22","preserve":"18","small":"27","fast":"23"}.get(q,"22")
        preset="slow" if q in {"maximum","best"} else "medium" if q in {"high","balanced","preserve"} else "fast"
        return ["-preset",preset,"-crf",crf]
    if "nvenc" in encoder:
        cq={"maximum":"16","best":"17","high":"19","balanced":"22","preserve":"18","small":"28","fast":"24"}.get(q,"22")
        preset="p7" if q in {"maximum","best"} else "p5" if q in {"high","balanced","preserve"} else "p3"
        return ["-preset",preset,"-rc","vbr","-cq",cq,"-b:v","0"]
    if "qsv" in encoder:
        qv={"maximum":"16","best":"17","high":"19","balanced":"22","preserve":"18","small":"28","fast":"24"}.get(q,"22")
        return ["-global_quality",qv]
    if "amf" in encoder: return ["-quality","quality" if q in {"maximum","best","high","preserve"} else "balanced" if q=="balanced" else "speed"]
    if "videotoolbox" in encoder: return ["-q:v","65"]
    if encoder in {"libsvtav1","libaom-av1"}:
        crf={"maximum":"20","best":"22","high":"26","balanced":"30","preserve":"24","small":"36","fast":"32"}.get(q,"30")
        return ["-crf",crf,"-b:v","0"]
    return []

def make_output_path(info,s):
    res=s.label if s.label!="original" else f"{info.height}p"
    fps=f"_{s.fps:g}fps" if s.fps else ""
    base=re.sub(r"[^\w .()-]+","_",info.path.stem,flags=re.UNICODE).strip(" .") or "video"
    candidate=OUTPUT_DIR/f"{base}_{res}{fps}.{s.container}"
    if not candidate.exists(): return candidate
    for i in range(2,10000):
        c=OUTPUT_DIR/f"{base}_{res}{fps}_{i}.{s.container}"
        if not c.exists(): return c
    raise RuntimeError("Terlalu banyak output dengan nama sama")

def disk_space_ok(info,cfg):
    free=shutil.disk_usage(OUTPUT_DIR).free
    source=max(info.path.stat().st_size,1)
    reserve=int(float(cfg.get("minimum_free_space_gb",1.0))*1024**3)
    return free>source*2+reserve

def build_command(ffmpeg,info,s,encoder,temp,cfg):
    cmd=[ffmpeg,"-hide_banner","-y","-i",str(info.path),"-map","0:v:0","-map","0:a?","-map","0:s?"]
    filters=[]; sf=scale_filter(info,s)
    if sf: filters.append(sf)
    if s.fps and abs(s.fps-info.fps)>0.01:
        if s.interpolation=="interpolate": filters.append(f"minterpolate=fps={s.fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1")
        else: filters.append(f"fps={s.fps}")
    if filters: cmd+=["-vf",",".join(filters)]
    cmd+=["-c:v",encoder]+encoder_args(encoder,s.profile,s.quality)
    cmd += ["-c:a","copy"] if cfg.get("audio_mode")=="copy" else ["-c:a","aac","-b:a","192k"]
    if s.container=="mp4" and info.subtitle_streams: cmd+=["-c:s","mov_text"]
    else: cmd+=["-c:s","copy"]
    if cfg.get("preserve_metadata",True): cmd+=["-map_metadata","0"]
    if cfg.get("preserve_chapters",True): cmd+=["-map_chapters","0"]
    if s.container=="mp4": cmd+=["-movflags","+faststart"]
    return cmd+["-progress","pipe:1","-nostats",str(temp)]

def format_time(sec):
    sec=max(0,int(sec)); return f"{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d}"

def run_ffmpeg(cmd,duration):
    global CURRENT_PROCESS
    logging.info("COMMAND: %s",subprocess.list2cmdline(cmd))
    CURRENT_PROCESS=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",bufsize=1,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    start=time.time(); last_print=0.0
    for line in CURRENT_PROCESS.stdout:
        if line.startswith("out_time_ms="):
            try:
                out=int(line.split("=",1)[1])/1_000_000
                pct=min(100.0,out/duration*100) if duration else 0
                elapsed=time.time()-start; eta=(elapsed/pct*(100-pct)) if pct>.1 else 0
                if time.time()-last_print>.3:
                    print(f"\rProgress: {pct:6.2f}% | Elapsed {format_time(elapsed)} | ETA {format_time(eta)}",end="",flush=True); last_print=time.time()
            except ValueError: pass
    stderr=CURRENT_PROCESS.stderr.read() if CURRENT_PROCESS.stderr else ""
    code=CURRENT_PROCESS.wait(); CURRENT_PROCESS=None; print()
    if code!=0: logging.error("FFmpeg failed: %s",stderr[-8000:])
    return code==0,stderr

def validate_output(ffprobe,output,expected):
    if not output.exists() or output.stat().st_size<=0: return False,"Output kosong/tidak ditemukan"
    try:
        v=probe_video(ffprobe,output)
        if v.width<=0 or v.height<=0 or v.duration<=0: return False,"Video stream/durasi output tidak valid"
        if expected.fps and abs(v.fps-expected.fps)>max(.5,expected.fps*.02): return False,f"FPS output tidak sesuai ({v.fps:.3f})"
        return True,f"{v.width}x{v.height} @ {v.fps:.3f} FPS"
    except Exception as e: return False,str(e)

def process_one(ffmpeg,ffprobe,encoders,info,s,cfg,index,total):
    print(f"\n[{index}/{total}] {info.path.name}")
    print(f"Source : {info.width}x{info.height} | {info.fps:.3f} FPS | {info.codec} | {format_time(info.duration)}")
    if not disk_space_ok(info,cfg):
        print("SKIP: Ruang disk tidak mencukupi untuk batas aman."); logging.error("Insufficient disk: %s",info.path); return False
    output=make_output_path(info,s); temp=output.with_name(output.stem+".processing"+output.suffix); temp.unlink(missing_ok=True)
    encoder,encoder_label=detect_encoder(encoders,s.codec)
    print(f"Target : {s.label} | {'Original' if s.fps is None else f'{s.fps:g} FPS'} | {encoder_label}")
    ok,err=run_ffmpeg(build_command(ffmpeg,info,s,encoder,temp,cfg),info.duration)
    if not ok and encoder not in {"libx264","libx265","libsvtav1","libaom-av1"}:
        family="hevc" if "hevc" in encoder else "av1" if "av1" in encoder else "h264"
        cpu=next((x for x in {"h264":["libx264"],"hevc":["libx265"],"av1":["libsvtav1","libaom-av1"]}[family] if x in encoders),None)
        if cpu:
            print(f"Hardware encoder gagal. Fallback aman ke {cpu}...")
            temp.unlink(missing_ok=True); ok,err=run_ffmpeg(build_command(ffmpeg,info,s,cpu,temp,cfg),info.duration)
    if not ok:
        print("FAILED: FFmpeg gagal. Video sumber tetap tidak berubah.")
        if not cfg.get("keep_failed_temp",False): temp.unlink(missing_ok=True)
        return False
    valid,detail=validate_output(ffprobe,temp,s) if cfg.get("validate_output",True) else (True,"validation disabled")
    if not valid:
        print(f"FAILED VALIDATION: {detail}"); logging.error("Validation failed %s: %s",info.path,detail)
        if not cfg.get("keep_failed_temp",False): temp.unlink(missing_ok=True)
        return False
    temp.replace(output)
    print(f"SUCCESS: {output.name}\nVerified: {detail}"); logging.info("SUCCESS %s -> %s",info.path,output)
    return True

def show_summary(videos,s):
    print("\nPROCESS SUMMARY\n"+"="*54)
    print(f"Files          : {len(videos)}\nResolution     : {s.label}\nFPS            : {'Original / Preserve' if s.fps is None else s.fps}\nProfile        : {s.profile}\nCodec          : {s.codec}\nQuality        : {s.quality}\nScaler         : {s.scaler}\nOutput         : {OUTPUT_DIR}\nSource safety  : READ-ONLY / NEVER OVERWRITTEN\nValidation     : Temporary output -> FFprobe -> Finalize")
    return choose("\nMulai proses? [Y/N]: ",{"y","n"})=="y"

def settings_for_mode(mode,cfg):
    w,h,label=choose_resolution() if mode in {"1","3","4"} else (None,None,"original")
    fps=choose_fps() if mode in {"2","3","4"} else None
    if mode=="1": profile,codec,quality=choose_profile(),"auto","auto"
    elif mode in {"2","3"}: profile,codec,quality="balanced","auto","auto"
    else: profile,codec,quality=choose_profile(),choose_codec(),choose_quality()
    interpolation="none"
    if fps:
        print("\nFPS METHOD\n"+"="*54+"\n[1] Standard FFmpeg\n[2] Motion Interpolation (lebih halus, jauh lebih berat)")
        interpolation="interpolate" if choose("Pilih: ",{"1","2"})=="2" else "standard"
    return JobSettings(w,h,label,fps,profile,codec,quality,cfg.get("scaler","lanczos"),cfg.get("output_container","mp4"),interpolation)

def handle_signal(sig,frame):
    global CURRENT_PROCESS
    print("\n\nMembatalkan dengan aman...")
    if CURRENT_PROCESS and CURRENT_PROCESS.poll() is None:
        try: CURRENT_PROCESS.terminate(); CURRENT_PROCESS.wait(timeout=5)
        except Exception:
            try: CURRENT_PROCESS.kill()
            except Exception: pass
    sys.exit(130)

def main():
    setup_dirs(); cfg=load_config(); log_file=setup_logging(); signal.signal(signal.SIGINT,handle_signal)
    ffmpeg,ffprobe=dependency_check(); encoders=available_encoders(ffmpeg); videos,bad=scan_videos(ffprobe)
    print(f"\n{APP_NAME} v{VERSION}\n"+"="*54)
    print(f"FFmpeg          : Ready\nFFprobe         : Ready\nVideos Found    : {len(videos)}\nInvalid Videos  : {len(bad)}\nHardware/Encoder: Auto Detect\nSource Safety   : ON")
    for p,e in bad: logging.warning("Unreadable %s: %s",p,e)
    if not videos:
        print(f"\nTidak ada video valid di: {INPUT_DIR}\nMasukkan video ke folder Video lalu jalankan kembali."); return 0
    print("\nMODE\n"+"="*54)
    print("[1] Auto / Recommended    Target resolusi + profil otomatis\n[2] Change FPS             Resolusi dipertahankan\n[3] Resolution + FPS       Ubah keduanya\n[4] Advanced               Target + codec + quality\n[5] Exit")
    mode=choose("Pilih: ",set("12345"))
    if mode=="5": return 0
    settings=settings_for_mode(mode,cfg)
    if not show_summary(videos,settings): print("Dibatalkan."); return 0
    success=0
    for i,info in enumerate(videos,1):
        try: success+=process_one(ffmpeg,ffprobe,encoders,info,settings,cfg,i,len(videos))
        except Exception as e: logging.exception("Unhandled error for %s",info.path); print(f"FAILED: {e}")
    print("\nFINAL RESULT\n"+"="*54)
    print(f"Success          : {success}\nFailed           : {len(videos)-success}\nOriginal modified: 0\nOriginal deleted : 0\nLog              : {log_file}")
    return 0 if success==len(videos) else 2

if __name__=="__main__":
    raise SystemExit(main())
