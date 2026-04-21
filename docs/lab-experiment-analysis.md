# AI 策略实验室 — 实验结果分析

> 更新时间: 2026-03-19 | **1189轮探索** | **ALL-TIME RETURN: 8909%** (AM8 TP1.0 MHD2, R1139) | **ALL-TIME SCORE (StdA+): 0.8717** (R1148) | **R1188**: 522实验/4176策略/667 StdA+(16%), best 0.853. **R1189**: 500实验/4000策略已提交(5骨架并行填充), 回测进行中.
>
> **StdA+标准(2026-03-07起)**: score≥0.80, return>60%, dd<18%, trades≥50, **win_rate>60%**
> **BUG FIX (R66 session)**: r54_process.py api_put 404 — 添加PUT `/api/lab/strategies/{id}` + `/api/lab/experiments/{id}`, 修复555策略backtest_summary (旧标准: score≥0.70, ret>20%, dd<25%)

---

## 核心洞察

> **556轮实验、~4982个实验、~8763个StdA+策略的核心发现**:

1. **KDJ 是 A 股最有效的技术指标** — 四轮实验持续验证。第四轮 67 个 KDJ 主题产出 26 个盈利策略, 最高收益 +60.7%, 且 5 个策略在牛/熊/震荡全阶段盈利
2. **KDJ+MACD 是最佳指标组合** — 双金叉(+34.1%), 趋势跟踪(+29.3%), 底背离(+26.9%) 三个方向均有不错收益
3. **短周期 KDJ(6,3,3) 比默认(9,3,3)更优** — 40% 盈利率, 最佳回撤仅 6.6%, 适合 A 股快进快出
4. **全阶段盈利策略的共同特征: 短持仓+快换手** — 5 个全阶段盈利策略全部是短线/超短线类
5. **震荡市是最大利润杀手** — 仅 4% 的策略在震荡市盈利, 而 A 股大部分时间处于震荡
6. **3+ 指标组合适得其反** — 2 个互补指标是组合上限, 3+ 指标几乎全军覆没
7. **3-4 个买入条件最优** — 2 条件过于宽松, 5+ 条件导致零交易
8. **纯均线/EMA策略在 A 股无效** — 均线金叉/EMA趋势追踪连续四轮 0 盈利, EMA+ATR动态止损全军覆没(-50%~-98%)
9. **CMF在A股几乎永远为负** — CMF_20对绝大多数A股股票持续为负值(测试茅台: -0.51~-0.003), CMF>0几乎不可能。先前21%盈利率来自多指标组合中CMF不起主导作用, 独立使用全军覆没
10. **BOLL_lower 最佳收益 +59.0%** — 布林下轨买入有强反弹动能
11. **规则引擎P4升级已完成, DeepSeek仍是瓶颈** — 新增6种compare_type(lookback_min/max/value, consecutive, pct_diff, pct_change), 支持N日回溯/连续涨跌/百分比偏差条件。条件可达性预检可在回测前检测矛盾条件。但DeepSeek即使收到详细格式说明仍不使用新类型, 需要更强的few-shot示例或硬编码模板
12. **非KDJ指标组合表现不佳** — KDJ+RSI(0%), KDJ+EMA(0%), MACD+RSI(6.7%), EMA+ATR(0%)四组P2实验合计仅1/23盈利; KDJ+MACD仍是唯一有效双指标组合
13. **RSI极端超卖(<25)盈利率高但信号极少** — 简化版4/6盈利(66.7%), 但保守版仅4-17笔交易, 最高+6.1%; 阈值放宽到RSI<30则亏损; 统计意义不足, 不适合独立使用
14. **KDJ+MACD短周期参数(6,3,3)+(8,17,9)不优于默认** — 短周期精调1/8盈利(+17.5%, score 0.57), 远不如默认参数(+34.1%, score 0.68); 默认参数已是最优
15. **放量条件对KDJ无增益** — KDJ金叉+放量确认0/8盈利, volume突破在A股超卖区不是有效信号, 可能因超卖区放量多为出货而非进场
16. **MACD柱线翻正作为主信号灾难性** — 0/8盈利, 亏损-37%~-99.8%, MACD_hist>0过于频繁触发, 震荡市单策略亏超3000元
17. **DeepSeek无法精确复现已有策略** — 即使描述相同买入条件, DeepSeek生成的实际规则与原始策略存在微妙差异, 导致"止盈止损优化"实验0/8盈利(原策略+37.1%)
18. **ADX/MA20等趋势过滤无法对抗震荡市** — ADX>25在震荡市中也会被短暂波动触发, MA20方向过滤有微弱效果但不足以盈利。没有任何单一技术指标能可靠识别并过滤震荡市
19. **field-to-field比较功能正常** — 规则引擎支持close<BOLL_lower等field比较, P7不是bug。但BOLL下轨条件极度严苛(close跌破布林下轨+超卖), 几乎无法触发
20. **新扩展指标大规模探索: 绝大多数无效** — 第十轮新增33个TA-lib指标, 20+实验160+策略全部完成。done=89中仅14个盈利(15.7%), 3个达Standard A。仅PSAR/ULCER/Keltner/UltimateOsc/Stochastic/BOLL%B+StochRSI有效, 其余全部无效
21. **PSAR是KDJ之外最有效的新指标** — PSAR+ADX+CCI+BOLL组合score=0.66/ret+14.3%/dd仅6.1%达到Standard A, PSAR+RSI+BOLL震荡市盈利+95元(罕见)。PSAR作为止损反转指标与多指标组合表现优秀
22. **Keltner+ULCER低波动策略有独特价值** — ULCER<5+KDJ_K<25组合盈利率38%(3/8), 最佳+19.5%。ULCER是唯一有效衡量下行风险的指标, 低ULCER+超卖=高概率反弹
23. **BOLL%B+StochRSI是最佳新发现** — 收益+37.9%/score 0.66/233trades, 达到Standard A。StochRSI比普通RSI更灵敏, BOLL%B比原始BOLL提供更标准化信号
24. **UltimateOscillator是最大惊喜** — 批量重试后ID129以50%盈利率(3/6)突出, 中性版C score=0.72/ret+28.0%/dd11.2%达Standard A。ULTOSC综合三周期(7/14/28)动量, 是KDJ/MACD之外第三个有效的独立震荡指标
25. **Stochastic(STOCH)也有价值** — ID128以50%盈利率(2/4)超预期, 保守版C +28.4%/dd23.4%。但STOCH_K和STOCH_D与KDJ类似, 非独立发现
26. **三层防护系统有效防止回测挂死** — L1增强信号爆炸检测(周期性重检每50天), L2单策略5分钟超时(threading.Timer+cancel_event), L3实验60分钟看门狗。323策略重试零挂死
27. **组合策略(P3)信号投票机制已实现** — 支持N个成员策略投票, 可配置投票阈值/卖出模式/权重。5个多元化策略(KDJ/PSAR/BOLL%B+StochRSI/全指标/UltimateOsc)组合投票结果: threshold=2/5仅产生6笔交易+1.0%收益, 极低回撤(0.2%); threshold≥3/5全部零交易。多元化策略组合过于保守, 应使用同类指标(如3个KDJ变体)提高信号频率
28. **组合策略性能瓶颈** — 5成员组合回测每只股票需计算5组指标+5次条件评估/天, 单策略回测约10分钟(vs 普通策略<1分钟)。18成员组合超15分钟timeout。需优化: 减少成员数/缓存指标计算/并行评估
29. **PSAR+ULCER+KDJ三重过滤是最高盈利率策略方向** — ID161取得71%盈利率(5/7), ID162精调版50%(4/8), ID163变体75%(3/4)。三重过滤(趋势确认+低波动+超卖)产生高质量信号。S1235达Standard A(score 0.69, +14.5%, dd 3.7%)且全阶段盈利
30. **UltimateOsc+KDJ双震荡组合失败** — ID159全部亏损(0/5), 两个震荡指标同时超卖过于严格, 信号质量不如PSAR趋势过滤。ULCER+STOCH组合也不佳(ID160, 0/2有效)。关键:需要不同类型指标(趋势+波动+超卖)而非同类指标叠加
31. **PSAR+MACD+KDJ是新晋最强组合** — S1277(PSAR趋势动量_保守版A)达score 0.77/+70.8%/dd12.6%/1012笔, 全阶段盈利(ranging+53/bull+404/bear+125)。PSAR提供趋势方向、MACD提供动量、KDJ提供超卖确认。三维度协同效果远超双指标组合
32. **同类指标叠加是死胡同** — STOCH+KDJ(ID165: 7/8信号爆炸), ULTOSC+KDJ(ID159: 0/5盈利), ULCER+STOCH(ID160: 0/2有效)全部失败。两个超卖指标叠加只会放大信号噪声,不提供新信息
33. **PSAR+BOLL+KDJ是第二强三维组合, 网格搜索8/8达StdA** — 基础S1334(score 0.70, +27.5%, dd 8.2%)经网格搜索优化, 最佳SL8_TP10变体(score 0.740, +39.6%, dd 8.0%). **TP10显著优于TP15/20**(+37-40% vs +26-28%), SL对结果影响极小(dd 8.0-8.8%), 说明买入条件本身就能规避深度亏损. 全阶段盈利, 极度鲁棒
34. **PSAR+RSI和PSAR+EMA的field比较指令DeepSeek完全不执行** — ID171(PSAR+EMA+KDJ)和ID172(PSAR+RSI精调)各8策略全部invalid。DeepSeek收到"PSAR用field比较"指令后仍生成无效条件。仅PSAR+BOLL组合偶尔生成正确field条件
35. **PSAR+RSI+KDJ(非field指令)仍是最高盈利率方向** — ID168(57%盈利率, S1293达StdA)不使用field比较指令, 而是让DeepSeek自由发挥。PSAR相关实验中, 不明确指定field比较反而成功率更高
36. **克隆调参网格搜索突破性成果** — 绕过DeepSeek, 直接克隆S1277修改exit_config跑11种参数组合。发现SL10_TP15(score 0.779, +82.8%, dd14.7%)超越原始S1277(score 0.77, +70.8%)。宽止损(-10%)比窄止损(-5%)更优: 给予价格更多波动空间, 避免过早止损。8/11变体全部达Standard A, 证明PSAR+MACD+KDJ策略极其鲁棒
37. **14线程并发回测导致超时** — 同时启动14个clone-backtest, 每个线程独立加载5000+股3年数据, 严重SQLite竞争。部分策略在300秒超时限制内无法完成(被标invalid), 串行或少量并发则正常完成。建议: 并发回测数不超过3-4个
38. **UltimateOsc对TP极度敏感, TP10最优** — 网格搜索6变体: TP10版(SL5/8/10)全部score 0.711-0.723、dd仅6.6%; TP15版全部score 0.678-0.693、dd 9.5-9.6%. **TP10比基础(TP18)的dd降低40%(6.6% vs 11.2%), score提升(0.723 vs 0.718)**. SL对结果几乎无影响(dd都是6.6%)
39. **KDJ+MACD双金叉和BOLL%B+StochRSI原始参数已最优** — 两个策略各6种exit变体全部不如原始。KDJ+MACD最佳变体(SL10_TP15, 0.651)比原始(0.678)低4%; BOLL%B+StochRSI最佳变体(SL8_TP15, 0.621)比原始(0.656)低5%. 说明DeepSeek为这些策略选择的exit参数恰好是最优的
40. **DeepSeek新实验生成已基本失效(87.5% invalid)** — 第十六轮6个DeepSeek实验仅5/40策略完成(12.5%), 0盈利. PSAR+MACD简化版(P21/P22修复后)仍8/8 invalid; STOCH+KDJ 4/4 invalid; ULCER+KDJ 8/8 invalid. DeepSeek对新指标的条件格式化能力极差. 未来应完全依赖grid search+手动构造, 不再使用DeepSeek生成新策略
41. **全指标综合_保守版B紧止盈(TP10)达dd 3.4%** — S63(0.753/+29.1%/dd4.0%)的SL8_TP10变体(0.747/+26.8%/dd3.4%)用更紧止盈换取更低回撤, 牺牲2.3pp收益但dd降0.6pp. 适合极度保守的投资者
42. **KDJ金叉_中性版A不适合缩短止盈** — S115(SL-9/TP22)改为SL8_TP15后-1.0%(dd 32.2%), SL10_TP15仅+2.4%(dd 31.4%). KDJ金叉需要更宽的止盈空间让利润奔跑
43. **TP14是PSAR+MACD+KDJ的最优止盈点!** — 细粒度搜索发现TP14在所有SL水平下都是峰值: SL9(0.793/+92.6%), **SL10(0.802/+99.6%)**, SL11(0.801/+99.2%). 比之前最佳TP15多赚+17pp! **S1481 SL10_TP14=新全局最佳(score 0.802, +99.6%, dd 12.2%, 969trades)**
44. **全指标综合_保守版B的TP8创dd新低(3.3%)** — SL6_TP8(0.737/+25.0%/dd3.3%)和SL7_TP8(0.737/+25.1%/dd3.3%)达到全策略最低回撤. TP9导致零交易(invalid), 说明TP8是该策略的最小可行止盈点
45. **PSAR+BOLL+KDJ的TP9优于TP10!** — SL8_TP9(0.753/+42.0%/dd6.0%)同时在score、return和dd三维度都优于SL8_TP10(0.740/+39.6%/dd8.0%), 是Pareto改进. TP9使dd从8.0%降至6.0%(降25%), 同时收益提升+2.4pp
46. **Max Hold Days对PSAR+MACD+KDJ影响极小** — MHD30已是最优(0.802/+99.6%). MHD15损失10%收益, MHD25基本持平(0.800/+98.2%), MHD35+收敛到相同水平(+99.4-99.8%). 说明绝大多数交易在30天内通过TP14/SL10自然平仓, max_hold_days不是关键参数
47. **全指标综合_中性版C的SL7_TP14_MHD15=新全局最高评分(0.825)!** — SL7比SL5多2pp止损空间, 收益从+75.6%升至+90.5%(+15pp!). TP14再次证明是黄金止盈点(同时对PSAR+MACD+KDJ和全指标综合两大策略族最优). MHD15短持仓适合该策略快换手特性. SL7_TP15(0.820/+85.5%)也超越旧最佳
48. **TP14移植对5/6策略族有效, MACD+RSI是最大赢家** — R20对6个单变体StdA策略做TP14+SL7移植: 三指标共振(+3.5%), KDJ超短线(+2.6%), KDJ极致保守(+2.0%), PSAR+RSI+KDJ(+0.9%), **MACD+RSI(+6.0%!从0.672→0.732,收益翻倍+51.1%)**. 唯一失败: ULTOSC共振需要更宽TP20. **TP14已确认为跨所有KDJ/MACD策略族的通用最优止盈**
49. **MHD对大多数策略无影响, 但MACD+RSI是例外** — R21对4个策略族做MHD精扫: PSAR+BOLL+KDJ(MHD20=MHD28), UltimateOsc(MHD15≈MHD25), 全指标综合_保守版B(MHD15=MHD30). 绝大多数交易通过TP/SL在MHD前平仓. **唯一例外**: MACD+RSI的MHD15(0.738/+59.8%)和MHD30(0.739/+54.2%)均显著优于MHD25(0.732/+51.1%), MHD15收益最高!
50. **SL7仅对全指标综合和MACD+RSI有效** — R21验证SL7移植到PSAR+BOLL+KDJ(0.746<0.753)和UltimateOsc(0.727<0.731)均降低。SL最优值因策略而异: 全指标综合/MACD+RSI→SL7, PSAR+BOLL+KDJ→SL8, PSAR+MACD+KDJ→SL10, UltimateOsc→SL无关
51. **全指标综合_保守版B TP9创dd 3.2%新纪录** — SL8_TP9(0.744/+26.4%/dd3.2%)比TP10(0.747/+26.8%/dd3.4%)dd更低0.2pp但score降0.003. TP8(dd3.3%)和TP9(dd3.2%)是该策略的极限低回撤区间
52. **UltimateOsc的TP7(0.758)是新最优!** — R22发现TP越紧越好: TP7(0.758)>TP8(0.742)>TP9(0.731)>TP10(0.723)>TP11(0.718), 单调递减。ULTOSC不同于其他策略族, 极度短平快最优. SL对其完全无影响(dd始终6.6%)
53. **TP14不是真正通用的** — R22 TP14跨族移植: PSAR三重确认(0.669≈原0.674), BOLL%B+StochRSI(0.643<原0.656), PSAR+ADX+CCI+BOLL(0.669≈原0.674). TP14仅对KDJ/MACD类策略有效, 非KDJ系的策略各有不同最优TP
54. **MACD+RSI在MHD15下TP15(0.736)回归最优** — R20在MHD25下TP14最优(0.732), 但R22在MHD15下TP15(0.736)更好。MHD影响TP最优点: 短持仓倾向更宽止盈
55. **R22精扫100%盈利率+96% StdA** — 50个grid search变体中49/49盈利(1 invalid), 47/49达StdA. 在已知最优区间的精细搜索具有极高命中率
56. **PSAR TP4创收益新纪录+135.6%** — R24发现TP4(avg +131.4%)>TP5(avg +121%)>TP6(+111%)>TP7(+106%). PSAR策略族的最优止盈随着实验深入持续下移(TP14→TP7→TP5→TP4), 说明PSAR信号的最佳持仓极短
57. **全指标综合 TP14确认无可争议(score 0.818)** — R24大规模验证: TP14(0.818)>>TP12(0.813)>TP15(0.815)>TP8(0.799)>TP7(0.802). SL10>SL9(0.820 vs 0.819). 全指标综合与PSAR的TP最优点完全不同(TP14 vs TP4), 反映截然不同的信号特性
58. **SL对大多数策略影响极小** — R24覆盖SL5-15, 同TP下不同SL的score差异通常<0.005. BOLL+KDJ(SL6-10差异<0.006), UltimateOsc(SL完全无影响), PSAR(SL10-12微优但差异<0.004). 买入条件本身已提供足够的下行保护
59. **PSAR TP3创+151.7%全局最高收益** — R25发现PSAR极短止盈(TP2-4)区间持续产出超高收益, S2225(SL10_TP3_MHD30)=**+151.7%**(score 0.808)超越R24的TP4纪录(+135.6%). TP越低收益越高但交易数暴涨(1400+), 高频交易放大趋势追踪优势
60. **PSAR+MACD+KDJ和全指标综合两族占据绝对统治** — R25 198个StdA中69个≥0.80, 全部来自这两大族(PSAR 45个, 全指标综合 24个). 其余5族(BOLL+KDJ/保守版B/MACD+RSI/UltimateOsc/KDJ)稳定但无法突破0.80. 参数空间已极限穷尽
61. **三指标共振 TP1 = 历史最高评分0.803 + 最高收益+188.6%** — R28发现TP1(最短止盈)是三指标共振的最优参数, 远超之前的TP8-15范围. 6个策略score≥0.80(首次突破!), SL对结果几乎无影响(SL5-15仅差0.003). MHD越短越好(MHD3>MHD5>MHD7), 2700+交易实现极高频交易+极高收益. 颠覆了"TP越低收益越高仅限PSAR"的认知, 三指标共振也具有极短持仓优势
62. **PSAR三重确认 TP1-3不达StdA标准** — R28测试31个变体(TP1/2/3 × SL5-12 × MHD7-15), 最佳仅score=0.641/+9.3%. 该族需要TP≥6(已知最优TP6=0.67)才能达到StdA. 极低DD(2.2%)但交易数和收益率不足
63. **MHD1(当日卖出)是终极参数 — R29发现** — PSAR+RSI+KDJ 激进版A TP1/SL12/MHD1 = **+627.7%**(S3431), 碾压前纪录+367.4%! MHD1使日均换手率最大化, 极致复利。三指标共振 MHD1也达0.814(R29最高分)。DD与MHD基本无关(激进版A恒定13.9%)
64. **PSAR+ADX+CCI确认死胡同(TP1-2)** — R29测试54个变体(TP1/2 × SL5-15 × MHD1-15), 0/54达StdA+, 最佳score仅0.679。该族在低TP下完全失效, 与其他族特性不同
65. **5族100%达StdA+(R29)** — 三指标共振(29/29=100%, 0.814), 全指标综合(15/15=100%, 0.807), UltimateOsc(20/20=100%, 0.759), 保守版B(40/40=100%, 0.724), PSAR+RSI+KDJ 激进版A(101/114=89%, 0.810/+627.7%)
66. **MHD2是PSAR+MACD+KDJ的甜蜜点, 非MHD1(R30)** — S3807 TP1/SL12/MHD2 = score **0.830**(NEW ALL-TIME RECORD), +269.8%, dd5.2%。MHD2>MHD5(0.825)>MHD1。不同于激进版A(MHD1最优)和三指标共振(MHD1最优), PSAR+MACD+KDJ隔日卖出反而最优。每个策略族都有独立的最优MHD, 不能一刀切
67. **MHD3-10对PSAR+MACD+KDJ分数无显著提升(R31)** — MHD3-10 × SL5-15 × TP1-2, 70/70全部StdA+(100%). 最高score 0.825(MHD3/4/5), 与MHD2的0.830相比微降。说明MHD2确实是该族最优, MHD延长不带来额外收益, 参数空间已完全穷尽
68. **激进版A MHD2-5超高收益, 最高+517.6%(R31)** — 60个变体中56/60 StdA+(93%), MHD2/SL10-12/TP1组合收益400-517%, DD恒定13.9%。MHD2是该族第二甜蜜点(仅次于MHD1的+627.7%), 但交易数更多(4450笔), 更稳健
69. **KAMA是唯一有潜力的新指标(R31)** — 15个DeepSeek实验(120策略), 74 done / 46 invalid, **9个StdA+**(12.2%). 最佳: KAMA终极震荡_中性版D(score 0.791, +92.3%, dd23.2%), KAMA中长线_保守版F(0.778, +34.0%, dd7.6%). KAMA自适应均线有独特价值, 值得grid search深入
70. **WR/MFI/ROC三个新指标全部失败(R31)** — WR(25 done/0 StdA+, best 0.676), MFI(29 done/0 StdA+, best 0.662), ROC(4 done/0 StdA+, best 0.322/负收益). 这三个指标不适合A股量化策略, 不再探索
71. **Grid search仍是唯一可靠方法(R31确认)** — 网格搜索261/265=98.5% StdA+, DeepSeek新指标9/132=6.8% StdA+. 成功率差距14倍。新指标探索应只用少量DeepSeek试探, 发现有效后立即转grid search
72. **KAMA终极震荡刷新全局最高分0.831(R32)** — S4900 SL13/TP1/MHD1 = score **0.831**, +360.3%, dd8.9%, 2476笔交易。超越PSAR+MACD+KDJ的0.830(S3807)。KAMA自适应均线+UltimateOsc震荡双确认, MHD1(当日卖出)是该族最优。SL11-15均达0.828-0.831, SL不敏感
73. **KAMA突破家族全面爆发(R32)** — 6个子族(中性版C/D/E, 保守版F/G, 激进版A)全部100% StdA+, 均120/120达标。最佳score 0.828(SL12/TP1/MHD1), 收益+389.4%, dd9.1%。KAMA突破是继PSAR+MACD+KDJ后第二个score超0.82的策略大类
74. **KAMA是第二大策略超级家族** — R32一轮新增294个StdA+, KAMA总计371个StdA+(含R31的77个)。仅KAMA终极震荡+KAMA突破两个子族就贡献了38个score≥0.82的精英策略。KAMA的TP1/MHD1组合与PSAR系列的TP1/MHD1-2表现类似, 进一步确认"极短持仓+极低止盈"是A股最优通用策略
75. **NVI(负成交量指标)浅探索: 仅1/11达StdA+(R32)** — 6个DeepSeek实验, 11个done策略, 仅NVI机构追踪_中性版B达StdA+(score 0.719, +55.8%, dd17.9%). NVI追踪机构行为的理论合理, 但实践效果有限。值得用grid search对该唯一StdA+策略做参数优化
76. **VPT+PSAR是新王牌家族 — R37 grid search 90% StdA+!** — R32独立VPT无效. R36 VPT+PSAR首个StdA+(0.752). **R37 grid search: 18/20 StdA+(90%)!** S6631 SL7/TP7/MHD7=**0.783**(+102.6%), S6628 SL5/TP3/MHD5=**+130.7%**. 最优参数: SL7-12, TP5-15, MHD7-15. VPT+PSAR+布林带三重过滤在A股极其有效, 已成为第三大超级家族(仅次于全指标综合、PSAR趋势动量)
77. **STC/WR/ROC跨家族组合全部失败(R32)** — STC+KDJ(0/10 StdA+), WR+KDJ/PSAR(0/7 StdA+), ROC+KDJ/PSAR(0/10 StdA+)。仅MFI+KDJ产出1个StdA+(0.718)。浅探索指标与强指标组合也无法挽救, 确认这些指标在A股彻底无效
78. **KAMA中长线家族不适合低TP(R32)** — KAMA中长线_保守版F(0/40 StdA+), KAMA中长线_中性版C(0/20), KAMA中长线_激进版A(0/20)在TP1-5 grid中全部未达标。中长线策略需要更高TP(原始策略TP为默认值), 不适合极短止盈
79. **R32 Grid search成功率再创新高** — 374/388 grid strategies达StdA+(96.4%), DeepSeek仅5/173达StdA+(2.9%)。grid search在KAMA家族的表现与PSAR家族一致: 一旦找到有效基础策略, 参数优化几乎100%成功
80. **⚠️ T+1引擎重新回测: 1,889→1,178 StdA+(62.4%存活)** — 2026-02-28对全部1,950个策略使用T+1引擎(信号T日→T+1开盘执行, 0.1%滑点, 涨跌停限制)重新回测。772个策略被淘汰。关键发现:
    - **全指标综合 成为新王者**: Top 15全部来自全指标综合家族, 最高score 0.825(SL9/TP14/MHD15), +101.2%, dd 12.8%
    - **KAMA终极震荡 全军覆没(0/65 StdA+)**: 之前的0.831全局最高分是前视偏差的产物。KAMA依赖当日收盘价信号立即执行, T+1延迟后alpha完全消失
    - **PSAR+BOLL+KDJ保守版B 全军覆没(0/120 StdA+)**: 该族signal依赖当日价格, 延迟一天后信号过期
    - **KDJ超短线 全军覆没(0/46 StdA+)**: 超短线策略最受T+1影响
    - **存活率最高的族群**: 全指标综合_保守版B(108/108=100%), MACD+RSI(83/84=99%), 三指标共振(194/200=97%), PSAR趋势动量(313/343=91%)
    - **最高收益从+627.7%降至+192.5%**: 三指标共振取代激进版A成为收益冠军
    - **结论**: 之前"极短持仓+极低止盈"的结论在T+1下部分失效, 真正鲁棒的策略需要足够的alpha margin来吸收T+1执行成本
81. **buy_core 5-条件公式(RSI50-70+ATR<0.12+AbvMin13+BelMax10)+ ATRcalm7d = 93% StdA+(R1108)** — ATRcalm条件(ATR 7日涨幅<3%)作为第6个过滤条件将14/15策略提升至StdA+。win_rate=60-71%，远高于dip条件(53-55%)。ATRcalm的原理: 在波动趋于平稳时买入，避免在高波动期入场，自然提升胜率
82. **10条件以上的过约束是0 StdA+的直接原因(R1105-R1107)** — R1105-R1107三轮(E7207-E7210)全部0/all invalid或0 StdA+，原因是叠加了9-10个条件(ATRcalm+RSIconsec+dip+vol+close_ma等)。核心规律: 3-6条件最优，7+条件导致零信号或极少交易
83. **RSI45-65 + dip比RSI50-70 + dip更有效(R1109早期)** — E7215早期结果2/2 StdA+，wr=64-69%。RSI50-70+dip失败(wr=53-55%)，RSI45-65+dip成功。更低的RSI下界(45vs50)可能捕获更多准超卖区间，配合dip条件提高胜率
81. **SL甜蜜点: SL5-14(R121确认)** — SL3失败(score 0.731-0.738, 止损频繁触发于日常波动), SL4勉强通过(0.748-0.752), SL5始终通过。SL15/18/20与SL14完全相同(止损从不触发于TP1策略)。结论: TP1策略的有效SL范围为5-14, 两端均无额外信息
82. **MHD4-10黄金区间: 100%命中(R119)** — MACD+RSI/VPT+PSAR/全指标综合/三指標共振 4族在MHD{4,5,7,10}×SL{10,12}×TP1下32/32 StdA+(100%)。MHD4-10填补了已证实MHD2-3和原始MHD15-30之间的空白
83. **P4时间条件(consecutive/lookback/pct_change/pct_diff)打破0.843 ceiling(R166-R169)** — `sell=close falling 2 consecutive days` (close_fall2d) 取代BOLL+ROC复合卖出条件, 在MACD+RSI buy base上达到**0.845 StdA+** (wr=61.6%, ret=805%, dd=8.1%). 比旧ceiling(0.843)提升0.002. 同时发现: P4 sell条件可轻松达到score 0.855但wr<56%, 说明score-wr负相关是结构性约束. close_fall2d比BOLL_mid+ROC更简洁且更有效
84. **close_fall2d是跨家族有效的卖出条件(R170)** — 应用于5个家族: 三指標(0.817 StdA+), 全指標(0.816 StdA+), KAMA突破(0.777 StdA+), VPT+PSAR(0.797 StdA+). KAMA終極因结构性dd>20%无法达标. 简单P4卖出条件普遍优于复杂指标组合卖出
83. **MHD饱和: MHD≥8后无提升(R122确认)** — KAMA突破 MHD{8,9,12,14,25}全部score=0.765。三指標共振 MHD{12,14,18}全部score=0.777。TP1策略中, MHD越长仅等待更久平仓, 不增加收益
84. **TP>1普遍致命(R116)** — 0/32 StdA+。所有族在TP2+时wr暴跌15-30pp(MACD+RSI: TP1 wr=77.5% → TP2 wr=54-59%)。TP1是所有短MHD策略的唯一最优
85. **PSAR趨勢上升结构性dd失败(R122)** — dd=24.5-24.7%在所有MHD(4-20)下恒定。该族高收益(146-161%)但高dd源于激进入场规则, exit_config无法修复。永久排除于StdA+
86. **高wr基底→grid search方法论有效(R111)** — 5/8家族成功产出StdA+: MACD+RSI(67%), 全指标综合/PSAR趋势动量(50%), VPT+PSAR(44%), 三指標共振(25%)
87. **SL15-20突破: 全7族100% StdA+(R145-R148)** — 宽SL(15-20)在所有家族都优于窄SL(5-12), 因为止损几乎不在5-8天持仓中触发。SL20是有效ceiling(SL25/SL30产生完全相同的结果)。DD从15-17%降至8.6-14.4%, 同时return和score提升。SL范围确认: MACD+RSI/VPT+PSAR SL4-20, 三指標/全指標 SL5-20, PSAR趨勢/KAMA保G SL8-20, KAMA中C SL10-20
88. **TP=2是绝对上限(R149-R150)** — TP2仅对MACD+RSI/全指標/PSAR趋势/VPT+PSAR在MHD4+时有效(wr>60%)。TP2+MHD2-3全部失败(wr 54-59%)。TP3+在SL15-20下仍全部死亡(wr 48-58%, 所有家族), KAMA族TP2也全部失败(wr 58-59%)
89. **MHD15是有效ceiling(R151-R153)** — MHD10/12/15/20/25/30产生几乎完全相同的score。MHD8+后score完全平台化, win rate持续上升(68-77%)但对score无贡献。全7族MHD10-30均100% StdA+
90. **新指标全面失败确认(R154)** — 12个DeepSeek实验(NVI/MFI/WR/ROC/STC/KELTNER/ULTOSC组合), 96策略中69 invalid(72%), 0 StdA+。最高wr仅51.6%(KELTNER+KDJ), 远低于60%。A股T+1高wr策略仅限已知7大家族, 新指标探索空间彻底耗尽
91. **条件阈值优化是SL/TP/MHD之外的第三维度(R155)** — 修改买入/卖出条件的指标阈值(如ATR<0.05→0.06, MFI>50→30)在已知最优exit_config上产出47个新StdA+。ATR<0.05是多族的通用瓶颈(过紧过滤低波动股), 放宽至0.06后MACD+RSI从0.810→**0.821**, 全指标综合从0.795→**0.807**。MFI>50过于严格, 降至30-40使三指标共振从0.783→0.791。批量条件优化功能已实现(信号重向量化+缓存)
92. **MACD+RSI MFI_40创历史新高0.832(R156)** — MFI>50→40进一步松弛使MACD+RSI登顶! 5族创新best: MACD+RSI 0.832(MFI_40), **全指标综合 0.814(删除CCI条件)**, 三指標共振 0.809(ROC>-0.5+ATR_0.06), KAMA突破 0.801(MACD_hist>0.1), VPT+PSAR 0.803(VPT>-1500). **关键发现: 删除冗余条件(CCI)有时比调参更有效; MACD_hist>0.1(更紧)反而比>0更好(质量>数量)**
93. **Min3(MACD+RSI50+ATR0.08)仅3条件=0.832/1822%/12.1%dd(R189)** — 从6条件MACD+RSI ablation实验发现: 移除MFI、RSI<70、lookback后, 3条件版本(MACD>signal+RSI>50+ATR<0.08)竟然与6条件原版score相当(0.832 vs 0.846), 收益翻倍(1822% vs 826%)! 额外条件不增加任何alpha, 只增加复杂度. **简单即是最优**
94. **ATR sweet spot: 0.06-0.08(R189-R190)** — ATR<0.05过紧(wr下降), ATR>0.08 dd爆炸(>18%), ATR 0.06-0.08是跨族通用最优区间. ATR<0.08使交易数从2400→3049(+27%), 收益从826%→1822%
95. **batch-clone只能使用source策略已有指标(R191)** — 向MACD+RSI source添加PSAR/KDJ/EMA/BOLL条件→ALL INVALID. vectorized_signals只计算source的指标集. 跨族指标需DeepSeek实验或独立回测
96. **KDJ超卖(K<30)在A股是死亡策略(R192)** — DeepSeek生成KDJ<30策略4个done, wr=31-38%, dd=33-48%. 买入oversold在A股是亏损策略
97. **DeepSeek无法生成有效PSAR/EMA策略(R192)** — PSAR 8/8 invalid, EMA 7/8 invalid. 这些指标的规则引擎格式DeepSeek理解不了
98. **BWB(布林带宽)对VPT+PSAR不可或缺(R188)** — 移除BWB<5后收益从280%暴跌至25%. BWB是该族关键的波动率过滤器
99. **Combined dual-sell可推score至0.849但wr<60%(R188)** — fall2d+lookback_min组合卖出条件突破score ceiling但牺牲wr(57%), 不满足StdA+. score-wr负相关是结构性约束
100. **全指標ATR0.08+TP1=77.5% wr(R189)** — 历史最高win rate, ATR松弛+TP1极短持仓组合产出超高wr
101. **每族可简化至2条件(R193-R197)** — BOLL+ATR(close>BOLL_mid+ATR<0.06), PSAR+BWB(close>PSAR+BWB<5), EMA+ATR(EMA12>EMA26+ATR<0.06), 删除lookback/CCI/VPT等条件后score不变。**VPT完全无效**(PSAR+BWB=0.806≈VPT+PSAR+BWB=0.799)
102. **gt5dHigh是wr最优卖出条件(R198-R200)** — 跨4族达80%+ wr: EMA+ATR=82.4%, BOLL+ATR=81.6%, Min3=80.6%, PSAR+BWB=77.0%. 远超fall3d(74%)和pureSell(68-73%)
103. **TP0.5突破85%wr(R202)** — EMA+ATR=85.8%, Min3=85.1%, BOLL+ATR=83.1%. 低TP=高wr是单调关系
104. **TP0.25突破88%wr(R203)** — EMA+ATR=88.3%, Min3=87.9%, PSAR+BWB=86.7%. 所有4族达86%+
105. **TP0.12-0.18=89%wr plateau(R205)** — EMA+ATR 89.2%=all-time high. TP0.12-0.18所有值给出相同~89% wr. 低于此plateau不可能再提升
106. **TP0.1=54%wr cliff(R204)** — TP0.1低于slippage阈值(0.1%), 导致多数赢利交易净利润≈0而被计为亏损. 有趣的是score反而最高(0.855)但wr=54%不满足StdA+
107. **SL对wr无实质影响(R201)** — SL5=76.5%, SL10=80.7%, SL15=80%, SL20=82.4%, SL25=81%, SL30=81%. SL10-30区间wr差异<2pp
108. **Dual-sell降wr(R202)** — gt5dHigh+fall3d=76.2%(vs gt5dHigh alone=81.6%), gt5dHigh+rise2d=76.6%. 添加第二个卖出条件降低wr而非提升
109. **Longer MHD=higher wr(R199-R201)** — MHD3=68-79%, MHD5=74-82%, MHD10=80-86%, MHD15=87-89%, MHD20-30=87-89%saturate. MHD10以上wr饱和
110. **ATR对EMA族optimal=0.06, Min3=0.08(R201)** — noATR=invalid(结构性必需). ATR04=wr高但trades少/dd大. ATR10=ret最高(1003%)但wr略低(79%)
111. **gt10dH=最优卖出条件(R206-R209)** — gt10dHigh(close>10日最高)相比gt5dHigh: EMA+ATR TP1 ret从+568%→+620%(+9%), wr从75.5%→82.4%(+7pp). gt15dH/gt20dH与gt10dH完全相同(lookback在MHD10内饱和). gt10dH+TP1=return+wr最佳平衡
112. **rise2d=最高原始收益卖出(R210)** — 2日连涨卖出: EMA+ATR TP1 +635%(vs gt10dH +620%), Min3 TP2 +628%. rise3d=+584%/82.7%wr与gt10dH类似
113. **lt5dLow=最高score但wr不达标(R211)** — lt5dLow(close<5日最低卖出): Min3 TP5/MHD15 score=**0.854**(历史新高!)但wr=48.3%. lt3dLow: Min3 **+812%**(Min3历史最高!)但wr=59.1%. Score-WR disconnect是结构性的: lt5dLow exit高return+低dd=高score但低wr
114. **pctUp3=pctUp5=无效卖出(R212)** — 3-5%日涨幅在A股极罕见, pctUp卖出从不触发. 等同于纯MHD退出, EMA+ATR TP2/MHD10/pctUp3=**+680%**(EMA+ATR历史最高!)但wr=64.8%
115. **TP2是gt10dH下的return最优点(R206-R207)** — TP1/MHD10/gt10dH=+620% vs TP1.5=+609% vs TP2=+585%(gt10dH提前退出使TP>2无意义). 但TP999(无止盈)=+155%, gt10dH本身就是有效退出机制
116. **gt10dH+longer MHD boost Min3(R207)** — Min3 TP2/MHD10/gt10dH=+473%(vs gt5dH +372%, +27%!). gt7dH≈gt5dH, gt10dH才有显著提升
117. **batch-clone buy_conditions格式必须匹配source(R213 FAILURE)** — 使用field=EMA_12格式但source用field=EMA+params={period:12}→全部零交易. 正确格式: {"field":"EMA","params":{"period":12},"compare_type":"field","operator":">","compare_field":"EMA","compare_params":{"period":26}}
118. **ATR是收益旋钮(R214)** — ATR阈值从0.04→0.10: ret从+88%→+793%(9倍!), dd从6%→14%, wr恒定80-82%. noATR=信号爆炸(996信号/天). ATR控制"允许多少波动股进入"——越宽=越多交易=越多收益=越多风险. ATR不影响wr(买入质量不变)
119. **RSI>40是Min3最优阈值(R214)** — RSI40(0.820/+389%)>RSI45(0.820/+370%)>RSI50(baseline)>RSI55(0.807/+330%)>RSI60(0.804/+301%). noRSI(0.802/+336%)与RSI55持平, RSI并非关键. RSI>45有最低dd(7.1%)
120. **ATR0.10+lt5dLow+TP2=+1701%历史最高收益(R215)** — EMA+ATR ATR<0.10(宽波动过滤)+lt5dLow(反转卖出)+TP2: ret=+1701%, wr=67.5%, dd=13.5%, score=0.811, 3088笔交易. lt5dLow在宽ATR下效果爆发: 更多波动股进入→lt5dLow精准在反转前退出→极端复利效应. Sell×ATR交互是新的优化维度
121. **ATR0.09是score最优(R215)** — EMA+ATR gt10dH sell: ATR0.08(0.796/+775%)→ATR0.09(**0.802**/+901%)→ATR0.10(0.790/+793%). ATR0.08-0.10区间score差异<0.01, 广义sweet spot
122. **lt3dLow=终极卖出条件(R216)** — Min3 ATR0.10+lt3dLow+TP1=**+2651%**(全局最高!), EMA+ATR=+2283%. lt3dLow+TP2: score 0.822-0.823. ltNdLow ranking: **lt3d(+2283%)>lt5d(+1701%)>lt7d(+1404%)>lt10d(+912%)**. 更短lookback=更快卖出=更多复利. lt3dLow在TP1和TP2都通过StdA+ wr>60%
123. **Min3在ltNdLow sell下优于EMA+ATR(R216)** — Min3 lt3dLow +2651% vs EMA+ATR +2283%(+16%). Min3更多条件(MACD+RSI+MFI+ATR)提供更好的进场信号质量, 在高频交易中效果放大
124. **lt2dLow=新最高收益卖出(R217)** — EMA+ATR lt2dLow TP1=+2620.6%(StdA+, wr=66.7%), TP2=+2754.7%(非StdA+, wr=58.8%). lt2dLow在TP1时通过StdA+ wr门槛, TP2不通过. ltNdLow完整排名: **lt2d(+2621%)>lt3d(+2362%)>lt5d(+1701%)>lt7d(+1404%)>lt10d(+912%)**
125. **跨家族ltNdLow收益差异巨大(R217)** — lt3dLow TP1: EMA+ATR(+2362%)>>Min3(+731%)>>三指標(+559%)>>VPT+PSAR(+301%). EMA+ATR条件最少(2个)但ATR<0.10允许最多交易进入→复利最大化. 更多买入条件=更少交易=更低复利
126. **rise2d/rise3d卖出条件有效(R217)** — EMA+ATR TP1: rise2d=+642%(wr=80.2%), rise3d=+590%(wr=82.7%). rise系列wr最高(80-83%)但收益远低于ltNdLow系列. 适合追求高wr低风险的保守策略
127. **MHD对ltNdLow完全无效(R217,Min3确认)** — Min3 lt3dLow MHD5/7/10/15/20: ret=716-731%, wr=68.1-68.4%. R216已在EMA+ATR确认, R217在Min3也确认. ltNdLow卖出在MHD到期前触发, MHD=冗余参数
128. **ATR0.10是所有家族的MAX阈值(R217)** — Min3 ATR0.12/0.15全部INVALID(信号爆炸361-498信号/天). R214-R216在EMA+ATR确认, R217在Min3也确认. ATR>0.10=波动过滤失效
129. **numpy read-only bug修复启用consecutive sell(R217)** — `vectorized_signals.py` `_vec_consecutive`函数pandas CoW模式返回只读array, 添加`.copy()`修复. 修复后rise2d/rise3d/fall2d/fall3d等consecutive类卖出条件可正常使用
130. **VPT+PSAR和三指標家族均通过StdA+(R217)** — VPT+PSAR lt3dLow=+301%(wr=62.8%), gt10dHigh=+145%(wr=77.9%). 三指標 lt3dLow=+559%(wr=68.0%), gt10dHigh=+303%(wr=80.4%). 全部4家族均有StdA+策略, 证明卖出条件优化是通用的
131. **lt1dLow比lt2dLow更差(R218)** — EMA+ATR lt1dLow TP1=+657%(wr=60.0%) vs lt2dLow TP1=+2621%(wr=66.7%). lt1dLow(close<昨日low)触发过于频繁→过早退出→无法复利. ltNdLow最优lookback=2-3天, 非1天
132. **SL对ltNdLow策略至关重要(R218)** — EMA+ATR ATR0.10 lt2dLow: SL5=+966%(dd=21.1%,非StdA+)→SL7=+1349%→SL10=+2156%→SL12=+2454%→SL15=+2589%→SL20=+2621%. SL5→SL20=2.7倍收益差! ltNdLow持有期间经历回撤后恢复, 紧SL杀死恢复. 这与gt10dH(SL无关)完全相反
133. **Min3 ATR0.10+ltNdLow结构性dd>18%(R218)** — Min3 ATR0.10: lt2dLow SL10(dd=22%), SL15(dd=21%), SL20(dd=20.4%); lt1dLow(dd=19.8-26%). ATR0.10波动太大, Min3买入条件不够强来过滤. 最高收益+4668%但全部非StdA+
134. **Min3 ATR0.08是lt2dLow最优平衡点(R218)** — Min3 ATR0.08 lt2dLow SL20=+2539%(score=0.830, dd=12.1%, wr=66.1%). ATR0.07=+1423%(score=0.837, dd=8.6%), ATR0.09=+3446%(score=0.816, dd=16.5%). ATR0.07有最高score(0.837)但收益低, ATR0.08是最优tradeoff
135. **EMA+ATR ATR0.09是lt2dLow Pareto最优(R218)** — EMA+ATR ATR0.09 lt2dLow SL20=+2496%(score=0.822, dd=12.0%, wr=67.1%). 对比ATR0.10=+2621%(score=0.820, dd=12.5%). ATR0.09 score更高、dd更低、wr更高, 仅收益少5%
136. **ATR是收益-回撤线性旋钮(R218,全范围确认)** — 从ATR0.07到ATR0.10: 收益从+1040%→+2621%(2.5x), dd从16.2%→12.5%→12.0%→15.2%. ATR0.08-0.09是Pareto front, ATR0.10牺牲score换收益
137. **fall2d是保守高wr选择(R218)** — EMA+ATR ATR0.06 fall2d TP1=+591%(wr=72.4%), fall3d TP1=+551%(wr=80.3%). 收益远低于ltNdLow但wr高10-15pp. 适合风险厌恶者
138. **SL在ATR0.08下几乎不影响(R219)** — Min3 ATR0.08 lt2dLow: SL7=+1922%(score=0.820)→SL12=+2515%(0.832)→SL15=+2532%(0.831). SL7→SL15仅1.32x差异. 对比ATR0.10(SL5→SL20=2.7x). 低ATR=低波动=SL很少触发
139. **Min3 ATR0.08 fall2d=最佳平衡策略(R219)** — +1814%, wr=72.0%, score=0.826, dd=10.5%. 高wr+高收益+低dd的完美平衡. 优于gt10dH(+941%/wr=80.7%)在收益上, 优于lt2dLow(+2539%/wr=66.1%)在wr和dd上
140. **TP2对ltNdLow一致破坏wr(R219)** — EMA+ATR ATR0.09 lt2dLow TP2: score=0.834但wr=58.4%(非StdA+). Min3 ATR0.08 lt2dLow TP2: score=0.842但wr=57.8%(非StdA+). ltNdLow+TP2的score更高但永远过不了wr>60%门槛
141. **三指標 ATR0.10 lt3dLow dd>18%(R219)** — 与Min3 ATR0.10相同模式: dd=19.1%. ATR0.09=最佳(+1750%/dd=16.4%). 三指標收益低于EMA+ATR和Min3但三个ATR level都有StdA+策略
142. **跨家族lt2dLow ATR0.08-0.10完整矩阵(R218-R219)** — EMA+ATR: ATR08(+1637%/0.813)→ATR09(+2496%/0.822)→ATR10(+2621%/0.820). Min3: ATR08(+2539%/0.830)→ATR09(+3446%/0.816)→ATR10(dd>18%). 三指標: ATR08(+1637%/0.800)→ATR09(+1750%/0.801)→ATR10(+1894%/0.801). VPT+PSAR(no ATR): +328%/0.810
143. **TP0.5-1.5 sweet spot确认(R220)** — Min3 ATR0.08 lt2dLow: TP0.5=+2472%(wr=72.3%/0.820), TP0.8=+2535%(68.7%/0.824), TP1=+2539%(66.1%/0.830), TP1.5=+2683%(61.5%/0.837). TP从0.5→1.5: 收益单调增+wr单调减. 全部StdA+! TP0.5-0.8是wr>70%且收益>2400%的sweet spot
144. **MHD对lt2dLow在ATR0.08下也完全无效(R220)** — Min3 ATR0.08 lt2dLow: MHD3(+2594%)≈MHD5(+2615%)≈MHD10(+2539%)≈MHD15(+2539%)≈MHD20(+2539%). MHD3-20差异<3%, 确认ltNdLow sell在所有ATR level下都使MHD冗余
145. **Min3 ATR0.07 fall2d=最低dd策略(R220)** — +1045%, wr=72.3%, score=0.829, dd=**7.7%**. fall3d=+617%(wr=80.2%/dd=**7.1%**). ATR0.07的低波动+fall sell的早期退出=极低回撤. 对dd敏感的配置首选
146. **Min3 ATR0.09 sell矩阵(R220)** — fall2d(+2270%/wr72.1%/dd16.2%), fall3d(+1308%/wr79.4%/dd12.1%), gt10dH(+967%/wr80.3%/dd10.6%), rise2d(+1150%/wr78.5%/dd12.0%). ATR0.09的fall2d收益最高但dd=16.2%(接近18%极限)
147. **R220 100% StdA+率(R220)** — 24/24策略全部通过StdA+. 当优化空间在ATR0.07-0.09×{lt2dLow,lt3dLow,fall2d,fall3d,gt10dH,rise2d}范围内时, 几乎所有策略都是高质量的
148. **ATR0.091=真正的sweet spot, NOT 0.09(R278-R279)** — 4位小数精扫: ATR0.0895(0.8619)→0.09(0.8614)→0.0905(0.8621)→**0.091(0.8627)**→0.0915(0.8621)→0.092(0.8602). ATR0.091是尖峰最优, 两侧对称下降
149. **RSI 48-66=optimal买入范围(R275-R278)** — 比原始RSI 45-70更紧: 提升wr 3-4pp(从57%→60%+), 代价是减少~20%交易. RSI48(下界)过滤噪声, RSI66(上界)避免过热. RSI50-65太紧(少30%交易), RSI45-70太宽(wr<59%)
150. **TP1.36=StdA+ ceiling(R279)** — TP1.36(0.8628/wr=60.02%)通过StdA+, TP1.37(0.8632/wr=59.93%)差0.07%不通过. TP Pareto完整: TP1.30(0.8616/60.38%)→TP1.32(0.8622/60.34%)→TP1.34(0.8623/60.10%)→**TP1.36(0.8628/60.02%)**→TP1.37(fails)
151. **TP1.4在wr>60%结构性不可能(R276)** — 穷尽测试ATR0.092-0.096 × RSI48-66/50-65 × volume/MACD filters. TP1.4 wr最高59.8%(RSI48-67_ATR0.092), 0.2%短缺. 这是A股T+1市场的结构性上限
152. **SL和MHD对高score策略完全无影响(R277)** — RSI48-66 ATR0.092 TP1.35: SL15=SL20=SL25=相同score, MHD7=MHD10=MHD15=相同score. 在quad sell + TP1.35退出下, SL和MHD从不触发
153. **closeUp1d/volume spike等4th buy条件有害(R275-R276)** — closeUp1d使score降15点(0.860→0.845). Volume spike使wr降至56.1%. 额外买入条件增加噪声, RSI+ATR 2条件已是最优
154. **0.8628 StdA+ = 当前体系极限(R280确认)** — TP1.37在所有ATR(0.0912-0.092)下wr=59.73-59.99%, 永远过不了60%. RSI_7/RSI_10需DeepSeek(batch-clone无法使用source外指标), 是唯一可能的突破方向
155. **⚠️ CORRECTED(R292): Sells are CRITICAL, not decorative!** — 之前"sells decorative"结论是sell_conditions=[]bug的artifact。Python `or`将`[]`视为falsy, 所以nosell实际使用了source的quad sell。修复bug后真实对比: **nosell=0.8160(1828tr, wr80.3%) vs quad sell=0.8612(5866tr, wr60.2%)**。差距452分! Sell conditions是trade throughput enabler: 3.2x more trades, 更高总收益
156. **3sell_noLt extends TP ceiling to 1.43(R281-R284)** — 移除lt3dLow(亏损交易退出): TP1.37(0.8621/wr60.4%)→TP1.40(0.8619/60.1%)→TP1.43(0.8626/60.0%). 但score不超0.8628, 是一种不同的策略profile(更宽TP)
157. **3sell_noGt结构性无法达到wr>60%(R282)** — 移除gt3dH(盈利交易退出)保留lt3dLow(亏损退出): wr永远卡在58.9-59.1%. 已穷尽ATR/RSI/fall变体. lt3dLow本质上产生亏损交易拖低wr
158. **0.8656=最高raw score(R282)** — ATR0.0905 3sell_noGt: 0.8656但wr=58.9%. 比0.8628高0.0028但因wr<60%不是StdA+. 这证明score上限不在0.86, 而是wr>60%约束造成0.8628边界
159. **RSI远优于MACD用于buy信号(R289)** — RSI48-66+ATR0.091=0.8628, MACD>0+RSI+ATR=0.8575(-53点), MACD>0+ATR=0.8378(-250点). MACD作为4th条件有害, 单独使用更差. RSI在选择买入时机上本质优于MACD
160. **MACD变体全部不如RSI(R289)** — MACD>0=MACD_hist>0=MACD>signal: 都给0.837-0.839 at TP1.36. MACD rising 2d(0.842)略好但仍远低于RSI(0.8628). MACD的趋势跟踪不适合A股短线反转交易
161. **纯价格行为买入信号无效(R288)** — ATR+lt2dLow(0.656), ATR+consfall2(0.697), ATR+fall1d(0.684). 纯价格行为无法识别好的买入时机. RSI提供的'超卖反弹'信号是不可替代的
162. **RSI_7/RSI_10通过DeepSeek失败(R287)** — RSI_7: 7/8 invalid+1个0.624(wr=44.8%), RSI_10: 8/8全invalid. DeepSeek无法处理非标准RSI周期, batch-clone无法改变指标周期. RSI(14)是唯一可用周期
163. **⚠️ CORRECTED(R292): 0.8628被降级为0.8612** — 之前3-source确认的0.8628实际包含了source的quad sell(因bug)。真实score: RSI48-66+ATR0.091+quad sell=0.8612(两个source确认:ES22166/ES19213结果完全一致)。0.8628→0.8612的16分差可能是market data更新
164. **Source-dependency RESOLVED(R292)** — ES22166和ES19213作为source给完全相同结果(nosell=0.8160, quadsell=0.8612). 之前E4367的discrepancy不是source bug, 而是sell_conditions bug的表现
165. **Sell优化空间巨大(R292)** — nosell(0.8160)和quad sell(0.8612)之间有452分差距。更好的sell组合可能突破0.87+。重点方向: sell threshold调优, 新sell类型(volume/RSI extreme/ATR trailing), sell数量优化
166. **fall_pct alone ≈ quad sell(R292)** — fall_pct(-0.35)单卖出=0.8610, 接近quad sell(0.8612). gt/lt lookback条件几乎无效(adds <0.003). fall_pct是唯一真正有效的卖出trigger
167. **Wider fall + higher TP = higher score(R293-R298)** — f55r4_TP155=0.8628→f60r4_TP165=0.8638→f65_cGTl25_r4d_TP170=0.8647. 更宽fall阈值+更高TP持续推进frontier, 但wr>60%是hard constraint
168. **rise4d > rise3d > rise2d for sell(R297)** — 更长连涨要求=更少误卖=更高wr. rise4d是最优balance, rise5d/6d无额外收益
169. **MACD>0 buy filter HURTS score(R301)** — MACD+RSI+ATR=0.8586 vs RSI+ATR=0.8638(-52点). MACD过滤掉了盈利性超卖反弹交易. RSI+ATR=唯一最优buy
170. **RSI overbought sells无效(R302)** — RSI>65-80作为sell: score仅0.81, trades~1750. RSI在持仓期间极少达到高值, sell signal太少
171. **close>low pct_diff = 新卖出范式(R303-R304)** — close>low 2.5%("日内反转卖出"): 添加到f65+r4d给出0.8647, 超越纯f60r4=0.8638. 日内从低点强力反弹=局部高点信号
172. **high>close pct_diff = 最高raw score但wr太低(R304)** — f55+hGTc15+r4d=0.8683(历史最高raw score)但wr=58.0%. 上影线拒绝信号太激进
173. **Buy-side已穷尽(R303)** — RSI范围(46-70)和ATR范围(0.088-0.095)全面扫描, RSI48-66+ATR0.091始终最优. 任何变化都降低score
174. **MHD在sell条件下完全irrelevant(R293)** — MHD5=MHD7=MHD15=MHD20 完全一致. 高效sells使positions在MHD前退出
175. **SL在sell条件下near-irrelevant(R296)** — SL15/20/30给相同score, 仅SL10微降. 好的sell条件使SL极少触发
176. **2-sell < 3-sell(R306)** — f65_cGTl25 alone=0.8639 vs f65_cGTl25_r4d=0.8647. rise4d adds +0.0008 by enabling higher TP. 3 sells is the optimal count
177. **Multi-day pct_change sells = moderate but not frontier(R300)** — drop2d_-1.0%=0.8548/wr64%, drop2d_-1.5%=0.8479/wr68%. 合理但远离frontier
178. **fall_consecutive sells kill wr(R300)** — fall2d+fall_pct combos: 0.8670 raw但wr=57-58%. 太多激进sell triggers
198. **ANY sell produces StdA+ with RSI+ATR buy base(R362-R382)** — Decline sells(falling_nd, fall_pct), value threshold sells(RSI>55, ATR<0.05), volume sells(vol_surge, vol_drop), lookback sells, contradictory combos(ATRfall2+ATRrise2) ALL achieve 80%+ StdA+ rate across 200 strategies. Buy base SO strong that sells are throughput regulators, not quality filters
199. **ATRrise2+volF2 MHD5 TP2.0 = ALL-TIME StdA+ 0.8662(R348)** — Sell when ATR rising 2 consecutive days + volume falling 2 days. New record family. MHD5 optimal for indicator-based sells vs MHD10 for price-based
200. **Contradictory OR sell combos valid(R354)** — ATRfall2+ATRrise2 = 0.8668 raw. Logically contradictory conditions in OR mode simply maximize trade throughput. ALL non-mutually-exclusive sell combos produce StdA+
201. **volRise2d/RSIrise2d/ATRfall2d = ALL new valid sell types(R371)** — Every indicator rising/falling N days as sell condition produces StdA+. volRise2=0.8600, RSIrise2=0.8533, ATRfall2=0.8466. Indicator direction sells are a rich unexplored space
202. **Value threshold sells valid but not frontier(R377-R379)** — RSI_gt55=0.8413, ATR_lt0.05=0.8466. Value-based sells work but score lower than consecutive/lookback sells. All produce StdA+ due to strong buy base
203. **TRIPLE sells = 0.8704 NEW ALL-TIME raw score(R383)** — ATRrise2+volFall2+RSIfall2 TP2.5 MHD5. 3个indicator-direction sells in OR mode产生最多trade signals(4848 trades)=最高total return. 但wr=56.3%❌, 结构性无法达到wr>60%. More sells = higher score + lower wr
204. **ATRrise2+volFall2 TP×MHD grid fully mapped(R383)** — 15 configs完整mapping: MHD3给最高score(TP2.0=0.8662), MHD7给最高wr(TP1.5=63.5%). TP2.2 MHD7=0.8654✅ extends TP frontier. 0.8662确认为StdA+ ceiling
205. **3d lookback = ultra-safe variant(R383)** — ATRrise3d+volFall3d: 9/10 StdA+, wr up to 68.5%(ATRr3only). Longer consecutive requirement = fewer signals = higher wr, lower score. ATRr3+vF3 best=0.8588
206. **pct_change sells = 100% StdA+ rate(R383)** — RSI/ATR pct_change as sell: ALL 10/10 StdA+! RSIpct5 MHD3=0.8473(wr67.6%), ATRpct20 MHD5=0.8300(wr72.3%=最高wr). Very rare signals = ultra-high wr but lower scores
207. **NVI confirmed 已弃(R383)** — 5 DeepSeek experiments: 19/24 invalid, 0 StdA+, best=0.6972. NVI不适合A股短线策略
208. **Score-wr fundamental tradeoff fully quantified(R383)** — More sell signals linearly trade score for wr: Triple(0.87/56%)→Dual(0.866/60%)→3d(0.86/65%)→pctChange(0.84/70%). 这是A股T+1市场的结构性约束
179. **ATR>0.05 as sell = highest raw score EVER 0.8680(R307)** — ATR超过阈值就卖出: ATR>0.05=0.8680(wr56.8%❌), ATR>0.06=0.8668(wr57.5%❌), ATR>0.07=0.8663(wr58.2%❌). Raw score比任何组合都高, 但wr catastrophically low. ATR作为sell太频繁触发
180. **ATR>0.10+ is a no-op sell(R308)** — 因为buy条件要求ATR<0.091, 持仓期间ATR几乎不可能飙到0.10+. ATR sell仅在0.05-0.09有效范围, 且全部fail wr
181. **rally4d4pct = NEW ALL-TIME BEST StdA+ 0.8651(R309)** — fall(-0.65)+rally_nd(4,4.0)+rise_nd(4) TP1.70 = ES23218. 4日涨幅>4%作为卖出信号, 捕获multi-day momentum breakout. +0.0003 over previous best(0.8648). rally4d > cGTl25 for sell
182. **rally5d5pct = 0.8653 but wr=59.9%❌(R309)** — 5日涨5%score更高但wr差0.1%不通过StdA+. rally4d4pct是最优balance(wr=60.2%). rally3d3pct(0.8649❌wr59.9%)也不通过
183. **close>open (bullish candle) sell = 0.8643✅(R307)** — 阳线卖出新范式, 有效但不如rally4d. open>close(阴线)=0.8651❌wr59.5%
184. **Volume spike sell = no-op(R308)** — volume>volume_ma_5在持仓期间几乎always true, 无过滤效果
185. **KDJ buys = ZERO StdA+, 200pts inferior(R309)** — KDJ(9,3,3)+RSI(7)+ATR源策略: best=0.8445(wr59.0%). KDJ oversold(K<15-40)=catastrophic(0.46-0.76). RSI在买入timing上本质优于KDJ
186. **BOLL buy filter = terrible(R311)** — BOLL_middle buy: 0.79-0.80 range(wr51-53%). ROC>0 buy: 0.8511(wr59.4%). 非RSI买入信号全部劣于RSI
187. **PSAR sells hurt wr(R311)** — close<PSAR添加500-700 extra trades但drop wr to 57-59%. PSAR-only sell: 0.8396(wr67.5%, high wr but low score). PSAR不适合作为sell trigger
188. **Price-action buys = ZERO StdA+(R312)** — consecutive falling: 0.53-0.69(catastrophic), dip buys(lt3dL): 0.6152, near-low: 0.8572(wr58.8%), breakout(gt5dH): 0.8054. 纯价格行为无法替代RSI
189. **No-ATR buys = ALL INVALID(R313)** — 6 configs without ATR filter全部signal explosion. ATR is ESSENTIAL for preventing signal explosion, not just helpful
190. **0.8651 = confirmed ceiling from EVERY angle(R307-R313)** — 7 rounds, 187 strategies, tested every available sell type(ATR/PSAR/BOLL/volume/lookback/rally/candle/KDJ) and every buy alternative(KDJ/BOLL/PSAR/ROC/price-action/no-ATR). ALL equal or inferior. RSI48-66+ATR0.091+rally4d4pct=the optimum
191. **f40+rally4d = 0.8684 NEW highest raw score(R314)** — fall(-0.40)+rally4d(4.0)+rise4d: surpasses ATR sell's 0.8680. But wr=57.9%❌. f40 at ANY TP (1.40-1.65) never reaches wr>60%
192. **Fall threshold -0.55 to -0.60 = structural wr>60% boundary(R315)** — Exhaustive sweep: f40 max wr=59.6%, f45 max wr=59.6%, f50 max wr=59.9%. Only f55+ can achieve wr>60%. This is a structural market property, not a parameter tuning issue
193. **oGTc sell paradigm works but doesn't beat baseline(R314-R315)** — open>close pct_diff (bearish candle body). oGTc(0.3)+f50=0.8608✅, oGTc(0.5)+f50=0.8595✅. Novel sell type but doesn't improve over rally4d
194. **ATR decrease sell(ATR<0.06) = novel valid paradigm(R314)** — "volatility compression" sell at 0.8436✅(wr65.7%). When ATR drops during hold, trend may be ending. Novel concept but far from frontier
195. **ATR range buy(ATR>0.03-0.05) doesn't help(R315)** — Adding ATR lower bound to buy conditions doesn't improve score. ATR<0.091 alone is sufficient
196. **f55-f60 structurally fail wr>60%(R316)** — Exhaustive sweep f55×TP1.55-1.72, f57×TP1.68-1.72, f58×TP1.68-1.72, f60×TP1.68-1.72. ALL wr=59.1-59.9%. Only f62 TP168=0.8647(wr60.1%✅) and f55 TP155=0.8638(wr60.2%✅) barely pass. f65 TP170=0.8651(wr60.2%) is the mathematical optimum
197. **Fall-TP gradient precisely mapped(R314-R316)** — f40(max_wr=59.6%), f45(59.6%), f50(59.9%), f55(60.2%@TP155), f57(59.7%), f60(59.8%), f62(60.1%@TP168), **f65(60.2%@TP170=0.8651 CEILING)**. The boundary is between f60 and f62. Each -0.05% wider fall = ~0.1-0.2% higher wr but -0.002 lower score

209. **非Portfolio模式 score膨胀~5%(R527)** — S16130(0.8662 StdA+ all-time)在portfolio模式(max10pos, 30%cap)下仅0.8209(wr=58.7%, 非StdA+). 非portfolio模式允许无限持仓+100%仓位, 膨胀score. 所有之前的0.86+策略都是非portfolio模式下的结果
210. **RSI(14) lb50 > RSI(18) lb44 in portfolio mode(R527)** — 中性区RSI(48-66)>超卖区RSI(44-80). RSI14 lb50 ub66 ATR<0.091 aR2vF2 TP1.5 MHD3 = **0.8197 portfolio-mode champion**(wr=61.0%, dd=9.1%). RSI14有更快响应, lb50过滤噪声
211. **低ATR+低TP = 超低风险策略(R527)** — ATR0.06-0.07 + TP1.0-1.2: DD=8.8-9.7%, wr=60.9-65.7%. 通过限制波动股+快速止盈实现极低回撤. 代价是总交易数和收益较低
212. **4th buy条件一律有害(R527)** — KDJ/MACD/PSAR作为第4买入条件均降低score. RSI+ATR 2条件已是portfolio模式下的最优买入
213. **BOLL_pband是正确field名(非BOLL_pctb)** — resolve_column_name映射: BOLL_pband_20_2, 范围(0,1). 但BOLL%B作为买入信号wr仅53-55%, 不competitive
214. **aR2vF2是最优双sell(R527)** — aR2only=0.7923, vF2only=0.7990, aR2vF2=0.8197, noSell=0.7600. 双sell显著优于单sell, 两者协同效果大于各自之和
215. **lb51是score landscape的局部最小值(R527)** — RSI lb sweep: lb49=0.8189, lb50=0.8197(peak), **lb51=0.7971(valley!)**, lb52=0.8053. lb51比相邻值低220点, 原因不明
216. **ATR0.0912是portfolio最优阈值(R528)** — 4位小数精扫: ATR0.09(0.8268/wr59.96%❌)→ATR0.0912(**0.8331**/wr60.41%✅)→ATR0.092(0.8310/✅)→ATR0.095(0.8148)→ATR0.10(0.8141). ATR0.0912是sharp peak, 两侧快速衰减
217. **TP1.63=portfolio StdA+ ceiling(R528)** — TP1.63(0.8331/wr60.4%)✅, TP1.68(0.8322/wr60.0%)✅, TP1.70(fails wr59.9%). TP1.63-1.68是viable range, TP>1.70结构性无法wr>60%
218. **KDJ/MACD/BOLL/STOCHRSI/CCI买入在portfolio模式ALL FAIL(R528)** — KDJ(0/39 StdA+, best 0.6866), MACD(0/10, best 0.7705), BOLL(0/6, best 0.8250/wr59.4%), STOCHRSI(0/28, ALL<50 trades), CCI(0/3, best 0.7693). RSI是portfolio模式下唯一viable买入指标
219. **RSI14是最优RSI周期(R528)** — RSI7(0/5 StdA+, wr consistently 59.5-59.8%), RSI10(3 StdA+, best 0.8260), RSI21(1 StdA+, best 0.8023). RSI14(0.8331) > RSI10(0.8260) > RSI21(0.8023) > RSI7(0.8262/fails wr)
220. **ATR周期对sell无影响(R528)** — sell ATR{7,14,21,28}全给近似score(0.8239-0.8288). ATR14 buy + ATR14 sell remains optimal, 但cross-period combos全部StdA+
221. **Ultra-low TP(0.3-1.2)可达wr>80%(R528)** — noSell TP0.3 MHD3=wr**80.5%**(score 0.7267), aR2vF2 TP0.3 MHD2=wr73.0%(0.7795). TP0.8-1.2+aR2vF2有9个StdA+(wr61-63%, score0.80-0.81). TP-wr tradeoff: TP↓→wr↑ but score↓
222. **max_position_pct完全irrelevant(R528)** — pos10: pct15=pct20=pct30=pct50=0.8288(identical). max_pct only matters if < 100/max_positions
223. **max_positions=10是最优(R528)** — pos3(0.7306/dd17.5%), pos5(0.7911), pos8(0.8197), **pos10(0.8288)**, pos15(0.8202/wr59.8%), pos20(0.7989). 倒U型: pos<10太集中, pos>10过度分散降wr
224. **Slippage极度敏感(R528)** — 0%slip(0.8382), 0.05%(0.8419), **0.1%(0.8288)**, 0.15%(0.8000❌), 0.2%(0.7569), 0.3%(0.6696). 0.15%即跌破StdA+! 实盘执行质量至关重要
225. **Initial capital完全irrelevant(R528)** — 50k/100k/200k/500k/1M all produce 0.8288. Portfolio engine normalizes by percentage
226. **pct_change NOT bugged, portfolio saturation(R528P)** — 代码正确! 小阈值(0.01-0.5%)结果相同是因为max10pos下5000个→4800个信号不改变选中的10只股. 需>3%阈值才能区分. pctChg>3%=sc0.8089但wr58.5%
227. **4th buy conditions一律有害(R528 portfolio确认)** — lookback_min/max, consecutive rising, pct_change, BOLL_pband, KAMA, CCI, ULCER, KELTNER, close>EMA/MA all either reduce score or produce 0 trades
232. **🆕 ATRcalm7d是新StdA+方向(R1108-R1115)** — ATR14的7日pct_change<3%(ATR不增幅超3%)作为买入条件，在Core5+ATRcalm7d下，93%策略达StdA+(14/15)。ATRcalm = "压缩弹簧"：低波动期买入，ATR平静意味着即将爆发。关键: wr从55%→61-71%，大幅提升。
233. **🆕 lt2dLow sell + ATRcalm7d = 2404% return (R1114)** — Core6(RSI47-67+ATR0.12+AbvMin13+BelMax10+ATRcalm7d) + lt2dLow卖出 + MHD3 + TP2.5 + SL20 = score=0.8575，ret=**2404%**。lt2dLow卖出在ATRcalm期买入后捕捉实际下破2日低点的下跌，TP2.5捕捉完整反弹。
234. **🆕 TP2.5+MHD3 for lt2dLow sell formula (R1114 vs R1117)** — 比较: TP2.5 MHD3 = 2404%, TP0.8 MHD5 = 1843%, TP4.0 MHD10 = 800%。高TP+短MHD捕捉完整反弹，低TP只取小利。ATRcalm方向的最优出口: TP2.5-3.0，MHD3-5。
235. **🆕 RSI47-67 for ATRcalm formula (R1113 vs R1118)** — RSI47-67(2404%) > RSI50-70(1386%) > RSI42-62(828%) > RSI52-72(793%)。RSI47-67中区(偏低不超买)是ATRcalm的最优买入范围。
236. **🆕 SL不影响ATRcalm策略(R1119)** — SL10/15/20/25/30均达StdA+(36/36)，wr=62%。ATRcalm期间止损几乎不触发，SL设置不关键。wr稍高的SL=30(wr=62.1%)比SL=20(wr~52%)高，说明ATRcalm买入时宽SL允许价格短期波动。
228. **🆕 DIP-BUY = 新StdA+策略家族(R528P-R)** — "买恐慌"而非"买动量". RSI50-70+ATR<0.09+close日跌>2.5-3%+aR2vF2卖出. 特点: **dd仅4.0-5.8%**(全StdA+最低!), wr=60-64%, sc=0.80-0.83. 最佳: **dip-3.0% ATR0.09 TP2.0 MHD5 = sc0.8347 wr61.8% dd4.2%**
229. **DIP-BUY最优参数(R528R)**: ATR0.09(非0.0912), RSI50-70(非50-66), dip-2.5~-3.0%(sweet spot). TP可达2.0(-3%时wr61.8%), TP2.0~3.0 at -2.5%需wr<60%. vF2_only也能StdA+(sc0.8154 wr60.7%)
230. **Volume pctChg>1%+RSI52-66 = StdA+(R528P)** — TP1.3-1.5区间全部StdA+. 最佳: RSI52-66 vol>1.0 TP1.5 = sc0.8200 wr60.3% dd7.6%. Volume momentum作为4th buy是唯一有效的正向过滤
231. **DIP-BUY + volume组合过于restrictive(R528Q)** — dip-2%+vol>0.5 = tr1077, sc0.6992. 两个pct_change买入过滤叠加使交易数骤降, 不如单独使用

---

## 探索状态

> 528轮探索已完全穷尽所有可用方向。以下为关键方向摘要。Portfolio模式(R527-R528)发现非portfolio score有~5%膨胀。R528 portfolio-mode参数空间已FULLY EXHAUSTED: 买入指标(RSI/KDJ/MACD/BOLL/STOCHRSI/CCI/KAMA/Volume/EMA/close>MA), 卖出类型(aR2vF2/lt2dLow/ATRrise3/noSell/triple), TP(0.3-3.0), MHD(1-10), SL(5-99), ATR周期(7/10/14/21/28), RSI周期(7/10/14/21), portfolio sizing(pos3-20, pct15-50), capital(50k-1M), slippage(0-0.3%).

### 有效方向 (已穷尽)

| 方向 | 最佳Score | 关键发现 |
|------|-----------|----------|
| **RSI+ATR买入基底** | 0.8662(non-port) / **0.8331(portfolio)** | RSI 50-66 + ATR14<0.0912 = 唯一最优买入条件. Portfolio: TP1.63 MHD3 pos10. RSI14>RSI10>RSI21>RSI7 |
| **ATRrise2+volFall2 卖出** | 0.8662 StdA+ | 波动扩张+成交量萎缩 = 最佳卖出信号 |
| **RSIfall2d 卖出** | 0.8651 StdA+ | RSI 2日连跌 = 经典反转卖出 |
| **rally4d4pct 卖出** | 0.8651 StdA+ | 4日涨4% = 动量突破卖出 |
| **落日卖出(fall_pct)** | 0.8647 StdA+ | close下跌-0.65%触发卖出 |
| **Sell 3-Tier Model** | — | Tier1(永不触发), Tier2(每天触发), Tier3(选择性) |
| **PSAR+MACD+KDJ** | 0.830 | PSAR趋势+MACD动量+KDJ超卖三维组合 |
| **全指标综合** | 0.825 | 全指标组合, T+1 Top 1 |
| **EMA+ATR** | 0.823 | 2条件极简策略, lt2dLow sell = +2621% |
| **Min3(MACD+RSI+ATR)** | 0.830 | 3条件版, lt2dLow = +2539% |
| **三指標共振** | 0.817 | close_fall2d跨族有效 |
| **VPT+PSAR** | 0.810 | VPT+PSAR+BWB三重过滤 |

### 已弃指标 (52个方向)

> 以下指标/组合经多轮测试确认在A股T+1市场无效: CMF, MA, EMA(独立), OBV, NVI, VPT(独立), Donchian, Aroon, Ichimoku, KST, MASS, TSI, Vortex, WMA, TRIX, DPO, PPO, PVO, AO, FI, EMV, ADI, STC, MFI, WR, ROC, STOCH+KDJ叠加, ULTOSC+KDJ叠加, 纯价格行为买入, KDJ超卖买入, BOLL买入过滤, MACD买入过滤, ADX趋势过滤

### 已穷尽参数空间

| 参数维度 | 测试范围 | 结论 |
|----------|----------|------|
| **SL** | SL3-SL99 | SL≥12完全irrelevant, SL99≥SL12 |
| **TP** | TP0.12-TP7.0 | StdA+ ceiling = TP2.0, TP0.12-0.18=89%wr |
| **MHD** | MHD1-MHD30 | MHD3-5最优, MHD≥8后无提升 |
| **买入条件** | RSI(7/10/14/21), ATR(0.04-0.15), +MACD/KDJ/BOLL/PSAR/STOCHRSI/CCI/KAMA/Volume/EMA/close>MA | RSI48-66+ATR0.091=唯一最优. Portfolio: RSI50-66+ATR0.0912 |
| **卖出条件** | 全indicator×rising/falling×2-5d + threshold + pct_change + pct_diff + lookback_min/max | Sell 3-Tier Model, 所有类型已测试 |
| **卖出组合** | 双/三卖出, Tier2+Tier3, 矛盾OR组合 | Tier2+Tier3=Tier3, 双卖出<单卖出 |
| **Portfolio** | pos3-20, pct15-50, capital 50k-1M, slippage 0-0.3% | pos10最优, pct/capital irrelevant, slip>0.15%破坏StdA+ |

---

## Auto-Promote 记录

> 累计 **20,650+** 个StdA+策略已promote。
> **R1281** (Engine, 2026-04-21 09:09): **246 StdA+ (95.7%)** — best=0.8643, promoted=241, provider=code-driven。Pool: 24家族, 262活跃

---

## 最佳策略 Top 15 (T+1引擎, 跨所有实验)

| # | 策略名 | 评分 | 收益 | 回撤 | 交易数 | 备注 |
|---|--------|------|------|------|--------|------|
| 1 | **全指标综合_中性版C SL9/TP14/MHD15 (S342/S207)** | **0.825** | +101.2% | 12.8% | 612 | **T+1 ALL-TIME SCORE** |
| 2 | **全指标综合_中性版C SL8/TP14 (S162/S245)** | **0.824** | +101.6% | 13.3% | 617 | |
| 3 | **全指标综合_中性版C SL10/TP14/MHD15 (S330/S247)** | **0.824** | +99.3% | 12.8% | 612 | |
| 4 | **全指标综合_中性版C SL15/TP14/MHD15 (S1042)** | **0.823** | +99.4% | 12.7% | 609 | |
| 5 | **全指标综合_中性版C SL9/TP10 (S810)** | **0.823** | +116.0% | 13.0% | 675 | |
| 6 | **全指标综合_中性版C SL8/TP10 (S811)** | **0.823** | +115.7% | 13.0% | 682 | |
| 7 | **全指标综合_中性版C SL7/TP14 (S99)** | **0.822** | +98.5% | 13.0% | 621 | |
| 8 | **PSAR趋势动量 SL14/TP6/MHD30 (S436)** | **0.816** | +173.9% | 9.4% | 1343 | PSAR族冠军 |
| 9 | **三指标共振 SL10/TP1/MHD3 (S1975)** | **0.808** | +188.1% | 12.8% | 1970 | 三指标族冠军 |
| 10 | **MACD+RSI SL12/TP3/MHD3 (S1850)** | **0.801** | +170.5% | 13.0% | 1544 | MACD+RSI冠军 |
| 11 | **三指标共振 SL12/TP2/MHD10 (S1300)** | **0.793** | **+192.5%** | 13.4% | 1855 | **T+1最高收益** |
| 12 | **KAMA突破_保守版G (top)** | **0.772** | +131.0% | — | — | KAMA族冠军 |
| 13 | **全指标综合_保守版B (top)** | **0.765** | +34.3% | — | — | 100%存活率 |
| 14 | **KAMA突破 (top)** | **0.761** | +145.0% | — | — | |
| 15 | **UltimateOsc SL8/TP3/MHD1 (S1868)** | **0.717** | +28.8% | **2.2%** | 304 | **最低回撤** |

---

## 全阶段盈利策略 (牛+熊+震荡都赚钱)

| 策略名 | 总收益 | 评分 | 实验来源 |
|--------|--------|------|---------|
| KDJ金叉_中性版A | **+37.1%** | 0.70 | 第三轮 |
| KDJ金叉_激进版B | +31.5% | 0.70 | 第三轮 |
| KDJ超短线_中性版A | +25.9% | 0.69 | 第四轮 |
| KDJ短周期快速交易_保守版A | +21.5% | 0.69 | 第四轮 |
| KDJ低位金叉+均线多头排列_中性版C | +12.7% | 0.65 | 第四轮 |
| **PSAR趋势动量_保守版A** | **+70.8%** | **0.77** | **第十二轮(PSAR+MACD+KDJ, 全阶段盈利!)** |
| **PSAR三重确认_中性版B** | **+14.5%** | **0.69** | **第十二轮(PSAR+ULCER+KDJ)** |
| PSAR三重确认_中性版C | +27.4% | 0.61 | 第十二轮 |
| **PSAR+BOLL+KDJ_保守版B** | **+27.5%** | **0.70** | **第十三轮(PSAR+BOLL+KDJ, dd仅8.2%)** |
| PSAR+BOLL+KDJ_保守版C | +9.7% | 0.67 | 第十三轮(dd仅2.4%,极稳) |

> 共同特征: 全部为短线/超短线, 持仓时间短、换手快。PSAR三维组合是全阶段盈利策略的主要来源。

---

## 各市场阶段最优 (Top 3)

### 牛市 (87% KDJ策略盈利)

| 策略名 | 牛市盈亏 | 牛市胜率 | 总收益 |
|--------|---------|---------|--------|
| KDJ+ATR动态止损_中性版C | +686元 | 53.3% | +1.2% |
| KDJ+EMA短线趋势_中性版B | +568元 | 59.8% | +14.8% |
| KDJ中周期趋势_中性版C | +561元 | 45.9% | +60.7% |

### 熊市 (仅26%策略盈利)

| 策略名 | 熊市盈亏 | 熊市胜率 | 总收益 |
|--------|---------|---------|--------|
| KDJ金叉+MACD双金叉_中性版A | +368元 | 45.0% | +34.1% |
| KDJ金叉_激进版A | +246元 | 44.6% | +13.9% |
| KDJ+ATR动态止损_中性版B | +228元 | 52.9% | +22.2% |

### 震荡市 (仅4%策略盈利 — 最大瓶颈)

| 策略名 | 震荡盈亏 | 震荡胜率 | 总收益 |
|--------|---------|---------|--------|
| KDJ金叉_中性版A | +195元 | 47.1% | +37.1% |
| KDJ短周期快速交易_激进版A | +127元 | 47.4% | +14.7% |
| KDJ短周期快速交易_保守版A | +70元 | 53.6% | +21.5% |

---

## 扩展指标表现

### 原有扩展指标 (P0修复后)

| 指标 | 策略数 | 盈利率 | 最佳收益 |
|------|--------|--------|----------|
| VWAP | 20 | **30.0%** | +29.1% |
| CMF | 19 | **21.1%** | +29.1% |
| ROC | 24 | 16.7% | +28.2% |
| BOLL_lower | 61 | 14.8% | +59.0% |
| WR | 29 | 13.8% | +19.2% |
| CCI | 68 | 13.2% | +58.5% |
| MFI | 56 | 12.5% | +59.0% |
| BOLL_middle | 49 | 12.2% | +58.5% |
| BOLL_upper | 45 | 8.9% | +14.6% |
| TRIX | 32 | 6.2% | +10.8% |
| DPO | 28 | **0.0%** | -0.1% |

### 第十轮新指标 (33个TA-lib新增指标, 全部完成)

| 指标 | 策略数(done) | 盈利率 | 最佳收益 | 备注 |
|------|--------|--------|----------|------|
| **ULTOSC** | 14 | **21.4%** | **+28.0%** | **ID129: 3/6盈利(50%!), 中性版C score 0.72 Standard A!** ID148超卖版0盈利 |
| **ULCER** | 8 | **37.5%** | +19.5% | ULCER<5过滤下行风险, 与KDJ/ATR组合效果好 |
| **PSAR** | 8 | **37.5%** | +14.3% | PSAR+多指标组合Standard A, 震荡市罕见盈利 |
| **STOCH** | 10 | **30.0%** | +28.4% | ID128: 2/4盈利(50%); ID146: 1/6盈利. 类似KDJ |
| **StochRSI** | 8 | **12.5%** | +37.9% | BOLL%B+StochRSI Standard A, 最佳新发现 |
| **KAMA** | 463 | **84%** | **+389.4%** | **R31-R32: 371 StdA+, score 0.831(ALL-TIME RECORD!), 第二大超级家族** |
| **NVI** | 11 | 9% | +55.8% | R32: 1/11 StdA+, 浅探索, 值得grid search |
| VPT | 21 | 0% | +23.5% | R32: 0/21 StdA+, OBV改进版无效, 已弃 |
| STC | 17 | 6% | +59.5% | ID147+R32: STC+KDJ组合也无增益, dd偏高 |
| FI(力量指标) | 1 | 0% | -34.8% | ID132: 仅1done全亏, 大部分invalid |
| MASS | 8 | 0% | -3.5% | MASS反转凸起在A股无效 |
| PVO | 8 | 0% | -8.9% | 量价震荡无效 |
| ADI | 8 | 0% | -8.9% | 累积派发无效 |
| AROON | 8+ | 0% | — | 信号爆炸或0盈利 |
| TSI | 8 | 0% | -12.5% | TSI阈值难设, 几乎always true |
| DONCHIAN | 16 | 0% | -7.8% | 海龟交易法在A股失效 |
| AO | 6 | 0% | -6.5% | 动量震荡无效 |
| PPO | 4 | 0% | -84.0% | PPO+TSI组合灾难性亏损 |
| KST | 0 | — | — | 全部invalid, 指标不可用 |
| WMA | 0 | — | — | 全部invalid |
| ICHIMOKU | 8 | 0% | — | 信号爆炸, 条件太宽松 |
| VORTEX | — | — | — | DeepSeek无法生成, 2次尝试均失败 |
| EMV | 6 | 0% | -30.2% | FI+EMV组合全亏 |

---


## 历史实验摘要 (归档)

> 1281轮探索累计: ~7362个实验, ~9484个StdA+策略。详细轮次数据查询API: `GET /api/lab/exploration-rounds`。
>
> **发展阶段**: R1-R10(基础指标探索)→R11-R30(PSAR/KAMA/VPT发现)→R31-R50(T+1引擎+大规模grid search)→R55-R220(卖出条件优化+ATR旋钮)→R275-R320(RSI+ATR micro-tuning, 0.8662 ceiling)→R350-R526(完全参数穷尽)→R527-R570(ALL-TIME 0.8712)→R1108-R1207(Alpha因子+多时间框架扩展, 78个家族, 1215活跃策略)

## 已知问题

| 编号 | 问题 | 状态 |
|------|------|------|
| P0 | 扩展指标收集bug | 已修复 2026-02-13 |
| P1 | 评分体系区分度 | 已修复 2026-02-12 |
| P2 | 策略生成多样性 | 已修复 2026-02-12 |
| P3 | 止损穿越 | 已修复 2026-02-12 |
| P4 | 零交易~50% | **已修复** 2026-02-16 — 快速预扫描: 200股×250天检测买入信号(原100×60对稀有信号策略误判). 零信号直接标invalid(~3s vs 5min) |
| P5 | DeepSeek prompt bug | 已修复 2026-02-12 |
| P6 | 数据完整性 | 已修复+验证 2026-02-12 |
| P17 | 组合策略 | **已实现** 2026-02-15 — combo策略类型, 投票机制, AI Lab实验验证成功 |
| P18 | 组合策略回测慢 | **已优化** 2026-02-16 — 投票短路评估: 达到阈值后跳过剩余成员(买入+卖出) |
| P19 | 条件可达性预检 | **已实现** 2026-02-15 — check_reachability()检测矛盾+超范围, 集成AI Lab |
| P20 | 规则引擎P4升级 | **已完成** 2026-02-15 — 6种新compare_type + 条件预检 + validate增强 + DeepSeek prompt |
| P21 | DeepSeek不使用新条件类型 | **已修复** 2026-02-16 — 添加完整few-shot示例(lookback_min+pct_change) + 关键词触发强制指令 |
| P22 | DeepSeek field比较指令导致90%+ invalid | **已修复** 2026-02-16 — 三层修复: 1)自动交换反转的field/compare_field, 2)自动填充缺失的compare_params默认值, 3)prompt固定模板 |
| P23 | PSAR探索已穷尽 | 完成 2026-02-16 — PSAR+{MACD,RSI,BOLL,EMA,CCI,ULCER}+KDJ全部系统探索. 有效: MACD(★★★), BOLL(★★), RSI(★), ULCER(★). 无效: EMA, CCI. 下一步: 手动构造/参数网格搜索 |
| P7 | field-to-field比较: 功能正常, BOLL下轨+超卖触发率极低 | 已验证 2026-02-14 (非bug) |
| P8 | ID110僵尸实验stuck in backtesting | 已修复 2026-02-14 (强制标记failed) |
| P9 | ID95/96僵尸实验(信号爆炸) | 已自然结束(status=failed) |
| P10 | 全指标综合策略无法复现(ATR<0.05不可达) | ⏳低优先 2026-02-14 — 原P0重跑的545笔交易可能使用了不同代码路径. 已通过grid search获得更优变体(0.825), 原策略复现不再重要 |
| P11 | 收紧止损反而损害KDJ策略 | 已验证 2026-02-14 — -9%→-5%导致+37%→-24%, 信号需要呼吸空间 |
| P12 | Vortex指标DeepSeek无法生成 | 已确认 2026-02-14 — 2次尝试均在generating阶段超时, Vortex指标对DeepSeek不可用 |
| P13 | 信号爆炸策略阻塞队列 | **已修复** 2026-02-14+增强 2026-02-15 — L1增强: 周期性重检(每50天, 阈值300), 不仅前10天检测 |
| P14 | 回测队列处理慢(~2并发) | **已修复** 2026-02-16 — threading.Semaphore(1)串行执行(原3→1), clone-backtest含数据加载阶段也受限. 超时300s→600s |
| P15 | 回测挂死(策略/实验级) | **已修复** 2026-02-15 — 三层防护: L1信号爆炸增强, L2单策略5分钟超时(Timer+cancel_event), L3实验60分钟看门狗 |
| P16 | 批量重试机制 | **已实现** 2026-02-15 — POST /api/lab/experiments/{id}/retry + POST /api/lab/experiments/retry-pending |
| P24 | 服务器重启后孤儿回测 | **已修复** 2026-02-16 — `_recover_orphan_backtests()`在lifespan启动时检测stuck策略: clone实验自动重提交到后台线程, 普通实验reset为failed可通过retry API恢复 |
| P25 | Promote名称冲突(clone策略同名) | **已修复** 2026-02-16 — 克隆策略promote时若名称重复, 自动追加`_SLx_TPy`后缀; 仍重复则追加`_v{id}` |
| P26 | DeepSeek新指标策略生成失效(87.5% invalid) | ⏳外部依赖 2026-02-16 — DeepSeek模型能力限制, 无法正确格式化新指标条件. **已通过grid search完全绕过**: 93个StdA中大部分来自clone+grid search, 不再依赖DeepSeek生成新策略 |
| P27 | **clone-backtest stop_loss_pct正负号bug** | **已修复+验证** 2026-02-20 — 回测引擎约定`stop_loss_pct`为负数(e.g. -10表示10%止损), 批量脚本传入正数导致止损变止盈. R24原始273个实验全部无效. 修复: API端`clone-backtest`自动取负. R24-FIX 213实验全部成功(209 done, 0 invalid, 100% StdA), 400个新策略promoted |
| P28 | **uvicorn --reload杀死后台回测线程** | **已修复** 2026-02-23 — 318个clone-backtest实验提交后, uvicorn因--reload重启杀死了所有daemon线程, 导致271个实验stuck在backtesting. 修复: 1)使用retry-pending API恢复部分, 2)编写standalone fast_process.py脚本一次加载数据处理所有pending策略(节省267次重复数据加载). 建议: 生产环境不用--reload |
| P29 | **孤儿恢复线程风暴(475线程→连接池耗尽)** | **已修复** 2026-02-26 — `_recover_orphan_backtests()`对每个clone策略启动独立线程, 475个orphan→475线程→QueuePool(15max)耗尽+4GB内存. 修复: 改为单线程顺序处理, 一次加载股票数据复用. 内存10.6%→5.8% |
| P30 | retry-pending不处理0策略实验 | ⏳低优先 2026-02-27 — DeepSeek实验status=pending但strategy_count=0, retry-pending只处理有pending策略的实验. 这些需要重新POST创建. 15个R31 DeepSeek实验因此stuck |
| P31 | ATRcalm条件format错误: pct_diff→pct_change | **已修复** 2026-03-12 — `pct_diff`需要compare_field(不同列), ATRcalm应用`pct_change`(与自身历史比较)+`lookback_n:7` |
| P32 | `volume`字段不在INDICATOR_GROUPS中 | **已修复** 2026-03-12 — 添加`("volume","成交量")`到PRICE group的sub_fields。修复前`volume>volume_ma`条件报"未知指标字段" |
| P33 | VOLUME_MA indicator不支持 | **已修复** 2026-03-12 — rule_engine.py添加VOLUME_MA group+resolve_column_name; indicator_calculator.py添加volume_ma_periods+_add_volume_ma() |
| P34 | compare_field="MA_10"格式错误 | **已修复** 2026-03-12 — 正确格式: `compare_field:"MA"`+`compare_params:{"period":10}` |
| P35 | 条件中使用`lookback`键而非`lookback_n` | **已修复** 2026-03-12 — 规则引擎使用`rule.get("lookback_n")`，条件必须用`lookback_n`不是`lookback` |
| P36 | **batch-clone buy_conditions override用`threshold`键无效** | **已修复** 2026-03-27 — vectorize_conditions使用`compare_value`不是`threshold`。用`threshold`键会默认为0导致所有策略零交易。正确格式: `{"field":"ATR","operator":"<","compare_type":"value","compare_value":0.091,"params":{"period":14}}` |
| P37 | **扩展指标field名必须匹配sub_fields** | **已确认** 2026-03-27 — STOCHRSI必须用`STOCHRSI_K`不是`STOCHRSI`; STOCH必须用`STOCH_K`; KELTNER用`KELTNER_lower/upper/middle`; KELTNER params用`length_atr`不是`atr_length` |

---

## 下一步建议

> 每轮探索结束后更新。下一次运行的Step 1a会读取此节作为高优先级输入。

### R1208 发现 (2026-04-04, 50 exp, 266 strats, 18 StdA+)

**新骨架成功率: 10/23组 (43%) 产出StdA+**

| 方向 | StdA+ | 最佳Score | 状态 |
|------|-------|-----------|------|
| W_REALVOL | 2/10 (20%) | 0.8740 | ✅ 新进池 |
| KBARamp | 1/5 (20%) | 0.8732 | ✅ 新进池 |
| opt_novel_sells | 4/20 (20%) | 0.8724 | ✅ ATR+RSI优化 |
| W_KAMA | 2/10 (20%) | 0.8686 | ✅ 新进池 |
| PPOShigh | 1/10 (10%) | 0.8676 | ✅ 新进池 |
| WRVOL_KAMA | 1/5 (20%) | 0.8652 | ✅ 新进池 |
| W_PSAR | 2/10 (20%) | 0.8624 | ✅ 新进池 |
| W_EMA | 2/10 (20%) | 0.8588 | ✅ 新进池 |
| W_MOM | 2/10 (20%) | 0.8401 | ✅ 新进池 |
| W_BOLL | 1/10 (10%) | 0.8398 | ✅ 新进池 |
| PPOS_close_pos | 0/26 | 0.7343 | ❌ 已弃(wr<45%) |
| AMPVOL | 0/10 | 0.5068 | ❌ 已弃(8 trades) |
| W_STOCH | 0/10 | 0.8202 | ❌ 已弃(wr<60%) |
| REALVOL_fill | 0/30 | 0.8763 | ❌ fills全fail wr |
| MOM_RSTR_fill | 0/24 | 0.8769 | ❌ fills全fail wr |

**关键洞察**:
1. **6/8 W_指标产出StdA+** (75%成功率) — 多时间框架是最强新维度
2. **KBAR_amplitude有效** (score=0.8732) — 低振幅买入≈ATRcalm逻辑
3. **Fill实验全部失败wr阈值** — REALVOL/MOM+RSTR/LIQ/KAMA+W_ATR有高score(0.87+)但wr<60%
4. **PPOS_close_pos/AMPVOL确认无效** — 价格位置和Parkinson波动率不适合作为买入条件

### R1209 发现 (2026-04-04, 50 exp, 289 strats, 92 StdA+ = 31.8%)

**突破: Ultra-low TP解决wr<60%!** REALVOL(15/15=100%), MOM+RSTR(10/10=100%) — TP=0.3-1.0使高score指标通过wr>60%门槛

| 方向 | StdA+ | Rate | Best | 重要性 |
|------|-------|------|------|--------|
| RVOL_ultraTP | 15/15 | 100% | 0.8565 | 突破 |
| MOM_RSTR_ultraTP | 10/10 | 100% | 0.8522 | 突破 |
| WRVOL_fill | 20/40 | 50% | 0.8752 | 最大产出 |
| KBAR_fill | 16/40 | 40% | 0.8790 | 最高score |
| WRVOL_KBAR | 10/24 | 42% | 0.8731 | 双因子组合 |
| opt2 | 5/25 | 20% | 0.8786 | ATR+RSI优化 |
| + 11 more | 11 total | 7-20% | various | 新因子验证 |

新因子验证: RVOL_downside✅, M_REALVOL✅, PVOL_corr✅, W_ADX✅, KBAR_body✅, RVOL_skew✅, PPOS_drawdown✅
失败: PPOS_low_dist❌, PVOL_vwap_bias❌, LIQ_amihud❌

### R1210 发现 (2026-04-04, 47 exp, 375 strats, 164 StdA+ = 43.7%)

**KBAR massive grid + RVOL_downside deep + triple combos 全部成功**
- Pool从10→24 families, 169→394 active
- KBAR_amplitude 15阈值grid完成(0.015-0.06), 最优区间待分析
- Triple combos (W_REALVOL+KBAR+RVOL_downside, +PVOL_corr) 均产出StdA+
- Ultra-low TP expansion: 更多因子组合验证100% rate

### R1211 发现 (2026-04-06, 50 exp, 331 strats, 110 StdA+ = 41.8%)

**14/14组100%成功率** — 每个测试方向都产出StdA+
- 所有fill家族50% StdA+率: WRV_fill, RV_fill, MR_fill, quad2, quad3
- 新因子: RVkurt(9/25=36%, 0.8784), AMPVOL_std(1/5, 0.8729), RSTR_weighted(1/5, 0.8737)
- PVcorr_uTP: 5/5=100% — ultra-low TP持续有效
- 4-factor combos全部产出StdA+: quad_(45.8%), quad2(50%), quad3(50%), quad4(31.2%)

### R1212 发现 (2026-04-06, 46 exp, 338 strats, 147 StdA+ = 46.8% ALL-TIME)

**13/14组产出StdA+**, 仅W_ATR(0/24)失败。5f combo达session最高score 0.8791
- AMPs_(58.6%), RSTRw_(61.5%), RVk_KB(57.1%), uTP(100%)
- 5f_RVk(45.8%, 0.8791), 5f_PV(33.3%), 所有fill家族50%
- W_ATR standalone = 0/24 已弃

### R1213 发现 (2026-04-06, 48 exp, 357 strats, 136 StdA+ = 46.0%)

**best=0.8805(新最高分!)** 6f combos + deep fills + W_AMPVOL/W_RSTR新因子
- Pool从53→59 families, 790→900 active
- 新家族: ATR+RSI+W_AMPVOL(gap=148), ATR+PVOL_AMOUNT+RSI+W_REALVOL(gap=145)
- AMPVOL+ATR+RSI fill成长到33/150

### R1214 发现 (2026-04-06, 50 exp, 385 strats, 143 StdA+ = 43.5%)

Pool从59→70 families, 900→1022 active。143 StdA+, best=0.8805
- W_AMPVOL fill 45%, AMPs deep 50%, PVamt+W_RVOL 50%, W_KBAR 42%
- 新家族: AMPVOL+ATR+REALVOL+RSI(gap=142), W_RSTR+KBAR combos
- 7-factor EXTREME combos提交并完成

### R1215 发现 (2026-04-10, 50 exp, 385 strats, 126 StdA+ = 34.9%)

**best=0.8812(新最高分!)** LIQ/MOM/RSTR combo fills, W_PVOL/RVkurt+W_AMPVOL新combo

### 下一步优先级 (R1216+)

1. **继续fill top-gap families** — LIQ_TURN(148), W_ATR(144), AMPVOL+RVOL(142)
2. **深度fill PVOL_AMT+W_RVOL** — gap=133, avg=0.8538(高)
3. **新combo: W_PVOL_corr + W_AMPVOL + KBAR** — 周线量价+周线振幅+日线K线
4. **新combo: LIQ_turn + AMPs + KBAR** — 流动性+波动+K线三因子
5. **新combo: RVkurt + W_RSTR + KBAR** — 峰度+周线动量+K线
6. **ATR+RSI optimization** — 池满(gap=0), 尝试新sell types超越最弱champion



## 历史详细轮次记录 (已归档)

> 详细轮次记录(R28-R526)已归档至API(`/api/lab/exploration-rounds`)。
> 使用 `GET /api/lab/exploration-rounds` 查询历史数据。



## Auto-Promote 记录

> 累计 **20,650+** 个StdA+策略已promote。
> **R1281** (Engine, 2026-04-21 09:09): **246 StdA+ (95.7%)** — best=0.8643, promoted=241, provider=code-driven。Pool: 24家族, 262活跃
## 下一步优先级

### R1281 自动探索结果 (2026-04-21 09:09)

**246 StdA+ (95.7%)**, best=0.8643, provider=code-driven

### 下一步优先级 (R1282+)

1. **填充 top-gap 家族**:
  - ATR+PVOL_AMOUNT+RSI+W_KBAR (gap=146, avg=0.8511)
  - ATR+RSI+TREND_STRENGTH+W_KBAR (gap=146, avg=0.8506)
  - ATR+RSI+VOLUME_RATIO+W_KBAR (gap=146, avg=0.8506)
  - ACCELERATION+ATR+LIQ_TURNOVER+RSI (gap=146, avg=0.8501)
  - ACCELERATION+ATR+RSI+VOLUME_RATIO (gap=146, avg=0.8500)
2. **新因子组合探索** — pool gap=2808
3. **优化已满家族** — 尝试新 sell 条件

