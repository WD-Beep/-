from pathlib import Path

samples = [
    "闀?, \"瀹?, \"楂?",
    "灏忎欢鍖呰",
    "澶栫焊绠?鍖呰璐癸紙绯荤粺浼扮畻锛?",
    "210D闃叉挄瑁傚凹榫欏寘",
    "包装",
]

encodings = ["latin1", "gbk", "cp1252", "utf-8", "gb18030"]

for s in samples:
    print("===", s[:40])
    for enc in encodings:
        try:
            fixed = s.encode(enc).decode("utf-8")
            if fixed != s:
                print(f"  {enc} -> utf-8:", fixed[:60])
        except Exception as e:
            pass
    for enc in encodings:
        try:
            fixed = s.encode("utf-8").decode(enc)
            if fixed != s:
                print(f"  utf-8 -> {enc}:", fixed[:60])
        except Exception:
            pass

# try whole-file roundtrip on a chunk
p = Path(__file__).resolve().parents[1] / "quote_engine.py"
raw = p.read_text(encoding="utf-8-sig")
for enc in ["gbk", "latin1", "cp1252"]:
    try:
        fixed = raw.encode("utf-8").decode(enc)
        compile(fixed, "x", "exec")
        print("WHOLE FILE compile ok with utf-8 ->", enc)
    except Exception as e:
        print("utf-8 ->", enc, type(e).__name__, str(e)[:80])

for enc in ["latin1", "cp1252"]:
    try:
        fixed = raw.encode(enc).decode("utf-8")
        compile(fixed, "x", "exec")
        print("WHOLE FILE compile ok with", enc, "-> utf-8")
    except Exception as e:
        print(enc, "-> utf-8", type(e).__name__, str(e)[:80])
