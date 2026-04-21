"""Layer 0: Rule-based news filter — reject irrelevant articles before AI analysis.

Inspired by PokieTicker's Layer 0. Expected: ~20-30% rejection at zero cost.
Runs before DeepSeek calls in both NewsAgent and SentimentEngine.
"""

import re
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# ── Rejection patterns ────────────────────────────────

# Ads / promotional content
AD_PATTERNS = [
    re.compile(r"(推荐|必买|精选|优选|严选|不容错过|限时).{0,4}(基金|理财|保险|产品)", re.IGNORECASE),
    re.compile(r"(开户|佣金|手续费|低至|万\d)", re.IGNORECASE),
    re.compile(r"(客服|咨询|热线|400-|拨打)", re.IGNORECASE),
]

# List / ranking articles (low signal density)
LIST_PATTERNS = [
    re.compile(r"^(今日|本周|本月)?(十大|五大|三大|TOP\s*\d|盘点)", re.IGNORECASE),
    re.compile(r"(排行榜|龙虎榜|涨幅榜|跌幅榜).*汇总"),
    re.compile(r"^\d+只.*一览"),
]

# Non-A-share / irrelevant topics
IRRELEVANT_PATTERNS = [
    re.compile(r"(美股|港股|欧股|纳斯达克|道琼斯|标普|恒生).*(收盘|盘前|盘后|涨跌)", re.IGNORECASE),
    re.compile(r"(足球|篮球|娱乐|明星|综艺|选秀|八卦)", re.IGNORECASE),
    re.compile(r"(天气预报|星座运势|彩票|福彩|体彩)", re.IGNORECASE),
]

# Minimum content length (too short = no useful info)
MIN_TITLE_LEN = 8
MIN_CONTENT_LEN = 20


def filter_article(title: str, content: str = "", source: str = "") -> Tuple[bool, str]:
    """Check if a single article should proceed to AI analysis.

    Returns:
        (passed, reason): passed=True means article is worth analyzing.
    """
    title = (title or "").strip()
    content = (content or "").strip()

    # Rule 1: Title too short
    if len(title) < MIN_TITLE_LEN:
        return False, "title_too_short"

    # Rule 2: Content too short (if provided)
    if content and len(content) < MIN_CONTENT_LEN:
        return False, "content_too_short"

    # Rule 3: Ad / promotional
    for pat in AD_PATTERNS:
        if pat.search(title) or pat.search(content[:200]):
            return False, "ad_promotional"

    # Rule 4: List / ranking articles
    for pat in LIST_PATTERNS:
        if pat.search(title):
            return False, "list_article"

    # Rule 5: Non-A-share / irrelevant
    for pat in IRRELEVANT_PATTERNS:
        if pat.search(title):
            return False, "irrelevant_topic"

    return True, "passed"


def filter_batch(articles: List[Dict[str, Any]], title_key: str = "title", content_key: str = "content") -> Tuple[List[Dict], Dict[str, int]]:
    """Filter a batch of articles. Returns (passed_articles, stats).

    Args:
        articles: List of article dicts
        title_key: Key for title field in article dict
        content_key: Key for content field in article dict

    Returns:
        (passed, stats) where stats has counts per rejection reason.
    """
    passed = []
    stats: Dict[str, int] = {"total": len(articles), "passed": 0}

    for art in articles:
        ok, reason = filter_article(
            art.get(title_key, ""),
            art.get(content_key, ""),
            art.get("source", ""),
        )
        if ok:
            passed.append(art)
            stats["passed"] += 1
        else:
            stats[reason] = stats.get(reason, 0) + 1

    stats["filtered"] = stats["total"] - stats["passed"]
    pct = round(stats["filtered"] / max(stats["total"], 1) * 100, 1)
    logger.info(
        "NewsFilter: %d/%d passed (%.1f%% filtered) — %s",
        stats["passed"], stats["total"], pct,
        {k: v for k, v in stats.items() if k not in ("total", "passed", "filtered")},
    )
    return passed, stats
