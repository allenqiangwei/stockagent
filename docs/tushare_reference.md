# TuShare Pro 常用函数参考

> 官方文档: https://tushare.pro/document/2
>
> 使用 Context7 查询: `/websites/tushare_pro_document`
>
> **注意**: TuShare Pro 需要 Token 和积分，部分接口有积分门槛

## 初始化

```python
import tushare as ts

# 设置 Token（只需设置一次）
ts.set_token('your_token_here')

# 获取 API 接口
pro = ts.pro_api()

# 或者直接传入 token
pro = ts.pro_api('your_token_here')
```

## 股票列表

### stock_basic - 股票列表
```python
df = pro.stock_basic(
    exchange='',           # 交易所: SSE上交所/SZSE深交所/BSE北交所，空为全部
    list_status='L',       # L上市/D退市/P暂停上市
    fields='ts_code,symbol,name,area,industry,market,list_date'
)
# 返回: ts_code(股票代码), symbol(股票简码), name(名称), area(地区),
#       industry(行业), market(市场类型), list_date(上市日期)
```

## 日线行情

### daily - A股日线行情
```python
# 单只股票
df = pro.daily(
    ts_code='000001.SZ',   # 股票代码
    start_date='20240101', # 开始日期 YYYYMMDD
    end_date='20240301'    # 结束日期
)

# 多只股票
df = pro.daily(ts_code='000001.SZ,600000.SH', start_date='20240101', end_date='20240301')

# 单日全市场
df = pro.daily(trade_date='20240301')

# 返回: ts_code, trade_date, open, high, low, close, pre_close,
#       change, pct_chg, vol(成交量,手), amount(成交额,千元)
```

### daily_basic - 每日指标
```python
df = pro.daily_basic(
    ts_code='000001.SZ',
    trade_date='20240301',
    fields='ts_code,trade_date,close,turnover_rate,volume_ratio,pe,pe_ttm,pb,ps,total_mv,circ_mv'
)
# 返回: ts_code, trade_date, close, turnover_rate(换手率%), volume_ratio(量比),
#       pe(市盈率), pe_ttm, pb(市净率), ps(市销率),
#       total_mv(总市值,万元), circ_mv(流通市值,万元)
```

## 指数数据

### index_daily - 指数日线
```python
df = pro.index_daily(
    ts_code='000001.SH',   # 指数代码
    start_date='20240101',
    end_date='20240301'
)
# 返回: ts_code, trade_date, close, open, high, low, pre_close,
#       change, pct_chg, vol, amount
```

### index_dailybasic - 指数每日指标
```python
df = pro.index_dailybasic(
    ts_code='000001.SH',
    trade_date='20240301',
    fields='ts_code,trade_date,total_mv,float_mv,turnover_rate,pe,pb'
)
# 返回: ts_code, trade_date, total_mv(总市值), float_mv(流通市值),
#       turnover_rate(换手率), pe(市盈率), pb(市净率)
```

## 资金流向

### moneyflow - 个股资金流向
```python
# 单日全市场
df = pro.moneyflow(trade_date='20240301')

# 单只股票
df = pro.moneyflow(ts_code='000001.SZ', start_date='20240101', end_date='20240301')

# 返回: ts_code, trade_date,
#       buy_sm_vol(小单买入量), sell_sm_vol(小单卖出量), buy_sm_amount, sell_sm_amount,
#       buy_md_vol(中单), sell_md_vol, buy_md_amount, sell_md_amount,
#       buy_lg_vol(大单), sell_lg_vol, buy_lg_amount, sell_lg_amount,
#       buy_elg_vol(特大单), sell_elg_vol, buy_elg_amount, sell_elg_amount,
#       net_mf_vol(净流入量), net_mf_amount(净流入额)
```

### moneyflow_dc - 东财个股资金流（需5000积分）
```python
df = pro.moneyflow_dc(trade_date='20240301')
# 返回: trade_date, ts_code, name, pct_change, close,
#       net_amount(主力净流入,万), net_amount_rate(%),
#       buy_elg_amount(超大单净流入), buy_lg_amount(大单),
#       buy_md_amount(中单), buy_sm_amount(小单)
```

## 交易日历

### trade_cal - 交易日历
```python
df = pro.trade_cal(
    exchange='SSE',        # SSE上交所/SZSE深交所
    start_date='20240101',
    end_date='20241231'
)
# 返回: exchange, cal_date, is_open(1开盘/0休市), pretrade_date(上一交易日)
```

## 复权因子

### adj_factor - 复权因子
```python
df = pro.adj_factor(
    ts_code='000001.SZ',
    trade_date='20240301'
)
# 返回: ts_code, trade_date, adj_factor
# 前复权价 = 当日收盘价 * 当日复权因子 / 最新复权因子
# 后复权价 = 当日收盘价 * 当日复权因子
```

## 股票代码格式

| 交易所 | 后缀 | 示例 |
|-------|-----|------|
| 上海 | .SH | 600000.SH |
| 深圳 | .SZ | 000001.SZ |
| 北京 | .BJ | 430047.BJ |

## 常用指数代码

| 指数名称 | TuShare代码 |
|---------|------------|
| 上证指数 | 000001.SH |
| 深证成指 | 399001.SZ |
| 创业板指 | 399006.SZ |
| 沪深300 | 000300.SH |
| 中证500 | 000905.SH |
| 上证50 | 000016.SH |

## 积分要求

| 接口 | 所需积分 |
|-----|---------|
| stock_basic | 免费 |
| daily | 免费 |
| daily_basic | 免费 |
| index_daily | 免费 |
| trade_cal | 免费 |
| moneyflow | 2000 |
| moneyflow_dc | 5000 |
| index_dailybasic | 400 |

## 注意事项

1. **日期格式**: 统一使用 `YYYYMMDD` 格式（字符串）
2. **频率限制**: 每分钟最多调用 500 次（根据积分等级不同）
3. **单次限制**: 大多数接口单次返回不超过 5000 条
4. **数据延迟**: 日线数据通常 15:30-17:00 更新
5. **fields参数**: 可以指定只返回需要的字段，减少数据传输

## 错误处理

```python
try:
    df = pro.daily(ts_code='000001.SZ', start_date='20240101', end_date='20240301')
except Exception as e:
    print(f"API调用失败: {e}")
    # 常见错误:
    # - 抱歉，您没有访问该接口的权限 → 积分不足
    # - 参数错误 → 检查日期格式或代码格式
    # - 超过访问频率 → 添加延时
```
