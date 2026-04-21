"""TDX market data API — real-time quotes, K-lines, finance, company info.

Exposes pytdx capabilities as REST endpoints for external consumers.
All endpoints use TDX TCP protocol (no TuShare dependency).
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tdx", tags=["tdx"])

_collector = None


def _get_collector():
    global _collector
    if _collector is None:
        from api.services.tdx_collector import TdxCollector
        _collector = TdxCollector()
    return _collector


# ── 1. Real-time Quotes (实时行情) ─────────────────────

@router.get("/quotes")
def get_quotes(
    codes: str = Query(..., description="逗号分隔股票代码, e.g. 300027,600519,000001"),
):
    """批量获取实时行情 (盘中实时, 盘后为收盘价)."""
    from pytdx.hq import TdxHq_API

    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list or len(code_list) > 50:
        raise HTTPException(400, "代码数量需在 1-50 之间")

    collector = _get_collector()
    market_codes = []
    for code in code_list:
        market = collector._code_to_market(code)
        market_codes.append((market, code))

    try:
        with collector._connect() as client:
            df = client.to_df(client.get_security_quotes(market_codes))
    except Exception as e:
        raise HTTPException(502, f"TDX 连接失败: {e}")

    if df is None or len(df) == 0:
        return []

    result = []
    for _, row in df.iterrows():
        result.append({
            "code": str(row.get("code", "")),
            "name": str(row.get("servertime", "")),
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "price": float(row.get("price", 0)),
            "last_close": float(row.get("last_close", 0)),
            "volume": int(row.get("vol", 0)),
            "amount": float(row.get("amount", 0)),
            "bid1": float(row.get("bid1", 0)),
            "bid1_vol": int(row.get("bid_vol1", 0)),
            "bid2": float(row.get("bid2", 0)),
            "bid2_vol": int(row.get("bid_vol2", 0)),
            "bid3": float(row.get("bid3", 0)),
            "bid3_vol": int(row.get("bid_vol3", 0)),
            "bid4": float(row.get("bid4", 0)),
            "bid4_vol": int(row.get("bid_vol4", 0)),
            "bid5": float(row.get("bid5", 0)),
            "bid5_vol": int(row.get("bid_vol5", 0)),
            "ask1": float(row.get("ask1", 0)),
            "ask1_vol": int(row.get("ask_vol1", 0)),
            "ask2": float(row.get("ask2", 0)),
            "ask2_vol": int(row.get("ask_vol2", 0)),
            "ask3": float(row.get("ask3", 0)),
            "ask3_vol": int(row.get("ask_vol3", 0)),
            "ask4": float(row.get("ask4", 0)),
            "ask4_vol": int(row.get("ask_vol4", 0)),
            "ask5": float(row.get("ask5", 0)),
            "ask5_vol": int(row.get("ask_vol5", 0)),
        })
    return result


# ── 2. K-lines (K线数据) ──────────────────────────────

@router.get("/klines")
def get_klines(
    code: str = Query(..., description="股票代码 e.g. 300027"),
    start: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD"),
    freq: str = Query("d", description="频率: 1m/5m/15m/30m/60m/d/w/m"),
    adjust: str = Query("qfq", description="复权: qfq(前复权)/none(不复权)"),
):
    """获取个股K线数据 (支持多频率, 默认前复权)."""
    collector = _get_collector()

    if freq == "d" and adjust == "qfq":
        df = collector.fetch_daily(code, start, end)
    else:
        # Non-daily or non-adjusted: use raw bars
        from api.services.tdx_collector import _FREQ_MAP
        freq_code = _FREQ_MAP.get(freq)
        if freq_code is None:
            raise HTTPException(400, f"不支持的频率: {freq}. 可选: {list(_FREQ_MAP.keys())}")

        market = collector._code_to_market(code)
        import datetime as dt, math
        try:
            d_start = dt.date.fromisoformat(start)
            d_end = dt.date.fromisoformat(end)
            days = (d_end - d_start).days
            if freq in ("1m", "5m", "15m", "30m", "60m"):
                pages = min(math.ceil(days * 4), 20)
            else:
                pages = max(2, math.ceil(days / 500))
                pages = min(pages, 12)
        except Exception:
            pages = 4

        try:
            with collector._connect() as client:
                frames = []
                for i in range(1, pages + 1):
                    data = client.to_df(
                        client.get_security_bars(freq_code, market, code, (i - 1) * 700, 700)
                    )
                    if data is None or len(data) == 0:
                        break
                    frames.append(data)

            if not frames:
                return []

            import pandas as pd
            ks = pd.concat(frames, sort=False)
            ks["date"] = pd.to_datetime(ks["datetime"]).dt.strftime(
                "%Y-%m-%d %H:%M" if freq != "d" else "%Y-%m-%d"
            )
            ks = ks.drop_duplicates(["date"], keep="last").sort_values("date")
            mask = ks["date"] >= start
            ks = ks[mask]
            df = ks.rename(columns={"vol": "volume"})[["date", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            raise HTTPException(502, f"TDX 获取K线失败: {e}")

    if df is None or len(df) == 0:
        return []

    return df.to_dict(orient="records")


# ── 3. Index K-lines (指数K线) ────────────────────────

@router.get("/index/klines")
def get_index_klines(
    code: str = Query("000001.SH", description="指数代码: 000001.SH/399001.SZ/399006.SZ/000300.SH"),
    start: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD"),
):
    """获取指数日线数据."""
    collector = _get_collector()
    df = collector.fetch_index_daily(code, start, end)

    if df is None or len(df) == 0:
        return []
    return df.to_dict(orient="records")


# ── 4. Minute Time Data (分时数据) ────────────────────

@router.get("/minute")
def get_minute_data(
    code: str = Query(..., description="股票代码 e.g. 300027"),
    date: str = Query("", description="日期 YYYYMMDD (空=当天)"),
):
    """获取分时数据 (逐分钟价格+成交量)."""
    collector = _get_collector()
    market = collector._code_to_market(code)

    try:
        with collector._connect() as client:
            if date:
                df = client.to_df(
                    client.get_history_minute_time_data(market, code, int(date))
                )
            else:
                df = client.to_df(client.get_minute_time_data(market, code))
    except Exception as e:
        raise HTTPException(502, f"TDX 获取分时失败: {e}")

    if df is None or len(df) == 0:
        return []
    return df.to_dict(orient="records")


# ── 5. Transaction Data (成交明细) ────────────────────

@router.get("/transactions")
def get_transactions(
    code: str = Query(..., description="股票代码 e.g. 300027"),
    date: str = Query("", description="日期 YYYYMMDD (空=当天)"),
    offset: int = Query(0, description="起始位置"),
    limit: int = Query(100, ge=1, le=2000, description="条数 (最大2000)"),
):
    """获取逐笔成交明细. buyorsell: 0=买, 1=卖, 2=集合竞价."""
    collector = _get_collector()
    market = collector._code_to_market(code)

    try:
        with collector._connect() as client:
            if date:
                df = client.to_df(
                    client.get_history_transaction_data(market, code, offset, limit, int(date))
                )
            else:
                df = client.to_df(
                    client.get_transaction_data(market, code, offset, limit)
                )
    except Exception as e:
        raise HTTPException(502, f"TDX 获取成交明细失败: {e}")

    if df is None or len(df) == 0:
        return []
    return df.to_dict(orient="records")


# ── 6. Finance Info (财务简要) ────────────────────────

@router.get("/finance")
def get_finance_info(
    code: str = Query(..., description="股票代码 e.g. 300027"),
):
    """获取股票财务简要信息 (总资产/净资产/营收/净利润/每股净资产等)."""
    collector = _get_collector()
    market = collector._code_to_market(code)

    try:
        with collector._connect() as client:
            df = client.to_df(client.get_finance_info(market, code))
    except Exception as e:
        raise HTTPException(502, f"TDX 获取财务信息失败: {e}")

    if df is None or len(df) == 0:
        return {}

    row = df.iloc[0]
    return {
        "code": code,
        "总股本": float(row.get("zongguben", 0)),
        "流通股本": float(row.get("liutongguben", 0)),
        "总资产": float(row.get("zongzichan", 0)),
        "流动资产": float(row.get("liudongzichan", 0)),
        "固定资产": float(row.get("gudingzichan", 0)),
        "净资产": float(row.get("jingzichan", 0)),
        "流动负债": float(row.get("liudongfuzhai", 0)),
        "长期负债": float(row.get("changqifuzhai", 0)),
        "主营收入": float(row.get("zhuyingshouru", 0)),
        "主营利润": float(row.get("zhuyinglirun", 0)),
        "营业利润": float(row.get("yingyelirun", 0)),
        "利润总额": float(row.get("lirunzonghe", 0)),
        "净利润": float(row.get("jinglirun", 0)),
        "未分配利润": float(row.get("weifenpeilirun", 0)),
        "每股净资产": float(row.get("meigujingzichan", 0)),
        "股东人数": int(row.get("gudongrenshu", 0)),
        "投资收益": float(row.get("touzishouyu", 0)),
        "经营现金流": float(row.get("jingyingxianjinliu", 0)),
        "总现金流": float(row.get("zongxianjinliu", 0)),
        "存货": float(row.get("cunhuo", 0)),
        "应收账款": float(row.get("yingshouzhangkuan", 0)),
        "资本公积金": float(row.get("zibengongjijin", 0)),
        "更新日期": str(int(row.get("updated_date", 0))),
    }


# ── 7. Company Info (公司资料) ────────────────────────

@router.get("/company")
def get_company_info(
    code: str = Query(..., description="股票代码 e.g. 300027"),
    category: str = Query(
        "公司概况",
        description="分类: 最新提示/公司概况/财务分析/股东研究/股本结构/资本运作/业内点评/行业分析/公司大事/龙虎榜单",
    ),
):
    """获取公司资料详情 (文本)."""
    collector = _get_collector()
    market = collector._code_to_market(code)

    try:
        with collector._connect() as client:
            cats = client.get_company_info_category(market, code)
            if not cats:
                raise HTTPException(404, f"无公司资料: {code}")

            target = None
            for c in cats:
                if c.get("name") == category:
                    target = c
                    break

            if not target:
                available = [c["name"] for c in cats]
                raise HTTPException(404, f"分类 '{category}' 不存在. 可选: {available}")

            content = client.get_company_info_content(
                market, code, target["filename"], target["start"], target["length"]
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"TDX 获取公司资料失败: {e}")

    return {
        "code": code,
        "category": category,
        "content": content.decode("gbk", errors="ignore") if isinstance(content, bytes) else str(content),
    }


@router.get("/company/categories")
def get_company_categories(
    code: str = Query(..., description="股票代码 e.g. 300027"),
):
    """获取公司资料可用分类列表."""
    collector = _get_collector()
    market = collector._code_to_market(code)

    try:
        with collector._connect() as client:
            cats = client.get_company_info_category(market, code)
    except Exception as e:
        raise HTTPException(502, f"TDX 连接失败: {e}")

    if not cats:
        return []
    return [{"name": c["name"], "length": c["length"]} for c in cats]


# ── 8. XDXR Info (除权除息) ──────────────────────────

@router.get("/xdxr")
def get_xdxr(
    code: str = Query(..., description="股票代码 e.g. 300027"),
):
    """获取除权除息信息 (分红/送股/配股历史)."""
    collector = _get_collector()
    market = collector._code_to_market(code)

    try:
        with collector._connect() as client:
            df = client.to_df(client.get_xdxr_info(market, code))
    except Exception as e:
        raise HTTPException(502, f"TDX 获取除权除息失败: {e}")

    if df is None or len(df) == 0:
        return []

    result = []
    for _, row in df.iterrows():
        item = {
            "date": f"{int(row['year'])}-{int(row['month']):02d}-{int(row['day']):02d}",
            "category": int(row.get("category", 0)),
            "name": str(row.get("name", "")),
        }
        cat = item["category"]
        if cat == 1:  # 除权除息
            item["fenhong"] = float(row.get("fenhong", 0))
            item["songzhuangu"] = float(row.get("songzhuangu", 0))
            item["peigu"] = float(row.get("peigu", 0))
            item["peigujia"] = float(row.get("peigujia", 0))
        result.append(item)
    return result


# ── 9. Board / Sector (板块分类) ─────────────────────

@router.get("/boards/industry")
def get_industry_boards():
    """获取行业板块分类 {行业名: [股票代码]}."""
    collector = _get_collector()
    try:
        boards = collector.fetch_industry_boards()
    except Exception as e:
        raise HTTPException(502, f"TDX 获取行业板块失败: {e}")
    return boards


@router.get("/boards/concept")
def get_concept_boards():
    """获取概念板块分类 {概念名: [股票代码]}."""
    collector = _get_collector()
    try:
        boards = collector.fetch_concept_boards()
    except Exception as e:
        raise HTTPException(502, f"TDX 获取概念板块失败: {e}")
    return boards


# ── 10. Stock List (股票列表) ────────────────────────

@router.get("/stocks")
def get_stock_list():
    """获取全部A股股票列表."""
    collector = _get_collector()
    try:
        df = collector.fetch_stock_list()
    except Exception as e:
        raise HTTPException(502, f"TDX 获取股票列表失败: {e}")

    if df is None or len(df) == 0:
        return []
    return df.to_dict(orient="records")
