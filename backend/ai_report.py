"""AI destekli (veya anahtarsız çalışan) olay raporu üretimi.

ANTHROPIC_API_KEY ortam değişkeni tanımlıysa Claude API'siyle Türkçe bir SOC
analist özeti üretilir. Tanımlı değilse aynı bilgi belirlenimci (deterministic)
bir şablonla üretilir — böylece rapor uç noktası API anahtarı olmadan da ders
demosu için çalışır durumda kalır ve ne zaman gerçek bir LLM'in konuştuğu
`generated_by` alanıyla her zaman açıkça belli olur.
"""
from __future__ import annotations

import collections
import os
from typing import List, Optional, Tuple

MODEL = "claude-sonnet-5-5"

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _template_report(events: List[dict]) -> str:
    if not events:
        return "İncelenecek olay yok — sistem sakin görünüyor."

    by_rule = collections.Counter(e["rule"] for e in events)
    by_sev = collections.Counter(e["severity"] for e in events)
    worst = sorted(events, key=lambda e: SEVERITY_ORDER.get(e["severity"], 9))[:5]

    lines = [f"SOC Özet Raporu — {len(events)} olay incelendi.", "",
             "Önem derecesine göre dağılım:"]
    for sev in ("critical", "high", "medium", "low"):
        if by_sev.get(sev):
            lines.append(f"  - {sev}: {by_sev[sev]}")

    lines += ["", "Kural bazında dağılım:"]
    for rule, count in by_rule.most_common():
        lines.append(f"  - {rule}: {count}")

    lines += ["", "En kritik 5 olay:"]
    for e in worst:
        lines.append(f"  - [{e['severity']}] {e['rule']}: {e['message']}")

    lines += ["", "(Bu rapor ANTHROPIC_API_KEY tanımlı olmadığı için şablon "
                   "tabanlı üretildi; gerçek bir dil modeli yorumu içermez.)"]
    return "\n".join(lines)


def _llm_report(events: List[dict]) -> Optional[str]:
    import anthropic

    client = anthropic.Anthropic()
    summary_input = "\n".join(
        f"- [{e['severity']}] {e['rule']}: {e['message']}" for e in events[-60:]
    )
    prompt = (
        "Aşağıda bir İHA (drone) MAVLink haberleşmesini izleyen bir SOC tespit "
        "motorunun ürettiği güvenlik olayları listesi var. Bir siber güvenlik "
        "analisti için kısa, net, Türkçe bir olay özeti raporu yaz: "
        "(1) genel durum, (2) en önemli bulgular, (3) önerilen aksiyonlar. "
        "Uydurma bilgi ekleme, sadece verilen olaylara dayan.\n\n"
        f"Olaylar:\n{summary_input}"
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=800, messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text for block in resp.content if getattr(block, "type", None) == "text"
    )


def generate_report(events: List[dict]) -> Tuple[str, str]:
    """Döner: (rapor_metni, "anthropic" | "template" | "template_fallback")."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            text = _llm_report(events)
            if text:
                return text, "anthropic"
        except Exception as e:
            fallback = _template_report(events)
            return f"(AI rapor üretimi başarısız oldu: {e})\n\n{fallback}", "template_fallback"
    return _template_report(events), "template"
