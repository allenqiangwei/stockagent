# AkShare 常用函数参考

> 官方文档: https://akshare.akfamily.xyz/data/stock/stock.html
>
> 使用 Context7 查询: `/websites/akshare_akfamily_xyz`

## 实时行情

### stock_zh_a_spot_em()
东方财富 A 股实时行情（推荐）
```python
import akshare as ak
df = ak.stock_zh_a_spot_em()
# 返回: 代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交量, 成交额, 振幅, 最高, 最低, 今开, 昨收, 量比, 换手率, 市盈率, 市净率, 总市值, 流通市值, 涨速, 5分钟涨跌, 60日涨跌幅, 年初至今涨跌幅
```

### stock_zh_index_spot_sina()
新浪财经指数实时行情
```python
df = ak.stock_zh_index_spot_sina()
# 返回: 代码, 名称, 最新价, 涨跌额, 涨跌幅, 今开, 最高, 最低, 成交量, 成交额
```

### stock_individual_info_em()
个股基本信息
```python
df = ak.stock_individual_info_em(symbol="000001")
# 返回: 总市值, 流通市值, 行业, 上市时间, 股票代码, 股票简称, 总股本, 流通股
```

## 历史行情

### stock_zh_a_hist()
东方财富 A 股历史数据（推荐）
```python
df = ak.stock_zh_a_hist(
    symbol="000001",           # 股票代码（不带后缀）
    period="daily",            # daily/weekly/monthly
    start_date="20240101",     # YYYYMMDD
    end_date="20240301",
    adjust="qfq"               # qfq前复权/hfq后复权/空字符串不复权
)
# 返回: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
```

### stock_zh_index_daily()
指数历史日线数据
```python
df = ak.stock_zh_index_daily(symbol="sh000001")  # sh上证/sz深证
# 返回: date, open, high, low, close, volume
```

### stock_zh_a_hist_min_em()
分钟级历史数据
```python
df = ak.stock_zh_a_hist_min_em(
    symbol="000001",
    start_date="2024-01-01 09:30:00",
    end_date="2024-01-01 15:00:00",
    period="5",                # 1/5/15/30/60分钟
    adjust="qfq"
)
```

## 板块数据

### stock_board_industry_name_em()
东方财富行业板块列表
```python
df = ak.stock_board_industry_name_em()
# 返回: 排名, 板块名称, 板块代码, 最新价, 涨跌幅, 涨跌额, 总市值, 换手率, 上涨家数, 下跌家数, 领涨股票, 领涨股票涨跌幅
```

### stock_board_industry_cons_em()
行业板块成分股
```python
df = ak.stock_board_industry_cons_em(symbol="小金属")
# 返回: 序号, 代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交量, 成交额, 振幅, 最高, 最低, 今开, 昨收, 换手率, 市盈率, 市净率
```

### stock_board_concept_name_em()
概念板块列表
```python
df = ak.stock_board_concept_name_em()
# 返回: 排名, 板块名称, 板块代码, 最新价, 涨跌幅, 涨跌额, 总市值, 换手率, 上涨家数, 下跌家数, 领涨股票, 领涨股票涨跌幅
```

## 资金流向

### stock_individual_fund_flow()
个股资金流向
```python
df = ak.stock_individual_fund_flow(stock="000001", market="sz")
# 返回: 日期, 收盘价, 涨跌幅, 主力净流入, 小单净流入, 中单净流入, 大单净流入, 超大单净流入
```

### stock_market_fund_flow()
大盘资金流向
```python
df = ak.stock_market_fund_flow()
# 返回: 日期, 上证指数, 深证成指, 主力净流入, 小单净流入, 中单净流入, 大单净流入, 超大单净流入
```

### stock_sector_fund_flow_rank()
板块资金流排名
```python
df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
# indicator: 今日/5日/10日
# sector_type: 行业资金流/概念资金流/地域资金流
```

## 交易日历

### tool_trade_date_hist_sina()
交易日历
```python
df = ak.tool_trade_date_hist_sina()
# 返回: trade_date 列，包含所有交易日
```

## 股票列表

### stock_info_a_code_name()
A股股票代码和名称
```python
df = ak.stock_info_a_code_name()
# 返回: code, name
```

### stock_info_sh_name_code()
上海交易所股票列表（含更多字段）
```python
df = ak.stock_info_sh_name_code(symbol="主板A股")
# symbol: 主板A股/主板B股/科创板
```

## 指数代码对照

| 指数名称 | AkShare代码 | TuShare代码 |
|---------|------------|------------|
| 上证指数 | sh000001 | 000001.SH |
| 深证成指 | sz399001 | 399001.SZ |
| 创业板指 | sz399006 | 399006.SZ |
| 沪深300 | sh000300 | 000300.SH |
| 中证500 | sh000905 | 000905.SH |

## 注意事项

1. **代码格式**: AkShare 大多数函数使用纯数字代码（如 "000001"），不带交易所后缀
2. **日期格式**: 部分函数用 YYYYMMDD，部分用 YYYY-MM-DD，需查看具体函数
3. **频率限制**: 建议请求间隔 0.5 秒以上
4. **数据源**: 主要来自东方财富(em)、新浪(sina)、同花顺等，不同来源字段略有差异
