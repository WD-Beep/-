"""闂幆鐑熸祴锛氬鍒舵爣浠疯〃鍒颁复鏃舵枃浠讹紝寮哄埗瑁佸喅鍐欎竴琛岋紝楠岃瘉涓嶄慨鏀瑰師 data/price_kb.xlsx銆?""
from __future__ import annotations

import os
import shutil
import sys
import time
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 淇濊瘉涓枃杈撳嚭鍦?Windows 缁堢鍙
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    os.environ.setdefault("KNOWLEDGE_AUTO_LEARN", "1")
    os.environ.setdefault("KNOWLEDGE_AUTO_WRITE", "1")
    import core.smart_lookup as smart_lookup_mod
    import price_kb as price_kb_mod
    from core.smart_lookup import warm_embedding_index, smart_lookup
    from embedding.embedding_index import get_embedding_index
    from kimi_client import get_kimi_config
    from price_kb import get_price_kb, reset_price_kb

    cfg = get_kimi_config()
    print(
        "[smoke] kimi key 宸查厤缃?"
        f"{bool(cfg.api_key)} source={cfg.api_key_source}",
        flush=True,
    )

    real_kb = price_kb_mod.DEFAULT_KB_PATH.resolve()
    if not real_kb.is_file():
        print(f"[smoke] 缂哄皯鏍囦环琛? {real_kb}", flush=True)
        return 2

    tmp_kb = Path(os.environ.get("TEMP", str(ROOT / "data"))) / "_price_kb_smoke_copy.xlsx"
    shutil.copy2(real_kb, tmp_kb)
    print(f"[smoke] 涓存椂 KB锛堝師琛ㄥ壇鏈級: {tmp_kb}", flush=True)

    price_kb_mod.DEFAULT_KB_PATH = tmp_kb
    smart_lookup_mod.DEFAULT_KB_PATH = tmp_kb

    def _forced_judge(_q: str, _spec: str, _cands: list) -> dict:
        return {
            "action": "write_to_kb",
            "confidence": 1.0,
            "material": {
                "name": "_闂幆鐑熸祴琛宊鍙垹_",
                "spec": "-",
                "price": "0.01鍏?PCS",
            },
        }

    reset_price_kb()
    warm_embedding_index(tmp_kb)
    idx = get_embedding_index()
    print(f"[smoke] embedding_ready={idx.is_ready()}", flush=True)

    kb = get_price_kb()
    before = kb.size

    # 鐢ㄦ瀬楂?min_score 閬垮厤闅忔満涓蹭笌澶ф暟鎹〃寮卞尮閰嶄粛绠椼€屽懡涓€?
    miss_score = 0.99
    q = "__SMOKE_UUID_8c1e4b2a9f0d__"
    hit0 = kb.lookup(q, "-", min_score=miss_score)
    print(
        f"[smoke] lookup_miss={hit0 is None} query={q!r} min_score={miss_score} rows={before}",
        flush=True,
    )

    # 鍚庡彴绾跨▼閲?`from core.knowledge_judge import judge_write_decision`锛屾晠 patch 鐩爣妯″潡
    with unittest.mock.patch(
        "core.knowledge_judge.judge_write_decision",
        _forced_judge,
    ):
        r = smart_lookup(q, "-", min_score=miss_score, top_k=5)
        print(f"[smoke] smart_lookup={r}", flush=True)
        print("[smoke] 绛夊緟鍚庡彴鍐欑洏涓?reload锛?0s锛宲atch 淇濇寔鏈夋晥锛夆€?, flush=True)
        time.sleep(30)

    reset_price_kb()
    kb2 = get_price_kb()
    after = kb2.size
    print(f"[smoke] 琛屾暟 before={before} after={after} delta={after - before}", flush=True)

    price_kb_mod.DEFAULT_KB_PATH = real_kb
    smart_lookup_mod.DEFAULT_KB_PATH = real_kb
    reset_price_kb()

    try:
        tmp_kb.unlink(missing_ok=True)
        print("[smoke] 宸插垹闄や复鏃?KB 鍓湰", flush=True)
    except OSError as e:
        print(f"[smoke] 鍒犻櫎涓存椂鏂囦欢澶辫触: {e}", flush=True)

    if after != before + 1:
        print(
            "[smoke] 鏈瀵熷埌 +1 琛岋細鍙兘 judge 鏈?patch 鐢熸晥銆佸啓鐩樺け璐ユ垨绾跨▼鏈窇瀹岋紱"
            "鍙€傚綋寤堕暱 sleep 鎴栫湅鏈嶅姟绔槸鍚︽湁澶氳繘绋嬪崰鐢ㄩ攣銆?,
            flush=True,
        )
        return 1
    print("[smoke] 闂幆鍐欑洏锛堜复鏃跺壇鏈級鎴愬姛銆?, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

