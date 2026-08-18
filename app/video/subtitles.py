from pathlib import Path
from app.ai.schemas import AudioAnalysis

def write_ass(analysis: AudioAnalysis, path: Path, width=1280, height=720):
    def ts(x):
        h = int(x // 3600); m = int((x % 3600) // 60); s = x % 60
        return f"{h}:{m:02d}:{s:05.2f}"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,DejaVu Sans,42,&H00FFFFFF,&H0000FFFF,&H00101010,&H64000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,50,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = []
    for seg in analysis.segments:
        text = seg.text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        lines.append(f"Dialogue: 0,{ts(seg.start)},{ts(seg.end)},Default,,0,0,0,,{text}")
    path.write_text(header + "\n".join(lines), encoding="utf-8")
