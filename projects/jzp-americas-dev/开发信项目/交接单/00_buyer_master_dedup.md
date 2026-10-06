# 00 Buyer Master Dedup（内部排重唯一真源）

> 给 AI 看的，不给用户看。对话里只报数量+命中结论，不贴全文。
> 规则：每次推荐新客户前，必须在此文件全文检索：EXACT（归一化全等）直接剔除；PARTIAL（词序子串/缩写折叠）标疑似人工判。不要另写比对逻辑。
> 生成时间：2026-09-24；来源：project2/buyers 四个 batch 目录实盘扫描。

总数：85 份交接单（batch1:19 + batch2:37 + batch3:14 + batch4:15）。缺号 20、21（空号）；22 为未发送。

## 一、主表（85）

| 编号 | 核心名 | 归一化key | 批次文件 |
|---|---|---|---|
| 1 | BG_High_Voltage | bg high voltage | batch1_early_1-19/买家1_BG_High_Voltage_开发信交接单.md |
| 2 | Ontario_High_Voltage | ontario high voltage | batch1_early_1-19/买家2_Ontario_High_Voltage_开发信交接单.md |
| 3 | ISCOCA | iscoca | batch1_early_1-19/买家3_ISCOCA_开发信交接单.md |
| 4 | DECH_High_Voltage | dech high voltage | batch1_early_1-19/买家4_DECH_High_Voltage_开发信交接单.md |
| 5 | Reeve_Electric | reeve electric | batch1_early_1-19/买家5_Reeve_Electric_开发信交接单.md |
| 6 | Williams_Electric | williams electric | batch1_early_1-19/买家6_Williams_Electric_开发信交接单.md |
| 7 | ALCO_Electric | alco electric | batch1_early_1-19/买家7_ALCO_Electric_开发信交接单.md |
| 8 | Alaska_Line_Builders | alaska line builders | batch1_early_1-19/买家8_Alaska_Line_Builders_开发信交接单.md |
| 9 | PowerTec_Electric | powertec electric | batch1_early_1-19/买家9_PowerTec_Electric_开发信交接单.md |
| 10 | Rogers_Electrical | rogers electrical | batch1_early_1-19/买家10_Rogers_Electrical_开发信交接单.md |
| 11 | South_Charleston_Electric | south charleston electric | batch1_early_1-19/买家11_South_Charleston_Electric_开发信交接单.md |
| 12 | Technical_Power_Services | technical power services | batch1_early_1-19/买家12_Technical_Power_Services_开发信交接单.md |
| 13 | Chatham_Electric | chatham electric | batch1_early_1-19/买家13_Chatham_Electric_开发信交接单.md |
| 14 | Pritchard_Electric | pritchard electric | batch1_early_1-19/买家14_Pritchard_Electric_开发信交接单.md |
| 15 | Pitts_Electric | pitts electric | batch1_early_1-19/买家15_Pitts_Electric_开发信交接单.md |
| 16 | Guerry_Electrical | guerry electrical | batch1_early_1-19/买家16_Guerry_Electrical_开发信交接单.md |
| 17 | Washington_State_Power | washington state power | batch1_early_1-19/买家17_Washington_State_Power_开发信交接单.md |
| 18 | WinAsia_Power_Corporation | winasia power corporation | batch1_early_1-19/买家18_WinAsia_Power_Corporation_开发信交接单.md |
| 19 | {{COMPANY}} | scientechnic | batch1_early_1-19/买家19_{{COMPANY}}_开发信交接单.md |
| 22 | VoltCore_Electrical | voltcore electrical | batch2_mid_22-58/买家22_VoltCore_Electrical_开发信交接单_未发送.md |
| 23 | Bossie_Electric | bossie electric | batch2_mid_22-58/买家23_Bossie_Electric_开发信交接单.md |
| 24 | Purcee_Industrial_Power | purcee industrial power | batch2_mid_22-58/买家24_Purcee_Industrial_Power_开发信交接单.md |
| 25 | GLS_Electric | gls electric | batch2_mid_22-58/买家25_GLS_Electric_开发信交接单.md |
| 26 | Oregon_Electric_Service | oregon electric service | batch2_mid_22-58/买家26_Oregon_Electric_Service_开发信交接单.md |
| 27 | CW_Galle | cw galle | batch2_mid_22-58/买家27_CW_Galle_开发信交接单.md |
| 28 | Romar_Electrical | romar electrical | batch2_mid_22-58/买家28_Romar_Electrical_开发信交接单.md |
| 29 | {{COMPANY}} | hillfort | batch2_mid_22-58/买家29_{{COMPANY}}_开发信交接单.md |
| 30 | MVA_Power | mva power | batch2_mid_22-58/买家30_MVA_Power_开发信交接单.md |
| 31 | TN_Electrical | tn electrical | batch2_mid_22-58/买家31_TN_Electrical_开发信交接单.md |
| 32 | Rexel_Utility | rexel utility | batch2_mid_22-58/买家32_Rexel_Utility_开发信交接单.md |
| 33 | Tri-State_Utility | tri state utility | batch2_mid_22-58/买家33_Tri-State_Utility_开发信交接单.md |
| 34 | Vancouver_Industrial_Electric | vancouver industrial electric | batch2_mid_22-58/买家34_Vancouver_Industrial_Electric_开发信交接单.md |
| 35 | Amped_Electric | amped electric | batch2_mid_22-58/买家35_Amped_Electric_开发信交接单.md |
| 36 | Power_Line_Supply | power line supply | batch2_mid_22-58/买家36_Power_Line_Supply_开发信交接单.md |
| 37 | Irby_Utilities | irby utilities | batch2_mid_22-58/买家37_Irby_Utilities_开发信交接单.md |
| 38 | Brownstown_Electric | brownstown electric | batch2_mid_22-58/买家38_Brownstown_Electric_开发信交接单.md |
| 39 | OneSource_Distributors | onesource distributors | batch2_mid_22-58/买家39_OneSource_Distributors_开发信交接单.md |
| 40 | KBS_Electrical | kbs electrical | batch2_mid_22-58/买家40_KBS_Electrical_开发信交接单.md |
| 41 | Transformer_Engineering_Services | transformer engineering services | batch2_mid_22-58/买家41_Transformer_Engineering_Services_开发信交接单.md |
| 42 | RA_Electrical | ra electrical | batch2_mid_22-58/买家42_RA_Electrical_开发信交接单.md |
| 43 | Ross_Morrison | ross morrison | batch2_mid_22-58/买家43_Ross_Morrison_开发信交接单.md |
| 44 | K2_Electric | k2 electric | batch2_mid_22-58/买家44_K2_Electric_开发信交接单.md |
| 45 | GEC | gec | batch2_mid_22-58/买家45_GEC_开发信交接单.md |
| 46 | Fletcher_Reinhardt | fletcher reinhardt | batch2_mid_22-58/买家46_Fletcher_Reinhardt_开发信交接单.md |
| 47 | Techline | techline | batch2_mid_22-58/买家47_Techline_开发信交接单.md |
| 48 | Sunbelt_Solomon | sunbelt solomon | batch2_mid_22-58/买家48_Sunbelt_Solomon_开发信交接单.md |
| 49 | Valley_Electrical_Suppliers | valley electrical suppliers | batch2_mid_22-58/买家49_Valley_Electrical_Suppliers_开发信交接单.md |
| 50 | Border_States | border states | batch2_mid_22-58/买家50_Border_States_开发信交接单.md |
| 51 | Power_Substation_Services | power substation services | batch2_mid_22-58/买家51_Power_Substation_Services_开发信交接单.md |
| 52 | {{COMPANY}} | westmoreland | batch2_mid_22-58/买家52_{{COMPANY}}_开发信交接单.md |
| 53 | Iconic_Power | iconic power | batch2_mid_22-58/买家53_Iconic_Power_开发信交接单.md |
| 54 | Dana_Power_and_Poles | dana power and poles | batch2_mid_22-58/买家54_Dana_Power_and_Poles_开发信交接单.md |
| 55 | {{COMPANY}} | gridlink | batch2_mid_22-58/买家55_{{COMPANY}}_开发信交接单.md |
| 56 | Kirby_Electric | kirby electric | batch2_mid_22-58/买家56_Kirby_Electric_开发信交接单.md |
| 57 | BV_Electric | bv electric | batch2_mid_22-58/买家57_BV_Electric_开发信交接单.md |
| 58 | Birmingham_Electric | birmingham electric | batch2_mid_22-58/买家58_Birmingham_Electric_开发信交接单.md |
| 59 | Texas_Electric_Cooperatives | texas electric cooperatives | batch3_late_59-72/买家59_Texas_Electric_Cooperatives_开发信交接单.md |
| 60 | Stewart_Electric | stewart electric | batch3_late_59-72/买家60_Stewart_Electric_开发信交接单.md |
| 61 | {{COMPANY}}_Mell_Nicholson | priester mell nicholson | batch3_late_59-72/买家61_{{COMPANY}}_Mell_Nicholson_开发信交接单.md |
| 62 | Everlast_Electric | everlast electric | batch3_late_59-72/买家62_Everlast_Electric_开发信交接单.md |
| 63 | Rising_Edge | rising edge | batch3_late_59-72/买家63_Rising_Edge_开发信交接单.md |
| 64 | Tryggr_Technical_Services | tryggr technical services | batch3_late_59-72/买家64_Tryggr_Technical_Services_开发信交接单.md |
| 65 | AMPS_Powerline | amps powerline | batch3_late_59-72/买家65_AMPS_Powerline_开发信交接单.md |
| 66 | Fullford_Electric | fullford electric | batch3_late_59-72/买家66_Fullford_Electric_开发信交接单.md |
| 67 | AECI | aeci | batch3_late_59-72/买家67_AECI_开发信交接单.md |
| 68 | UUS | uus | batch3_late_59-72/买家68_UUS_开发信交接单.md |
| 69 | RESCO | resco | batch3_late_59-72/买家69_RESCO_开发信交接单.md |
| 70 | WUES | wues | batch3_late_59-72/买家70_WUES_开发信交接单.md |
| 71 | CEEUS | ceeus | batch3_late_59-72/买家71_CEEUS_开发信交接单.md |
| 72 | GenPac | genpac | batch3_late_59-72/买家72_GenPac_开发信交接单.md |
| 73 | GNS_Technologies | gns technologies | batch4_73plus/买家73_GNS_Technologies_开发信交接单.md |
| 74 | HEI_Utility_Contractors | hei utility contractors | batch4_73plus/买家74_HEI_Utility_Contractors_开发信交接单.md |
| 75 | HS_Energy_System | hs energy system | batch4_73plus/买家75_HS_Energy_System_开发信交接单.md |
| 76 | Universal_Electric_Services | universal electric services | batch4_73plus/买家76_Universal_Electric_Services_开发信交接单.md |
| 77 | RESA_Power_Components | resa power components | batch4_73plus/买家77_RESA_Power_Components_开发信交接单.md |
| 78 | Graybar_Canada_Oshawa | graybar canada oshawa | batch4_73plus/买家78_Graybar_Canada_Oshawa_开发信交接单.md |
| 79 | Wesco_Distribution_Canada | wesco distribution canada | batch4_73plus/买家79_Wesco_Distribution_Canada_开发信交接单.md |
| 80 | Killmer_Electric | killmer electric | batch4_73plus/买家80_Killmer_Electric_开发信交接单.md |
| 81 | TM3 | tm3 | batch4_73plus/买家81_TM3_开发信交接单.md |
| 82 | Northern_High_Voltage | northern high voltage | batch4_73plus/买家82_Northern_High_Voltage_开发信交接单.md |
| 83 | Moody_Electric | moody electric | batch4_73plus/买家83_Moody_Electric_开发信交接单.md |
| 84 | Electrozad_Supply | electrozad supply | batch4_73plus/买家84_Electrozad_Supply_开发信交接单.md |
| 85 | Schaedler_Yesco | schaedler yesco | batch4_73plus/买家85_Schaedler_Yesco_开发信交接单.md |
| 86 | Franklin_Empire | franklin empire | batch4_73plus/买家86_Franklin_Empire_开发信交接单.md |
| 87 | Van_Meter | van meter | batch4_73plus/买家87_Van_Meter_开发信交接单.md |

## 二、外部排除（不在交接单里，但同样不能推）

| 来源 | 公司 | 归一化key | 备注 |
|---|---|---|---|
| 客户类型①出去重 | Pro 1 Electric | pro 1 electric | WV |
| 客户类型① | Wilson High Voltage | wilson high voltage | ON；与 Drunken Moose 同地址，关联判重 |
| 客户类型① | Drunken Moose Enterprises | drunken moose enterprises | 与 Wilson 同地址 |
| 客户类型① | JS Energy | js energy | NS |
| 客户类型① | ATD Power Solutions | atd power solutions | AK |
| 客户类型① | Boundary Electric | boundary electric | BC |
| 客户类型① | Bibico Electric | bibico electric | ON Burlington；与 AC Tesla 同地址 |
| 客户类型①关联 | AC Tesla | ac tesla | 与 Bibico 同地址，文件内提及 |
| 客户类型① | Electric South | electric south | AL Robertsdale |
| 客户类型② | Domino Highvoltage Supply | domino highvoltage supply | AB Edmonton |
| 客户类型② | POWER ELECTRONICS | power electronics | CA Visalia；注意 Graybar/CED 同城不同主体，不可误判为同一家 |
| 跟进表PPT | Dcore Electric | dcore electric | 在谈 Ben Cottell |
| 跟进表PPT | Bayou Transformer | bayou transformer | 在谈 Troy Rembert |
| 跟进表PPT | Dardan Electric | dardan electric | 在谈 Jordan White |

## 三、新搜同步区（以后搜到的客户先登记再推荐，避免重复）

| 日期 | 公司 | 归一化key | 状态 |
|---|---|---|---|
| 2026-09-24 | A&W High Voltage Contracting | aw high voltage contracting | 待建交接单（承包商·ON Innisfil） |
| 2026-09-24 | MVI LLC {{COMPANY}} | mvi mon valley integration | 待建交接单（承包商·WV Morgantown） |
| 2026-09-24 | {{COMPANY}} | rhododendron electric | 待建交接单（承包商·WV Washington） |
| 2026-09-24 | Robert Electrical Contractors Mobile | robert electrical contractors | 待建交接单（承包商·AL Mobile） |
| 2026-09-24 | Power Transformer Services PTS | power transformer services | 待建交接单（承包商/变压器服务·AL） |
| 2026-09-24 | {{COMPANY}} Electric | mcnaughton mckay electric | 待建交接单（经销商·MI） |
| 2026-09-24 | Turtle and Hughes | turtle hughes | 待建交接单（经销商·NJ） |
| 2026-09-24 | {{COMPANY}} Kendall Group | kendall electric | 待建交接单（经销商·MI） |
| 2026-09-24 | {{COMPANY}} Canada | gescan | 待建交接单（经销商·BC/ON） |
| 2026-09-24 | Crescent Electric Supply | crescent electric supply | 待建交接单（经销商·IL） |
| 2026-09-24 | {{COMPANY}} | aurum electric | 待建交接单（承包商·ON Burlington） |
| 2026-09-24 | {{COMPANY}} | kraun electric | 待建交接单（承包商·ON St Catharines，100+人偏大备选） |
| 2026-09-24 | Continental Power Services | continental power services | 待建交接单（承包商·BC Burnaby） |
| 2026-09-24 | Intel Electric Anchorage | intel electric | 待建交接单（承包商·AK Anchorage/Wasilla） |
| 2026-09-24 | Amtek | amtek | 待建交接单（承包商·NS） |
| 2026-09-24 | State Electric Supply | state electric supply | 待建交接单（经销商·WV Huntington） |
| 2026-09-24 | {{COMPANY}} Supply | elliott electric supply | 待建交接单（经销商·TX Nacogdoches） |
| 2026-09-24 | City Electric Supply CES | city electric supply | 待建交接单（经销商·TX Dallas；非CED，注意区分） |
| 2026-09-24 | {{COMPANY}} International | guillevin international | 待建交接单（经销商·QC Montreal） |
| 2026-09-24 | {{COMPANY}} Supply | yale electric supply | 待建交接单（经销商·PA Harrisburg） |
| 2026-09-24 | Leading Edge Electric | leading edge electric | 待建交接单（承包商·AK Wasilla，复筛9/10保留） |
| 2026-09-24 | {{COMPANY}} | megawatt electric | 待建交接单（承包商·AK，复筛8/10保留） |
| 2026-09-24 | {{COMPANY}} Energy Solutions | solectric energy solutions | 待建交接单（承包商·NS，复筛7/10保留） |
| 2026-09-24 | {{COMPANY}} Controls | zeus electric controls | 待建交接单（承包商·BC Burnaby，复筛9/10保留） |
| 2026-09-24 | {{COMPANY}} | mott electric | 待建交接单（承包商·BC Burnaby，复筛7/10保留偏大备选） |
| 2026-09-24 | EB Horsman Son | eb horsman son | 待建交接单（经销商·BC Surrey，复筛8/10保留） |
| 2026-09-24 | {{COMPANY}} | codale electric supply | 待建交接单（经销商·UT，复筛8/10保留） |
| 2026-09-24 | Gresco | gresco | 待建交接单（经销商·GA Forsyth，复筛9/10保留） |
| 2026-09-24 | Cooper Electric | cooper electric | 待建交接单（经销商·NJ，复筛7/10保留） |
| 2026-09-24 | Walters {{COMPANY}} | walters wholesale electric | 待建交接单（经销商·CA Fontana，复筛9/10保留） |
| 2026-09-24 | {{COMPANY}} | j ranck electric | 待建交接单（承包商·MI，复筛8/10保留） |
| 2026-09-24 | {{COMPANY}} Charleston | progressive electric | 待建交接单（承包商·WV，复筛8/10保留；与South Charleston不同主体） |
| 2026-09-24 | Canem Systems | canem systems | 待建交接单（承包商·BC Richmond，复筛8/10保留） |
| 2026-09-24 | {{COMPANY}} | valard construction | 待建交接单（承包商·AB，复筛7/10保留偏大备选） |
| 2026-09-24 | Alcan Electric Engineering | alcan electric | 待建交接单（承包商·AK，复筛7/10保留偏大备选） |
| 2026-09-24 | {{COMPANY}} Supply | aes electric supply | 待建交接单（经销商·AK Fairbanks，复筛10/10保留） |
| 2026-09-24 | Standard Electric Supply | standard electric supply | 待建交接单（经销商·WI，复筛7/10保留） |
| 2026-09-24 | Agilix Solutions French Gerleman | agilix solutions french gerleman | 待建交接单（经销商·MO，复筛7/10保留） |
| 2026-09-24 | Lumen Sonepar | lumen | 待建交接单（经销商·QC，复筛6/10保留规模偏大） |
| 2026-09-24 | {{COMPANY}} Industrial Supply | advance electrical industrial supply | 待建交接单（经销商·GA，复筛8/10保留） |
| 2026-09-24 | {{COMPANY}} Company | sargent electric company | 待建交接单（承包商·PA，复筛8/10保留） |
| 2026-09-24 | {{COMPANY}} CVE | cache valley electric | 待建交接单（承包商·UT，复筛7/10保留偏大备选） |
| 2026-09-24 | EC Electric | ec electric | 待建交接单（承包商·OR，复筛6/10压线偏大备选） |
| 2026-09-24 | {{COMPANY}} | lapp electric | 待建交接单（承包商·PA Lancaster，复筛7/10保留） |
| 2026-09-24 | {{COMPANY}} | houle electric | 待建交接单（承包商·BC，复筛7/10保留偏大备选） |
| 2026-09-24 | {{COMPANY}} | bartle gibson | 待建交接单（经销商·AB，复筛8/10保留） |
| 2026-09-24 | {{COMPANY}} | torbram electric supply | 待建交接单（经销商·ON，复筛9/10保留） |
| 2026-09-24 | World Electric Supply | world electric supply | 待建交接单（经销商·FL，复筛7/10保留） |
| 2026-09-24 | {{COMPANY}} Springfield | echo electric springfield | 待建交接单（经销商·IL，复筛7/10保留） |
| 2026-09-24 | {{COMPANY}} Electric | north coast electric | 待建交接单（经销商·WA，复筛7/10保留） |
| 2026-09-24 | Lemberg Electric Company | lemberg electric company | 待建交接单（承包商·WI，复筛7/10保留） |
| 2026-09-24 | {{COMPANY}} | egan company | 待建交接单（承包商·MN，复筛6/10压线备选） |
| 2026-09-24 | Big State Electric | big state electric | 待建交接单（承包商·TX，复筛9/10保留） |
| 2026-09-24 | Van Ert Electric | van ert electric | 待建交接单（承包商·WI，复筛8/10保留） |
| 2026-09-24 | {{COMPANY}} Charleston WV | progressive electric charleston | 待建交接单（承包商·WV，复筛8/10保留；与South Charleston不同主体） |
| 2026-09-24 | JH Larson Company | jh larson company | 待建交接单（经销商·MN，复筛8/10保留） |
| 2026-09-24 | {{COMPANY}} Supply | summit electric supply | 待建交接单（经销商·NM，复筛7/10保留） |
| 2026-09-24 | Dixon Electric | dixon electric | 待建交接单（经销商·ON Burlington，复筛8/10保留；与Bibico同街不同门牌） |
| 2026-09-24 | Robertson Electric Wholesale | robertson electric wholesale | 待建交接单（经销商·ON Vaughan，复筛8/10保留） |
| 2026-09-24 | SESCO Sonepar | sesco | 待建交接单（经销商·ON 401走廊，复筛8/10保留） |
| 2026-09-24待查 | （此前20家已在主表，无需重复登记） | - | 已在主表 |：GNS/HEI/VoltCore/OntarioHV/Universal/HS/RESA/Sunbelt/Graybar/Wesco/Killmer/TM3/Northern/Dana/Moody/Valley/Electrozad/Schaedler/Franklin/VanMeter 全部已在主表，无需重复登记） | - | 已在主表 |

## 四、使用方法
1. 新候选先算 normalize（小写、去符号、连续单字母折叠：B.G.->bg；剥离括号注释如 (Thunder Bay)）。
2. 与主表归一化key 做 EXACT 全等比对，命中即剔除。
3. 再做 PARTIAL 词序子串比对（如 bg high voltage 命中 bg high voltage systems），标疑似人工判。
4. 通过的才推荐；推荐后立即追加到第三节。
