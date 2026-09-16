using System.Text;
using System.Text.RegularExpressions;

namespace POE2Radar.Core.Game;

/// <summary>Converts display-bound game text to POE2DB Traditional Chinese. Internal IDs and metadata paths stay intact.</summary>
public static class DisplayTextLocalizer
{
    // Fixed UI strings were authored in Simplified Chinese before the POE2DB Traditional
    // Chinese catalog was added. This conversion is deliberately presentation-only: callers
    // must use it for labels and help text, never for metadata, rule keys, or memory values.
    private static readonly (string Simplified, string Traditional)[] UiTraditionalPairs =
    {
        ("世界地图", "世界地圖"), ("异界地图", "異界地圖"), ("地图石", "換界石"),
        ("异界", "異界"), ("地图", "地圖"), ("路径", "路徑"), ("路线", "路線"), ("网格", "網格"),
        ("节点", "節點"), ("连线", "連線"), ("连接", "連線"), ("图标", "圖示"),
        ("物品过滤器", "物品篩選器"), ("显示规则", "顯示規則"), ("异界地图", "異界地圖"),
        ("快捷键", "快捷鍵"), ("仪表盘", "儀表板"),
        ("控制台", "控制臺"), ("词缀", "詞綴"), ("时间线", "時間軸"), ("颜色", "顏色"),
        ("会话", "會話"), ("区域", "區域"), ("等级", "等級"),
        ("击杀", "擊殺"), ("经验", "經驗"), ("预加载", "預載入"), ("阶级", "階級"),
        ("阶段", "階段"), ("药剂", "藥劑"), ("风险", "風險"), ("跳过", "跳過"),
        ("宝箱", "寶箱"), ("设置", "設定"), ("打开", "開啟"), ("关闭", "關閉"),
        ("启动", "啟動"), ("导入", "匯入"), ("导出", "匯出"), ("选择", "選擇"),
        ("显示", "顯示"), ("隐藏", "隱藏"), ("读取", "讀取"), ("实时", "即時"),
        ("实体", "實體"), ("装备", "裝備"), ("传奇", "傳奇"), ("运行", "執行"),
        ("点击", "點擊"), ("当前", "目前"), ("终点", "終點"), ("起点", "起點"),
        ("终局", "終局"), ("战利品", "戰利品"), ("画面", "畫面"), ("边缘", "邊緣"),
        ("关键", "關鍵"), ("升级", "升級"), ("启用", "啟用"), ("删除", "刪除"),
        ("恢复", "還原"), ("过滤", "篩選"), ("筛选", "篩選"), ("编号", "編號"),
        ("复制", "複製"), ("名称", "名稱"), ("标题", "標題"), ("目录", "目錄"),
        ("游戏", "遊戲"), ("浏览器", "瀏覽器"), ("网页", "網頁"), ("网络", "網路"),
        ("日志", "日誌"), ("后台", "背景"), ("进程", "處理程序"), ("内存", "記憶體"),
        ("加载", "載入"), ("数据", "資料"), ("应用", "套用"), ("创建", "建立"),
        ("检查", "檢查"), ("强制", "強制"), ("即时", "即時"), ("传送", "傳送"),
        ("档案", "檔案"), ("发生", "發生"), ("触发", "觸發"), ("发现", "發現"),
        ("场景", "場景"), ("状态", "狀態"), ("数值", "數值"), ("计时", "計時"), ("层", "層"),
        ("视野", "視野"), ("保存", "儲存"), ("扩展", "擴充"), ("数量", "數量"),
        ("优先", "優先"), ("总开关", "總開關"), ("组件", "元件"), ("字体", "字型"),
        ("键盘", "鍵盤"), ("规则", "規則"), ("从", "從"), ("仅", "僅"), ("自动", "自動"),
        ("预设", "預設"), ("频道", "頻道"), ("覆盖", "覆蓋"), ("独立", "獨立"),
        ("权重", "權重"), ("极品", "極品"), ("粘贴", "貼上"), ("下载", "下載"),
        ("获得", "獲得"), ("章节", "章節"), ("兴趣点", "興趣點"), ("制图", "製圖"),
        ("箭头", "箭頭"), ("种类", "種類"), ("轮换", "輪換"), ("标记", "標記"),
        ("始终", "始終"), ("管理员", "管理員"), ("绑定", "繫結"), ("折叠", "摺疊"),
        ("观察", "觀察"), ("城镇", "城鎮"), ("进入", "進入"), ("伤害", "傷害"),
        ("护盾", "護盾"), ("高级", "高階"), ("画布", "畫布"), ("距离", "距離"),
        // Additional UI vocabulary used by the web dashboard and live status messages.
        // These are interface phrases only; POE2DB game names are protected separately.
        ("保存", "儲存"), ("应用", "套用"), ("打开", "開啟"), ("搜索", "搜尋"),
        ("查看", "檢視"), ("捕获", "擷取"), ("当前", "目前"), ("会话", "工作階段"),
        ("设置", "設定"), ("资料", "資料"), ("验证", "驗證"), ("记录", "記錄"),
        ("局域网", "區域網路"), ("刷新", "重新整理"), ("覆盖", "覆蓋"),
        ("版面", "版面"), ("预设", "預設"), ("空白", "空白"), ("删除", "刪除"),
        ("复制", "複製"), ("导入", "匯入"), ("导出", "匯出"), ("启用", "啟用"),
        ("禁用", "停用"), ("展开", "展開"), ("折叠", "摺疊"), ("移除", "移除"),
        ("新增", "新增"), ("状态", "狀態"), ("说明", "說明"), ("提示", "提示"),
        ("错误", "錯誤"), ("成功", "成功"), ("失败", "失敗"), ("无", "無"),
        ("尚无", "尚無"), ("阶段", "階段"), ("进度", "進度"), ("目标", "目標"),
        ("优先级", "優先級"), ("类别", "類別"), ("内容", "內容"), ("类型", "類型"),
        ("详细", "詳細"), ("摘要", "摘要"), ("帮助", "幫助"), ("快捷键", "快捷鍵"),
        ("工作阶段", "工作階段"), ("工作会话", "工作階段"), ("小组件", "小工具"),
        ("网格", "網格"), ("路径", "路徑"), ("路线", "路線"), ("连接", "連線"),
        ("地图颜色", "地圖顏色"), ("面板", "面板"), ("覆盖层", "覆蓋層"),
        ("词缀", "詞綴"), ("属性", "屬性"), ("物件", "物件"), ("资料包", "資料包"),
        ("高级", "進階"), ("首领", "首領"), ("地图", "地圖"), ("地图石", "地圖石"),
        ("设置", "設定"), ("搜索", "搜尋"), ("刷新", "重新整理"), ("布局", "版面"),
        ("导航", "導航"), ("任务", "任務"), ("章节", "章節"), ("导入", "匯入"),
        ("导出", "匯出"), ("保存", "儲存"), ("应用", "套用"), ("删除", "刪除"),
        ("恢复", "還原"), ("重新绑定", "重新綁定"), ("局域网", "區域網路"),
        ("会话小组件", "工作階段小工具"), ("会话回顾", "工作階段回顧"),
        ("击杀总数", "擊殺總數"), ("稀有击杀", "稀有擊殺"), ("传奇击杀", "傳奇擊殺"),
        ("点阵", "點陣"), ("点阵图", "點陣圖"), ("位图", "點陣圖"), ("总数", "總數"), ("回顾", "回顧"),
        ("实验性", "實驗性"), ("实验", "實驗"), ("推荐", "推薦"), ("来源", "來源"),
    };

    // Character-level fallback for dynamic UI copy assembled by the dashboard or status
    // panels. Phrase mappings above remain the preferred wording; this map only fills gaps
    // where a whole sentence was not present in the catalog.
    private const string TraditionalCharacters = "藥劑階閃電遊戲稱內領資載敗記錄無運須寫項儲驗證錯誤刪規則嗎動復請選擇類達篩預設蓋層擷網離線讀異圖關閉開啟後頁沒時節點區頻診斷標畫顯評權組蹤會顏並檔鑑還擊傳從遷嘗試檢欄產掃複製議碼謝識實體條優順換導頭繪圓環邊緣隱為籤個詞彙號險綴塊徑於數編輯單題態綁將鍵級殺價獎勵觀員裝備淵譫機銀銅聖別計鎮統經戰針尋觸發輸鬥進見閾熱準縮範鈕種鐘聲鈴嗶驟視僅過來遙測務訂國陸鏡這螢獨獲門檻貼護興揮師現與萬轉霧間廳脈輔寶維儀覽匯庫隨贈註對應狀連強偵輪終憶訊錨巔瀏遠許穩靜劃費變腦風劇報戶詳細爾煉顧總長傷繼裡摺疊適繫結據決調衝兩採徹執徵競場樣極紅軍團舊陣藍飾雜幾寬亂牆貨靈圍盤豐佇倉額賽敵續歡鮮難絕負暢參頂屬擲處說話軸鑄藝聯躍";
    private const string SimplifiedCharacters = "药剂阶闪电游戏称内领资载败记录无运须写项储验证错误删规则吗动复请选择类达筛预设盖层撷网离线读异图关闭开启后页没时节点区频诊断标画显评权组踪会颜并档鉴还击传从迁尝试检栏产扫复制议码谢识实体条优顺换导头绘圆环边缘隐为签个词汇号险缀块径于数编辑单题态绑将键级杀价奖励观员装备渊谵机银铜圣别计镇统经战针寻触发输斗进见阈热准缩范钮种钟声铃哔骤视仅过来遥测务订国陆镜这萤独获门槛贴护兴挥师现与万转雾间厅脉辅宝维仪览汇库随赠注对应状连强侦轮终忆讯锚巅浏远许稳静划费变脑风剧报户详细尔炼顾总长伤继里折叠适系结据决调冲两采彻执征竞场样极红军团旧阵蓝饰杂几宽乱墙货灵围盘丰伫仓额赛敌续欢鲜难绝负畅参顶属掷处说话轴铸艺联跃";
    internal static IReadOnlyDictionary<char, char> TraditionalCharacterMap { get; } = BuildTraditionalCharacterMap();

    private static IReadOnlyDictionary<char, char> BuildTraditionalCharacterMap()
    {
        var map = new Dictionary<char, char>();
        for (var i = 0; i < Math.Min(TraditionalCharacters.Length, SimplifiedCharacters.Length); i++)
            map[TraditionalCharacters[i]] = SimplifiedCharacters[i];
        return new System.Collections.ObjectModel.ReadOnlyDictionary<char, char>(map);
    }

    // Entries absent from POE2DB's autocomplete list, plus short phrases which can occur inside a live label.
    // Complete POE2DB entries are always resolved before this fallback table.
    private static readonly (string En, string Zh)[] FallbackPairs =
    {
        ("The Arbiter of Ash", "灰燼仲裁者"), ("Xesht, We That Are One", "萬眾歸一．烈許"),
        ("Kosis, the Revelation", "天譴啟示．科賽斯"), ("Kosis, The Revelation", "天譴啟示．科賽斯"), ("The Bodach", "博德克"),
        ("Untainted Paradise", "純淨樂園"), ("Waystone", "換界石"), ("Waystones", "換界石"),
        // The atlas tile reader can expose this device as either a spaced English leaf or a
        // partially localized runtime label. Keep the full name together: translating only its
        // individual tokens used to leave the player-facing "Waygate 裝置 Base" mixed.
        ("Waygate Device Base", "躍遷門裝置基座"), ("Waygate 裝置 Base", "躍遷門裝置基座"),
        ("Waygate 装置 Base", "躍遷門裝置基座"), ("Waygate Device", "躍遷門裝置"),
        ("Waygate", "躍遷門"),
        // POE2 campaign/world-area names (the live memory reader returns the English
        // internal display name on some clients, so keep these explicit and stable).
        ("The Riverbank", "河畔"), ("Clearfell", "清澈郊野"), ("Mud Burrow", "泥濘地穴"),
        ("The Grelwood", "葛瑞爾林"), ("Grelwood", "葛瑞爾林"), ("The Red Vale", "赤色山谷"),
        ("Red Vale", "赤色山谷"), ("The Grim Tangle", "幽暗密林"),
        ("Cemetery of the Eternals", "永恆墓地"), ("Hunting Grounds", "狩獵場"),
        ("Freythorn", "弗雷桑"), ("Ogham Farmlands", "歐甘農地"), ("Ogham Village", "歐甘村"),
        ("The Manor Ramparts", "莊園城牆"), ("Ogham Manor", "歐甘莊園"),
        // Remaining world-area labels.  These are exact display-name aliases: translating the
        // complete phrase keeps proper names and hideout titles natural and prevents outputs
        // such as “該 Copper 城塞” when only individual words are known.
        ("[DNT-UNUSED] Precursor Forge", "［未使用］先驅熔爐"),
        ("[DNT-UNUSED] Vahi Loa", "［未使用］瓦希洛阿"),
        ("[DNT-UNUSED] Vastiri Outpost", "［未使用］瓦斯提里前哨"),
        ("[DNT] River Barrens", "［未使用］河流荒地"), ("[DNT] Ship", "［未使用］船艦"),
        ("Abandoned Prison", "棄置監獄"), ("Aggorat", "阿戈拉特"),
        ("All at Sea Hideout", "海上漂泊藏身處"), ("All Black", "全黑"),
        ("Alpine Plateau Hideout", "高山高原藏身處"), ("Ancestral Hideout", "先祖藏身處"),
        ("Apex of Filth", "污穢頂峰"), ("Arastas", "阿拉斯塔斯"),
        ("Arcane Isle Hideout", "秘法島嶼藏身處"), ("Arroyo", "溪谷"),
        ("Ashen Forest", "灰燼森林"), ("Atlas", "輿圖"), ("Atlas Hideout", "輿圖藏身處"),
        ("Atziri's Temple", "阿茲里的神殿"), ("Azurite Cavern Hideout", "青藍礦洞藏身處"),
        ("Beacon of Salvation Hideout", "救贖信標藏身處"), ("Black Cathedral Hideout", "黑色大教堂藏身處"),
        ("Bloodreaver Manor Hideout", "嗜血掠奪者莊園藏身處"),
        ("Boss Rush Area 1", "首領突襲區域 1"), ("Boss Rush Area 2", "首領突襲區域 2"),
        ("Boss Rush Area 3", "首領突襲區域 3"), ("Boundless Skies Hideout", "無垠天際藏身處"),
        ("Brinerot Cove", "布萊恩洛特海灣"), ("Buried Shrines", "埋藏神殿"),
        ("Canopy Hideout", "林冠藏身處"), ("Cataclysmic Hideout", "災變藏身處"),
        ("Celestial Nebula Hideout", "天界星雲藏身處"), ("Champion's Hideout", "冠軍藏身處"),
        ("Character Select", "角色選擇"), ("Chimeral Wetlands", "奇美拉濕地"),
        ("Chiyou Hideout", "蚩尤藏身處"), ("Civic Square Hideout", "市民廣場藏身處"),
        ("Crucible Hideout", "熔爐藏身處"), ("Dark Domain", "黑暗領域"),
        ("Darkwood Hideout", "黑木藏身處"), ("Decayed Laboratory", "腐朽實驗室"),
        ("Derelict Catacombs", "荒廢地下墓穴"), ("Deserted Post", "荒棄哨站"),
        ("Deshar", "德沙爾"), ("Design (Lite)", "設計（精簡版）"),
        ("Doomguard Hideout", "毀滅守衛藏身處"), ("Dreadnought", "無畏艦"),
        ("Druid Trailer", "德魯伊預告場景"), ("Eclipsed Hideout", "蝕影藏身處"),
        ("Endless Sands Hideout", "無盡沙海藏身處"), ("Entombed Hideout", "埋葬之地藏身處"),
        ("Etched Ravine", "鏤刻峽谷"), ("Eternal Wasteland Hideout", "永恆荒原藏身處"),
        ("Eye of Hinekora", "悉妮蔻拉之眼"), ("Famed Pond", "著名池塘"),
        ("Fortress", "堡壘"), ("Freight", "貨運站"), ("Furious Hideout", "狂怒藏身處"),
        ("Geode", "晶洞"), ("Ghost-lit Graveyard Hideout", "鬼火墓園藏身處"),
        ("Gilded Deposit", "鍍金礦藏"), ("Glacial Expanse Hideout", "冰川荒野藏身處"),
        ("Glacial Tarn", "冰川湖"), ("Gone Fishing", "釣魚去"), ("Grinding Hideout", "磨礪藏身處"),
        ("Halls of the Dead", "亡者大廳"), ("Hidden Aquifer", "隱藏含水層"),
        ("Holten", "霍爾滕"), ("Holten Estate", "霍爾滕莊園"), ("Howling Caves", "嚎叫洞穴"),
        ("Humanoid Pet Hideout", "人形寵物藏身處"), ("Indomitable Hideout", "不屈藏身處"),
        ("Infested Barrens", "受感染荒地"), ("Infinite Abyss Hideout", "無盡深淵藏身處"),
        ("Innocent Hideout", "無辜者藏身處"), ("Isle of Decay", "腐朽島"), ("Isle of Kin", "親族島"),
        ("Jiquani's Machinarium", "吉卡尼的機械迷城"), ("Jiquani's Sanctum", "吉卡尼聖所"),
        ("Journey's End", "旅途終點"), ("Jungle Clearing Hideout", "叢林空地藏身處"),
        ("Jungle Ruins", "叢林遺跡"), ("Kalguuran Tomb", "卡爾古爾墓塚"), ("Karst", "喀斯特"),
        ("Karui Boss Showcase", "卡魯首領展示"), ("Kedge Bay", "凱奇海灣"), ("Keth", "凱斯"),
        ("Kingsmarch", "金司馬區"), ("Kraken's Cove Hideout", "海妖海灣藏身處"),
        ("Kriar Peaks", "克里亞爾山峰"), ("Kriar Village", "克里亞爾村"),
        ("Library of Kamasa", "卡瑪薩圖書館"), ("Lightless Passage", "無光通道"),
        ("Loathsome Mire", "可憎泥沼"), ("Login Scene", "登入場景"), ("Lost Catacombs", "失落地下墓穴"),
        ("Mastodon Badlands", "猛獁荒地"), ("Mawdun Mine", "莫頓礦坑"), ("Mawdun Quarry", "莫頓採石場"),
        ("Mezzanine", "夾層"), ("Monolith Hideout", "豐碑藏身處"), ("Morbid Hideout", "病態藏身處"),
        ("Ngakanu", "恩加卡努"), ("NULL", "未知區域"), ("Overgrown Apex Hideout", "過度生長頂峰藏身處"),
        ("Path of Mourning", "哀悼之路"), ("Plateau of the Gods Hideout", "神祇高原藏身處"),
        ("Plunder's Point", "掠奪者岬"), ("Polaric Hideout", "極光藏身處"), ("Pools of Khatal", "卡塔爾池"),
        ("Precursor Tower", "先驅高塔"), ("Precursor Vault", "先驅寶庫"),
        ("Programming World", "程式設計世界"), ("Programming World (Lite)", "程式設計世界（精簡版）"),
        ("Qimah", "奇馬"), ("Qimah Reservoir", "奇馬水庫"), ("Rancid Nest", "腐臭巢穴"),
        ("Ravenous Hideout", "貪婪藏身處"), ("Red Queen's Chambers Hideout", "赤色女王密室藏身處"),
        ("Redeemer's Hideout", "救贖者藏身處"), ("Ritualist's Hideout", "儀式師藏身處"),
        ("Root Hollow", "根系空洞"), ("Runic Catacombs", "符文地下墓穴"),
        ("Sacrificial Apex Hideout", "獻祭頂峰藏身處"), ("Sandswept Marsh", "風沙沼澤"),
        ("Scorched Farmlands", "焦灼農地"), ("Searing Hideout", "灼熱藏身處"),
        ("Seething Hideout", "沸騰藏身處"), ("Sel Khari Sanctuary", "塞爾卡里聖所"),
        ("Shipwreck Hideout", "沉船藏身處"), ("Shoreline Hideout", "海岸線藏身處"),
        ("Shrike Island", "伯勞島"), ("Singing Caverns", "歌唱洞窟"), ("Skull of the Titan", "泰坦頭骨"),
        ("Smuggler's Den", "走私者巢穴"), ("Solitary Confinement", "單獨監禁"),
        ("Stale Crevice", "陳腐裂隙"), ("Stones of Serle", "瑟爾之石"),
        ("Submerged Hideout", "沉沒藏身處"), ("Sulphur Mines", "硫磺礦坑"),
        ("Sunken Palace Hideout", "沉沒宮殿藏身處"), ("Sunspire Hideout", "日耀尖塔藏身處"),
        ("Synthesis Hideout", "合成藏身處"), ("Tangled Hideout", "糾纏藏身處"),
        ("Tavern Hideout", "酒館藏身處"), ("Temple of Kopec", "科佩克神殿"), ("Terrace", "台地"),
        ("Thaumaturgical Hideout", "奇術藏身處"), ("The Ardura Caravan", "阿杜拉商隊"),
        ("The Azak Bog", "阿札克沼澤"), ("The Black Chambers", "黑暗密室"), ("The Blackwood", "黑木林"),
        ("The Bone Pits", "骸骨坑"), ("The Copper Citadel", "青銅城塞"), ("Copper Citadel", "青銅城塞"),
        ("The Cuachic Vault", "瓜奇克寶庫"), ("The Dreadnought Hideout", "無畏艦藏身處"),
        ("The Dreadnought's Wake", "無畏艦尾流"), ("The Drowned City", "溺沒之城"),
        ("The Excavation", "挖掘場"), ("The Galai Gates", "加萊之門"), ("The Glade", "林間空地"),
        ("The Halani Gates", "哈拉尼之門"), ("The Khari Bazaar", "卡里市集"),
        ("The Khari Crossing", "卡里通道"), ("The Lost City", "失落之城"),
        ("The Matlan Waterways", "馬特蘭水道"), ("The Molten Vault", "熔火寶庫"),
        ("The Spires of Deshar", "德沙爾尖塔"), ("The Titan Grotto", "泰坦洞窟"),
        ("The Trial of Chaos", "混沌試煉"), ("The Venom Crypts", "毒液墓穴"), ("The Voyage", "航程"),
        ("Timekeeper's Hideout", "守時者藏身處"), ("Titan Apex Hideout", "泰坦頂峰藏身處"),
        ("Towering Hideout", "高聳藏身處"), ("Traitor's Passage", "叛徒通道"),
        ("Tranquil Chamber", "寧靜密室"), ("Trial of the Ancestors", "先祖試煉"),
        ("Trial of the Sekhemas", "絲克瑪試煉"), ("Twisted Domain", "扭曲領域"),
        ("Twisted Hideout", "扭曲藏身處"), ("Urban Sprawl Hideout", "城市蔓延藏身處"),
        ("Utzaal", "烏札爾"), ("Valley of the Titans", "泰坦山谷"),
        ("Vast Plains Hideout", "廣袤平原藏身處"), ("Vastiri Outskirts", "瓦斯提里郊外"),
        ("Vastiri Plains Hideout", "瓦斯提里平原藏身處"), ("Vastiri Racecourse Hideout", "瓦斯提里賽馬場藏身處"),
        ("Volcanic Cave Hideout", "火山洞穴藏身處"), ("Volcanic Warrens", "火山巢穴"),
        ("Whakapanu Island", "瓦卡帕努島"), ("Wolvenhold", "狼族堡壘"), ("Yaochi Hideout", "瑤池藏身處"),
        // Curated combat modifiers, buffs and objective labels are also display-bound data.
        ("Volatile (explodes on death)", "易爆（死亡時爆炸）"), ("Reflects Damage", "反射傷害"),
        ("Cannot be Stunned", "無法被暈眩"), ("Extra Fast", "額外快速"), ("Extra Life", "額外生命"),
        ("Physical Damage Aura", "物理傷害光環"), ("Cold Damage Aura", "冰冷傷害光環"),
        ("Fire Damage Aura", "火焰傷害光環"), ("Lightning Damage Aura", "閃電傷害光環"),
        ("Energy Shield Aura", "能量護盾光環"), ("Mana Siphoner", "魔力虹吸"),
        ("Allies cannot Die", "盟友不會死亡"), ("Reduced Player AoE", "玩家範圍效果降低"),
        ("Extra Critical Strikes", "額外暴擊"), ("Grace", "優雅"), ("Haste", "迅捷"),
        ("Igniting Presence", "點燃光環"), ("Chilling Presence", "冰冷光環"),
        ("Shocking Presence", "感電光環"), ("Physical Aura", "物理光環"), ("Enraged", "狂怒"),
        ("Berserk", "狂暴"), ("Shielded", "護盾保護"), ("Unstoppable", "不可阻擋"),
        ("Temporal Bubble", "時間泡沫"), ("The Maven (Pinnacle Cast)", "釋界（巔峰施法）"),
        ("Seasonal event", "賽季事件"), ("Side boss / passive trial", "支線首領／被動試煉"),
        ("Optional side area", "可選支線區域"), ("Continue (zone exit)", "繼續（區域出口）"),
        ("SideBoss", "支線首領"), ("SideZone", "支線區域"), ("MainProgression", "主線進度"),
        ("SeasonalEvent", "賽季事件"),
        ("Find/summon/talk Una", "尋找／召喚／與尤娜交談"),
        ("Find / summon / talk Una", "尋找／召喚／與尤娜交談"),
        ("WhiteOtter", "白色水獺"), ("BlackOtter", "黑色水獺"),
        // Campaign landmark labels supplied by the offline route/landmark catalog.  These are
        // presentation labels (never metadata keys), so translating them here also covers the
        // in-game navigation menu and edge arrows when a client exposes the English label.
        ("Areagne's Hut (Support Gem Level 1 and Flasks)", "阿瑞根的小屋（1級輔助寶石與藥劑）"),
        ("Areagne's Hut", "阿瑞根的小屋"),
        ("The Corpse Tree (waypoint)", "屍骸之樹（傳送點）"),
        ("The Corpse Tree", "屍骸之樹"),
        ("The Moving Bramble (Skill Gem Level 2)", "移動荊棘（2級技能寶石）"),
        ("The Moving Branches (Skill Gem Level 2)", "移動枝條（2級技能寶石）"),
        ("The Moving Bramble", "移動荊棘"),
        ("The Moving Branches", "移動枝條"),
        ("Tree Of Souls Nail Stake", "靈魂之樹釘"),
        ("Tree of Souls Nail Stake", "靈魂之樹釘"),
        ("The Hooded One", "蒙面者"),
        ("Arcane's Hut", "奧術小屋"),
        ("Vaal Skeletal Squire", "瓦爾骷髏侍從"),
        ("Vaal Skeletal Archer", "瓦爾骷髏弓手"),
        ("Vaal Skeletal Warrior", "瓦爾骷髏戰士"),
        ("Necromancer Raisable", "死靈法師可復甦"),
        ("Bone Rabble Melee Range", "骨骸暴徒近戰範圍"),
        ("Attack Block 30Bypass 10", "攻擊格擋 30（穿透 10）"),
        ("Forbidden Rites", "禁忌儀式"),
        ("Forbidden Rites Alliance", "禁忌儀式聯盟"),
        // League names are shown inside the economy widget/API as display text.  Keep the
        // current PoE2 league fully localized instead of the mixed "符文 of Aldur" fallback
        // produced by translating only the first token.
        ("Runes of Aldur", "阿爾杜爾符文"),
        ("HC Runes of Aldur", "專家模式阿爾杜爾符文"),
        ("Support Gem Lv1", "1級輔助寶石"),
        ("Support Gem Level 1", "1級輔助寶石"),
        ("Skill Gem Lv1", "1級技能寶石"),
        ("Skill Gem Level 1", "1級技能寶石"),
        ("Skill Gem Lv2", "2級技能寶石"),
        ("Skill Gem Level 2", "2級技能寶石"),
        ("Res Ring", "抗性戒指"), ("Cold Res", "冰冷抗性"),
        ("Passive", "被動技能"), ("Flasks", "藥劑"), ("Flask", "藥劑"),
        ("Waypoint", "傳送點"), ("Area Transition", "區域出口"),
        // 常見藏身處互動物與 NPC。這些名稱有些版本不在 POE2DB 自動完成表中，
        // 仍然必須在導航目標與覆蓋層中保持一致的繁體中文顯示。
        ("Verisium Anvil", "維瑞西姆鐵砧"), ("Salvage Bench", "拆解台"),
        ("Reforging Bench", "重鑄台"), ("Crafting Bench", "工藝台"),
        ("Multiplex Portal", "多重傳送門"), ("Hideout Healing Well", "藏身處治療井"),
        ("Relic Locker", "遺物櫃"), ("Guild Stash", "公會倉庫"), ("Stash", "倉庫"),
        ("Map Device", "地圖裝置"), ("Alva", "阿瓦"), ("Zelina", "塞莉娜"),
        ("Zolin", "佐林"), ("Doryani", "多里亞尼"), ("Ange", "安吉"),
        ("Jado", "賈多"), ("Farrow", "法羅"),
        ("Una", "尤娜"), ("Summon Una", "召喚尤娜"), ("Checkpoint", "檢查點"),
        ("Tree Of Souls Roots", "靈魂之樹根系"), ("Tree of Souls Roots", "靈魂之樹根系"),
        ("TreeOfSoulsRoots", "靈魂之樹根系"), ("Count's Sentencing", "伯爵的宣判"),
        ("Count’s Sentencing", "伯爵的宣判"), ("Roots", "根系"),
        ("Maps", "異界地圖"), ("The Burning Monolith", "燃燒豐碑"),
        ("Map Boss", "地圖頭目"), ("Powerful Map Boss", "強大地圖頭目"),
        ("Lightning Wraith", "雷電惡靈"), ("Guardian Turtle", "守護之龜"),
        ("Area Transition", "區域出口"), ("Map Device", "地圖裝置"), ("Waypoint", "傳送點"),
        ("Boss Arena", "首領競技場"), ("Powerful Map Boss", "強大地圖頭目"),
        ("Strongboxes", "保險箱"), ("Strongbox", "保險箱"), ("Waystone", "換界石"),
        // Live entity labels frequently come from the metadata display-name field rather than
        // the POE2DB autocomplete table. Keep these short combat/radar terms localized too, so
        // an otherwise translated overlay does not fall back to English for a spirit or rarity.
        ("Tormented Spirit", "折磨之魂"), ("Tormented Spirits", "折磨之魂"),
        ("Possessed Spirit", "附身之魂"), ("Spirit", "靈魂"),
        ("Daemon", "惡魔"), ("Area Transition", "區域出口"),
        ("Point of Interest", "興趣點"), ("Rogue Exile", "流放者"),
        ("Rare Elite", "稀有精英"), ("Elite", "精英"),
        ("Expedition", "死境探險"), ("Breach", "裂痕"), ("Delirium", "譫妄"),
        ("Ritual", "祭祀"), ("Essence", "精髓"), ("Shrine", "神殿"), ("Abyss", "深淵"),
        ("Incursion", "入侵"), ("Legion", "軍團"), ("Citadel", "城塞"), ("Tower", "高塔"),
        ("Bosses", "首領"), ("Boss", "首領"), ("Monsters", "怪物"), ("Monster", "怪物"),
        ("Unique", "傳奇"), ("Rare", "稀有"), ("Magic", "魔法"), ("Normal", "普通"),
        ("Chest", "寶箱"), ("Transition", "出口"), ("Area", "區域"), ("Zone", "區域"),
        ("chests", "寶箱"), ("chest", "寶箱"), ("Point of Interest", "興趣點"),
        ("Quest", "任務"), ("Complete", "完成"), ("Runestone (League Event)", "符文石（聯盟事件）"),
        ("Runestone", "符文石"), ("Essence Monolith", "精髓石碑"), ("Lightless", "無光者"),
        // Campaign and live overlay labels that are not present in the shared POE2DB autocomplete
        // list. These are player-visible game names, so keep them Traditional Chinese.
        ("Tomb of the Consort", "王妃之墓"), ("Mausoleum of the Praetor", "執政官陵墓"),
        ("Arena / Hunting Grounds", "競技場／狩獵場"), ("Hunting Grounds", "狩獵場"),
        ("Beira of the Rotten", "腐敗的貝拉"), ("Beira of the Rotten (10% Cold Res)", "腐敗的貝拉（10% 冰冷抗性）"),
        ("Dungeon entrance down", "地城下行入口"), ("Dungeon entrance up", "地城上行入口"),
        ("Armoury", "軍械庫"), ("Flask buff - Need key", "藥劑增益－需要鑰匙"),
        ("Crafting Bench", "工藝台"), ("Reforging Bench", "重鑄台"), ("Guild Stash", "公會倉庫"),
        ("Generic Buff Aura", "通用增益光環"), ("Schemer's Portal", "陰謀家的傳送門"),
        ("Schemers Portal", "陰謀家的傳送門"), ("Rune Interactable", "祭祀符文互動物"),
        ("祭祀 Rune Interactable", "祭祀符文互動物"),
        ("Rune Object", "祭祀符文物件"), ("Permanent Server Effect", "永久伺服器效果"),
        ("World Item", "地面物品"), ("Check Point", "檢查點"), ("Checkpoint", "檢查點"),
        ("Encounter", "遭遇戰"), ("Expedition 2 Encounter", "死境探險遭遇戰"),
        ("死境探險 2 Encounter", "死境探險遭遇戰"),
        ("Vaal Savage", "瓦爾野蠻人"), ("Black Otter", "黑色水獺"), ("White Otter", "白色水獺"),
        ("AreaTransition", "區域出口"), ("Makoru", "馬可魯"), ("Rennly", "倫利"),
        ("Renly", "倫利"), ("Finn", "芬恩"), ("Cyclonic", "旋風"),
        ("Sky", "天空"), ("Soul", "靈魂"), ("Tomb", "墓塚"),
        ("Mausoleum", "陵墓"), ("Arena", "競技場"),
        ("Level", "等級"), ("Energy Shield", "能量護盾"), ("Life", "生命"), ("Mana", "魔力"),
        ("Damage", "傷害"), ("Fire", "火焰"), ("Cold", "冰冷"), ("Lightning", "閃電"),
        ("Chaos", "混沌"), ("Physical", "物理"), ("movement speed", "移動速度"),
        // Entity-name fragments emitted by the live radar.  These are deliberately kept at
        // the display boundary: the metadata path and the classifier keys remain English.
        // A few complete labels are included first so the result reads naturally when a
        // runtime name is made from several otherwise-unknown words.
        ("Brequel Initiator", "布雷奎爾啟動者"), ("Deadly Breach Detonator", "致命裂痕引爆器"),
        ("Expedition Detonator", "死境探險引爆器"), ("Ezomyte Statue Green", "艾茲麥綠色石像"),
        ("Slithering Snakes", "蜿蜒蛇群"), ("Water Plane", "水之平原"),
        ("Servi Child Ziggurat Encampment", "瑟維孩童（高地神塔營地）"),
        ("Time Present", "當下時間"), ("Armourer", "護甲師"),
        // Expedition runes and reward names used by the monolith offer panel.
        ("Adaptive", "適應"), ("Rebirth", "重生"), ("Gasp", "喘息"), ("Celestial", "天界"),
        ("Tidal", "潮汐"), ("Protective", "防護"), ("Vision", "視界"), ("Tempest", "風暴"),
        ("Prismatic", "稜彩"), ("Moon", "月"), ("Bloodletting", "放血"), ("Rage", "暴怒"),
        ("Electrocuting", "感電"), ("Opulent", "豐饒"), ("Momentum", "動能"), ("Arcane", "秘法"),
        ("Ward", "守護"), ("Earth", "大地"), ("Stone", "石"), ("Death", "死亡"),
        ("Bond", "羈絆"), ("Lesser", "次級"), ("Greater", "高階"), ("Rune", "符文"),
        ("Verisium Pile", "維瑞西姆礦堆"),
        ("resistances", "抗性"), ("resistance", "抗性"), ("increased", "增加"),
        ("reduced", "降低"), ("maximum", "最大"), ("nearby", "附近"), ("Objective", "目標"),
        ("Target", "目標"), ("Navigation", "導航"), ("Path", "路徑"), ("Loading", "載入中"),
        ("Unknown", "未知"), ("Current", "目前"), ("Completed", "已完成"),
        ("Complete", "完成"), ("Accessible", "可進入"), ("Hidden", "隱藏"), ("Locked", "鎖定"),
        ("Unidentified", "未鑑定"), ("Currency", "通貨"), ("Soul Core", "靈魂核心"),
        ("Uncut Gem", "未切割寶石"), ("Support Gem", "輔助寶石"), ("Exalted Orb", "崇高石"),
        ("Divine Orb", "神聖石"), ("Rewards", "獎勵"), ("Reward", "獎勵"), ("Tier", "階級"),
        ("Phases", "階段"), ("Phase", "階段"), ("Flask", "藥劑"),
        ("Xesht, We That Are One (Breachlord)", "萬眾歸一．烈許（裂痕領主）"),
        ("Kosis, the Revelation (Delirium)", "天譴啟示．科賽斯（譫妄）"),
        ("The Bodach (Pinnacle Cast)", "博德克（巔峰施法）"),
        ("Volcanic Slam", "火山猛擊"), ("Meteor call", "隕石召喚"), ("Phase 2 arena ignite", "第二階段競技場點燃"),
        ("Hand-of-Xesht ground slam", "烈許之手地面猛擊"), ("Chaos rift pulses", "混沌裂隙脈衝"), ("Grab attack telegraph", "抓取攻擊預兆"),
        ("Freezing pulse cone", "冰凍脈衝錐形波"), ("Mirror-image summons", "鏡像召喚"), ("Sanity-drain aura", "理智消耗光環"),
        ("Memory-game phase", "記憶遊戲階段"), ("Ball-lightning line", "球狀閃電直線"), ("Meteor circle summon", "隕石圓環召喚"),
        ("Overhead crush", "頭頂重擊"), ("Cold-lightning storm", "冰冷閃電風暴"), ("Grab-throw combo", "抓取投擲連擊"),
        ("sidestep the red cone before it lands", "在紅色錐形區落下前側身躲避"),
        ("do not stand under the shadow marker", "不要站在陰影標記下方"),
        ("walk clockwise around the burning ring", "沿燃燒圓環順時針移動"),
        ("leave the marked circle before it detonates", "在爆炸前離開標記圓圈"),
        ("dash out before the arm closes", "手臂合攏前衝刺離開"),
        ("do not stand in the frost trail", "不要站在冰霜軌跡中"),
        ("kill the correct copy", "擊殺正確的分身"), ("stack away when the screen desaturates", "畫面褪色時遠離疊層"),
        ("repeat the flashed pattern", "重複閃現的圖案"), ("leap sideways before the ring closes", "圓環閉合前向側面跳躍"),
        ("the safe zone is the smallest circle", "最小圓圈才是安全區"),
        ("dash out of the ground shadow before it lands", "地面陰影落下前衝刺離開"),
        ("stand in the safe corridor between arcs", "站在弧線之間的安全通道"), ("cannot be blocked", "無法格擋"),
        ("Enrage", "狂怒"), ("Arena floor ignites in rotating rings", "競技場地面以旋轉圓環點燃"),
        ("Summons Hands", "召喚之手"), ("Breach walls close in", "裂痕牆壁向內收縮"), ("Mirror-images spawn each 10 s", "鏡像每 10 秒生成"),
        ("Sanity-drain aura permanent", "理智消耗光環永久存在"), ("Memory phase", "記憶階段"), ("Adds spawn", "增援生成"),
        ("Berserk", "狂暴"), ("Phase 2", "第二階段"), ("Phase 1", "第一階段"), ("movement skill up", "準備移動技能"),
        ("pinnacle", "巔峰"), ("AtlasBoss", "異界地圖首領"), ("Prioritize", "優先"),
        ("fire-resist flask uptime", "火焰抗性藥劑持續時間"), ("ignite pulses in phase 2 will chunk uncapped builds", "第二階段的點燃脈衝會重創抗性不足的配置"),
        ("Chaos resist matters", "混沌抗性很重要"), ("deals more chaos than most atlas bosses", "造成的混沌傷害高於多數異界地圖首領"),
        ("Bring at least one chaos-flask or chaos-res on gear", "至少準備一瓶混沌藥劑或在裝備上堆疊混沌抗性"),
        ("Freeze immunity is worth slotting", "值得配置免疫冰凍"), ("Cold-resist over-cap is the difference between a chip and a chunk", "冰冷抗性超額決定了輕傷或重創"),
        ("Balanced-elemental profile", "元素傷害平均"), ("over-cap all three elements", "三種元素抗性都需要超額"),
        ("Movement flask crucial for the ball-lightning phase", "球狀閃電階段需要移動藥劑"),
        ("Physical damage reduction", "物理傷害減免"), ("armour or evasion", "護甲或閃避"),
        ("matters more than element resist here", "在此處比元素抗性更重要"), ("Adds spawn", "增援生成"),
        ("Path of Exile 2 is not running.", "流亡黯道 2 尚未執行。"),
        ("Reading your character but no map data — deep reads may be stale after a patch.", "已讀取角色資料，但沒有地圖資料；更新後的深層記憶體讀取可能已失效。"),
        ("POE2GPS is up to date but can't read the game — try restarting in a loaded zone.", "POE2GPS 已是最新版本，但無法讀取遊戲；請在已載入區域重新啟動程式。"),
        ("POE2GPS can't read Path of Exile 2 — it likely just updated; a fix is coming.", "POE2GPS 無法讀取流亡黯道 2；遊戲可能剛更新，等待對應修正。"),
        ("Radar's been offline a while. Update available — download:", "雷達已離線一段時間。已有可用更新 — 下載："),
        ("Radar's been offline a while — if you're in a zone, a patch may have shifted offsets. Check for a new release.", "雷達已離線一段時間；若目前在遊戲區域，可能是更新變更了偏移，請檢查新版本。"),
        ("Update available — download:", "已有可用更新 — 下載："),
        ("POE2GPS can't find Path of Exile 2's game state — it likely just updated. Check for a new release.", "POE2GPS 找不到流亡黯道 2 的遊戲狀態；遊戲可能剛更新，請檢查新版本。"),
        ("Still can't read the game — if you're in a zone, POE2GPS may need an update. Check for a new release.", "仍然無法讀取遊戲；若目前在遊戲區域，POE2GPS 可能需要更新，請檢查新版本。"),
        ("Connecting to Path of Exile 2 — load into a zone.", "正在連線至流亡黯道 2 — 請進入遊戲區域。"),
        ("kill blockers first", "先擊殺阻擋者"), ("Breach walls close in", "裂痕牆壁向內收縮"),
        ("arena shrinks", "競技場縮小"), ("focus real one", "集中攻擊真身"), ("no gold shimmer", "沒有金色閃光"),
        ("keep chaos-recovery uptime", "維持混沌恢復效果"), ("one flash sequence", "一次閃現序列"),
        ("three flashes", "三次閃現"), ("five flashes", "五次閃現"), ("miss any and lose ~25% HP", "漏掉任何一次會失去約 25% 生命"),
        ("Explosive", "爆炸"), ("Carver Tribe Wicker Basket", "雕刻者部族柳條籃"),
        ("Stacked Boulder", "堆疊巨石"), ("Pirate Corpse", "海盜屍體"), ("Stone Altar", "石祭壇"),
        ("Spirit of Balbala", "巴爾巴拉之魂"), ("Spirit Of Balbala", "巴爾巴拉之魂"),
        ("Vaal Embalmed Archer", "瓦爾防腐弓箭手"), ("Balbala", "巴爾巴拉"), ("Atziri", "阿茲里"),
        ("Kirac", "基拉克"), ("Site", "地點"), ("Legacy", "舊版"), ("League", "聯盟"),
        ("Classify", "分類"), ("Show Name", "顯示名稱"), ("Show label", "顯示標籤"),
        ("Extra reward", "額外獎勵"), ("Forbidden Rites", "禁忌儀式"),
        ("Site (legacy Monster)", "地點（舊版怪物）"), ("Site (legacy monster)", "地點（舊版怪物）"),
    };

    // A few POE1 names are present in the shared POE2DB autocomplete catalog under the same
    // key. POE2DB's POE2 pages use the following terms; apply these exact aliases before the
    // shared catalog so a stale POE1 entry can never leak into the overlay.
    private static readonly IReadOnlyDictionary<string, string> Poe2Aliases =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["Map Device"] = "地圖裝置",
            ["Maps"] = "異界地圖",
            ["Waystone"] = "換界石",
            ["Waystones"] = "換界石",
            ["Untainted Paradise"] = "純淨樂園",
            ["The Burning Monolith"] = "燃燒豐碑",
            ["The Arbiter of Ash"] = "灰燼仲裁者",
            ["The Riverbank"] = "河畔",
            ["Clearfell"] = "清澈郊野",
            ["Mud Burrow"] = "泥濘地穴",
            ["The Grelwood"] = "葛瑞爾林",
            ["Grelwood"] = "葛瑞爾林",
            ["The Red Vale"] = "赤色山谷",
            ["Red Vale"] = "赤色山谷",
            ["The Grim Tangle"] = "幽暗密林",
            ["Cemetery of the Eternals"] = "永恆墓地",
            ["Hunting Grounds"] = "狩獵場",
            ["Freythorn"] = "弗雷桑",
            ["Ogham Farmlands"] = "歐甘農地",
            ["Ogham Village"] = "歐甘村",
            ["The Manor Ramparts"] = "莊園城牆",
            ["Ogham Manor"] = "歐甘莊園",
            ["Find/summon/talk Una"] = "尋找／召喚／與尤娜交談",
            ["Find / summon / talk Una"] = "尋找／召喚／與尤娜交談",
            ["WhiteOtter"] = "白色水獺",
            ["BlackOtter"] = "黑色水獺",
            ["Kosis, the Revelation"] = "天譴啟示．科賽斯",
            ["Kosis, The Revelation"] = "天譴啟示．科賽斯",
            ["Xesht, We That Are One"] = "萬眾歸一．烈許",
            ["The Bodach"] = "博德克",
        };

    private static readonly IReadOnlyDictionary<string, string> Phrases = FallbackPairs
        .GroupBy(pair => pair.En, StringComparer.OrdinalIgnoreCase)
        .ToDictionary(group => group.Key, group => group.Last().Zh, StringComparer.OrdinalIgnoreCase);

    private static readonly Regex ReplacementPattern = new(
        "(?<![A-Za-z])(?:" + string.Join('|', Phrases.Keys
            .OrderByDescending(key => key.Length).Select(Regex.Escape)) + ")(?![A-Za-z])",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled,
        TimeSpan.FromMilliseconds(100));
    private static readonly Regex ActPattern = new(@"\bAct\s+(?<n>[0-9]+)\b", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);
    private static readonly Regex IdentifierBoundary = new(
        @"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])",
        RegexOptions.CultureInvariant | RegexOptions.Compiled);
    private static readonly Regex DynamicWordPattern = new(
        @"(?<![A-Za-z])(?<word>[A-Za-z][A-Za-z0-9']*)(?![A-Za-z])",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    /// <summary>The effective display-name dictionary shared with the browser; POE2 aliases
    /// have exactly the same precedence as the desktop overlay.</summary>
    public static IReadOnlyDictionary<string, string> NameTranslations { get; } = BuildNameTranslations();

    // Entity metadata often contains a runtime-created PascalCase label that has no exact POE2DB
    // entry (for example `AreaTransitionExit3` or `AncientBeacon`).  Reuse the catalog's
    // single-word entries plus a small set of stable radar terms after splitting the identifier;
    // exact phrases above always win, so ordinary game names keep their curated translation.
    private static readonly (string En, string Zh)[] DynamicRadarPairs =
    {
        ("AreaTransition", "區域出口"), ("ExitPortal", "出口傳送門"), ("AreaExit", "區域出口"),
        ("Entrance", "入口"), ("Exit", "出口"), ("Door", "門"), ("Gate", "門"),
        ("Portal", "傳送門"), ("Waygate", "躍遷門"), ("Device", "裝置"), ("Base", "基座"),
        ("Chest", "寶箱"), ("Chests", "寶箱"),
        ("Strongbox", "保險箱"), ("Cache", "藏寶箱"), ("Locker", "櫃"),
        ("Waypoint", "傳送點"), ("Checkpoint", "檢查點"), ("Shrine", "神殿"),
        ("Ritual", "祭祀"), ("Breach", "裂痕"), ("Expedition", "死境探險"),
        ("Daemon", "惡魔"), ("Monster", "怪物"), ("Monsters", "怪物"),
        ("Npc", "非玩家角色"), ("NPC", "非玩家角色"), ("Object", "物件"),
        ("Summoned", "召喚"), ("Treasure", "寶藏"), ("Ancient", "遠古"),
        ("Broken", "破損"), ("Unopened", "未開啟"), ("Opened", "已開啟"),
        // Common live combat/entity tokens absent from the POE2DB exact-name list.
        ("Vaal", "瓦爾"), ("Gold", "黃金"), ("Stacked", "堆疊"), ("Boulder", "巨石"),
        ("Tendril", "觸手"), ("Sentinel", "守望"), ("Oil", "油"), ("Ground", "地面"),
        ("Hideout", "藏身處"), ("Blank", "空白"), ("Fire", "火焰"), ("Black", "黑色"), ("White", "白色"),
        ("Otter", "水獺"), ("Multiplex", "多重"), ("Bench", "工作台"), ("Ravine", "溪谷"),
        ("Mossy", "覆苔"), ("Goblin", "哥布林"), ("Rock", "岩石"), ("Pile", "堆"),
        ("Magic", "魔法"), ("Rare", "稀有"), ("And", "與"),
        // Deep fallback vocabulary for names generated by PoE2's encounter/entity
        // components.  POE2DB contains many complete names but not every component word;
        // translating these tokens prevents mixed labels such as “Ezomyte Statue Green”
        // from leaking into the radar while leaving proper-name spellings untouched.
        ("Brequel", "布雷奎爾"), ("Initiator", "啟動者"), ("Detonator", "引爆器"),
        ("Deadly", "致命"), ("Ezomyte", "艾茲麥"), ("Statue", "石像"),
        ("Green", "綠色"), ("Slithering", "蜿蜒"), ("Snakes", "蛇群"),
        ("Water", "水"), ("Plane", "平原"), ("Servi", "瑟維"), ("Child", "孩童"),
        ("Ziggurat", "高地神塔"), ("Encampment", "營地"), ("Time", "時間"),
        ("Present", "當下"), ("Armourer", "護甲師"), ("Armourers", "護甲師"),
        ("Armour", "護甲"), ("Armoured", "裝甲"), ("Breached", "裂痕"),
        ("Breach", "裂痕"), ("Rift", "裂隙"), ("Crack", "裂口"),
        ("Initiate", "啟動"), ("Activator", "啟動器"), ("Trigger", "觸發器"),
        ("Guardian", "守護者"), ("Guard", "守衛"), ("Warrior", "戰士"),
        ("Archer", "弓箭手"), ("Caster", "施法者"), ("Mage", "法師"),
        ("Rogue", "盜賊"), ("Knight", "騎士"), ("Priest", "祭司"),
        ("Priestess", "女祭司"), ("Captain", "隊長"), ("Commander", "指揮官"),
        ("Soldier", "士兵"), ("Scout", "斥候"), ("Hunter", "獵人"),
        ("Beast", "野獸"), ("Serpent", "巨蛇"), ("Snake", "蛇"),
        ("Spider", "蜘蛛"), ("Wolf", "狼"), ("Bear", "熊"), ("Rat", "鼠"),
        ("Bird", "鳥"), ("Crab", "螃蟹"), ("Toad", "蟾蜍"), ("Turtle", "龜"),
        ("Golem", "魔像"), ("Construct", "構造體"), ("Sentinel", "哨衛"),
        ("Servitor", "侍從"), ("Minion", "僕從"), ("Summoner", "召喚師"),
        ("Summon", "召喚"), ("Summoned", "已召喚"), ("Raised", "復甦"),
        ("Risen", "復甦"), ("Ancient", "遠古"), ("Eternal", "永恆"),
        ("Forgotten", "遺忘"), ("Mysterious", "神秘"), ("Nameless", "無名"),
        ("Corrupted", "腐化"), ("Fallen", "墮落"), ("Raging", "狂怒"),
        ("Frozen", "冰凍"), ("Burning", "燃燒"), ("Chilling", "冰冷"),
        ("Volatile", "易爆"), ("Explosive", "爆炸"), ("Toxic", "劇毒"),
        ("Poisonous", "有毒"), ("Blood", "鮮血"), ("Bone", "骨骸"),
        ("Flesh", "血肉"), ("Soul", "靈魂"), ("Spirit", "靈魂"),
        ("Shadow", "暗影"), ("Light", "光明"), ("Dark", "黑暗"),
        ("Fire", "火焰"), ("Ice", "冰霜"), ("Lightning", "閃電"),
        ("Thunder", "雷霆"), ("Storm", "風暴"), ("Flame", "火焰"),
        ("Ash", "灰燼"), ("Smoke", "煙霧"), ("Cloud", "雲霧"),
        ("Water", "水"), ("Earth", "大地"), ("Stone", "岩石"),
        ("Crystal", "水晶"), ("Metal", "金屬"), ("Iron", "鐵"),
        ("Golden", "黃金"), ("Silver", "白銀"), ("Black", "黑色"),
        ("White", "白色"), ("Red", "紅色"), ("Blue", "藍色"),
        ("Green", "綠色"), ("Purple", "紫色"), ("Great", "偉大"),
        ("Grand", "宏偉"), ("Lesser", "次級"), ("Greater", "高階"),
        ("First", "第一"), ("Second", "第二"), ("Third", "第三"),
        ("Last", "最後"), ("Present", "當下"), ("Past", "過去"),
        ("Future", "未來"), ("Time", "時間"), ("Morning", "早晨"),
        ("Evening", "夜晚"), ("Night", "夜晚"), ("Day", "日"),
        ("Door", "門"), ("Gate", "門"), ("Wall", "牆"), ("Lever", "拉桿"),
        ("Mechanism", "機關"), ("Machine", "機械"), ("Device", "裝置"),
        ("Beacon", "信標"), ("Relay", "中繼站"), ("Altar", "祭壇"),
        ("Shrine", "神殿"), ("Obelisk", "方尖碑"), ("Totem", "圖騰"),
        ("Statue", "石像"), ("Pillar", "石柱"), ("Bell", "鐘"),
        ("Book", "書籍"), ("Journal", "日誌"), ("Letter", "信件"),
        ("Message", "訊息"), ("Writings", "文字"), ("Carving", "雕刻"),
        ("Etchings", "蝕刻"), ("Offering", "供品"), ("Sacrificial", "獻祭"),
        ("Heart", "心臟"), ("Core", "核心"), ("Fragment", "碎片"),
        ("Remnant", "殘餘物"), ("Relic", "遺物"), ("Idol", "偶像"),
        ("Chest", "寶箱"), ("Strongbox", "保險箱"), ("Locker", "櫃"),
        ("Stash", "倉庫"), ("Cache", "藏寶箱"), ("Pile", "堆"), ("Boulder", "巨石"),
        ("Workbench", "工作台"), ("Bench", "工作台"), ("Armoury", "軍械庫"),
        ("Encampment", "營地"), ("Camp", "營地"), ("Village", "村落"),
        ("Town", "城鎮"), ("Harbour", "港口"), ("Refuge", "庇護所"),
        ("Temple", "神殿"), ("Chapel", "小教堂"), ("Mausoleum", "陵墓"),
        ("Tomb", "墓塚"), ("Grave", "墓地"), ("Cemetery", "墓園"),
        ("Arena", "競技場"), ("Dungeon", "地城"), ("Cavern", "洞窟"),
        ("Cave", "洞穴"), ("Forest", "森林"), ("Jungle", "叢林"),
        ("Desert", "沙漠"), ("Ravine", "峽谷"), ("River", "河流"),
        ("Lake", "湖泊"), ("Marsh", "沼澤"), ("Swamp", "沼澤"),
        ("Peak", "山峰"), ("Mountain", "山脈"), ("Grove", "林地"),
        ("Plane", "平原"), ("Field", "原野"), ("Grounds", "獵場"),
        ("North", "北方"), ("South", "南方"), ("East", "東方"), ("West", "西方"),
        ("Entrance", "入口"), ("Exit", "出口"), ("Transition", "區域出口"),
        ("Portal", "傳送門"), ("Waypoint", "傳送點"), ("Checkpoint", "檢查點"),
        ("Return", "返回"), ("Descend", "下降"), ("Ascend", "上升"),
        ("Open", "開啟"), ("Opened", "已開啟"), ("Closed", "已關閉"),
        ("Locked", "已鎖定"), ("Unlocked", "已解鎖"), ("Unopened", "未開啟"),
        ("Activate", "啟用"), ("Deactivate", "停用"), ("Destroy", "摧毀"),
        ("Break", "破壞"), ("Broken", "破損"), ("Repair", "修復"),
        ("Protect", "保護"), ("Defend", "防守"), ("Attack", "攻擊"),
        ("Dead", "死亡"), ("Death", "死亡"), ("Alive", "存活"),
        ("Rare", "稀有"), ("Magic", "魔法"), ("Normal", "普通"), ("Unique", "傳奇"),
        ("Elite", "精英"), ("Boss", "首領"), ("Monster", "怪物"), ("NPC", "非玩家角色"),
        ("Object", "物件"), ("World", "世界"), ("Item", "物品"), ("Ground", "地面"),
        ("Player", "玩家"), ("Character", "角色"), ("Enemy", "敵人"),
        ("Friendly", "友方"), ("Hostile", "敵對"), ("Neutral", "中立"),
        ("Unknown", "未知"), ("Mysterious", "神秘"), ("Placeholder", "佔位符"),
        ("Area", "區域"), ("Zone", "區域"), ("Level", "等級"), ("Tier", "階級"),
        ("Map", "地圖"), ("Maps", "異界地圖"), ("Waystone", "換界石"),
        ("Objective", "目標"), ("Target", "目標"), ("Navigation", "導航"),
        ("Path", "路徑"), ("Distance", "距離"), ("Current", "目前"),
        ("Complete", "完成"), ("Completed", "已完成"), ("Accessible", "可進入"),
        ("Hidden", "隱藏"), ("Visible", "可見"), ("Loading", "載入中"),
        ("Reward", "獎勵"), ("Rewards", "獎勵"), ("Currency", "通貨"),
        ("Uncut", "未切割"), ("Gem", "寶石"), ("Gems", "寶石"), ("Rune", "符文"),
        ("Runestone", "符文石"), ("Essence", "精髓"), ("Breach", "裂痕"),
        ("Expedition", "死境探險"), ("Ritual", "祭祀"), ("Delirium", "譫妄"),
        ("Abyss", "深淵"), ("Incursion", "入侵"), ("Legion", "軍團"),
        ("Citadel", "城塞"), ("Tower", "高塔"), ("Strongholds", "要塞"),
        ("Affliction", "苦痛"), ("Blight", "凋落"), ("Heist", "劫盜"),
        ("Harvest", "豐收"), ("Delve", "挖掘"), ("Mechanic", "機制"),
        ("Encounter", "遭遇戰"), ("Event", "事件"), ("League", "聯盟"),
        ("Initiator", "啟動者"), ("Detonator", "引爆器"), ("Trigger", "觸發器"),
        ("Summon", "召喚"), ("Skill", "技能"), ("Skills", "技能"), ("Aura", "光環"),
        ("Buff", "增益效果"), ("Debuff", "減益效果"), ("Effect", "效果"),
        ("Damage", "傷害"), ("Attack", "攻擊"), ("Spell", "法術"), ("Projectile", "投射物"),
        ("Melee", "近戰"), ("Ranged", "遠程"), ("Physical", "物理"), ("Elemental", "元素"),
        ("Chaos", "混沌"), ("Resistance", "抗性"), ("Resistances", "抗性"),
        ("Life", "生命"), ("Mana", "魔力"), ("Energy", "能量"), ("Shield", "護盾"),
        ("Speed", "速度"), ("Movement", "移動"), ("Critical", "暴擊"),
        ("Increased", "增加"), ("Reduced", "降低"), ("Maximum", "最大"),
        ("Nearby", "附近"), ("Greater", "高階"), ("Lesser", "次級"),
        ("Volatile", "易爆"), ("Shaped", "塑形"), ("Transcendent", "超越"),
        ("Present", "當下"), ("Future", "未來"), ("Past", "過去"),
        // Safe connective words are only applied by LocalizeDynamicLabel (never to a
        // metadata path).  Without them labels containing commas/articles remained half
        // English, e.g. “Statue of the Vaal Oversoul” or “Alva, Master Explorer”.
        ("The", "該"), ("Of", "的"), ("To", "至"), ("In", "在"), ("On", "於"),
        ("And", "與"), ("A", "一個"), ("It", "它"), ("That", "該"), ("Was", "曾是"),
        ("Your", "你的"), ("Place", "位置"), ("Group", "群組"), ("Event", "事件"),
        ("March", "三月"), ("Race", "賽事"), ("Master", "大師"), ("Explorer", "探險家"),
        ("Apparition", "幻影"), ("Queen", "女王"), ("Royal", "皇室"), ("Guild", "公會"),
        ("Embalmed", "防腐"), ("Manifesto", "宣言"), ("Pure", "純粹"), ("Goddess", "女神"),
        ("Voice", "聲音"), ("Keeper", "守衛者"), ("Order", "教團"), ("Orders", "命令"),
        ("Declaration", "宣言"), ("Decree", "法令"), ("Proclamation", "公告"),
        ("Testament", "遺訓"), ("Carvings", "雕刻"), ("Blacksmith", "鐵匠"),
        ("Construct", "構造體"), ("Crawler", "爬行者"), ("Companion", "同伴"),
        ("Console", "控制台"), ("Corpse", "屍體"), ("Decoration", "裝飾"),
        ("Disciple", "門徒"), ("Engineer", "工程師"), ("Fragment", "碎片"),
        ("Impaler", "穿刺者"), ("Knowledge", "知識"), ("Legacy", "傳承"),
        ("Living", "活體"), ("Lost", "失落"), ("Merchant", "商人"), ("Mirage", "幻象"),
        ("Mystic", "神秘者"), ("Offering", "供品"), ("Priest", "祭司"),
        ("Ravager", "掠奪者"), ("Rite", "儀式"), ("Runed", "符文"), ("Runic", "符文"),
        ("Seal", "封印"), ("Smith", "鐵匠"), ("Soldier", "士兵"), ("Spire", "尖塔"),
        ("Stalker", "潛伏者"), ("Tome", "典籍"), ("Undead", "亡靈"), ("Vile", "邪惡"),
        ("Warning", "警告"), ("Weapon", "武器"), ("Well", "水井"), ("Wise", "智者"),
        ("Woman", "女性"), ("Man", "男性"), ("Ancestor", "祖靈"), ("Acolyte", "侍祭"),
        ("Altar", "祭壇"), ("Anchor", "錨點"), ("Angel", "天使"), ("Ant", "螞蟻"),
        ("Beast", "野獸"), ("Blade", "刀刃"), ("Bloodrite", "血誓"), ("Cauldron", "大鍋"),
        ("Chieftain", "酋長"), ("Clone", "複製體"), ("Commander", "指揮官"),
        ("Curse", "詛咒"), ("Dreamer", "夢境者"), ("Fallen", "墮落"), ("Forging", "鍛造"),
        ("Gemcutting", "切割寶石"), ("Giant", "巨人"), ("Impaled", "被穿刺"),
        ("Journal", "日誌"), ("King", "國王"), ("Log", "紀錄"), ("Maraketh", "馬拉克斯"),
        ("Pale", "蒼白"), ("Primate", "靈長類"), ("Psalm", "聖詩"), ("Raging", "狂怒"),
        ("Raven", "烏鴉"), ("Sister", "姊妹"), ("Unearthed", "出土"), ("Warlord", "軍閥"),
        ("Xolotl", "索洛托"), ("Vox", "沃克斯"), ("Volatile", "易爆"), ("Vine", "藤蔓"),
        ("Wandering", "遊蕩"), ("Was", "曾是"), ("Toggle", "切換"), ("Capture", "擷取"),
        ("Activate", "啟用"), ("Add", "新增"), ("Augment", "增幅"), ("Display", "展示"),
        ("Boring", "無聊"), ("Boundless", "無限"), ("Brazier", "火盆"), ("Censer", "香爐"),
        ("Chair", "椅子"), ("Coffin", "棺材"), ("Cosmetics", "外觀"), ("Creations", "造物"),
        ("Darkshrine", "黑暗神殿"), ("Disloyalty", "不忠"), ("Double", "雙重"),
        ("Evening", "夜晚"), ("Exquisite", "精美"), ("Fetish", "護符"), ("Gilded", "鍍金"),
        ("Glorious", "輝煌"), ("Grasping", "攫取"), ("Hatchling", "幼體"), ("High", "高階"),
        ("Imperial", "帝國"), ("Isolation", "孤立"), ("Legacy", "傳承"), ("Luminous", "發光"),
        ("Lurking", "潛伏"), ("Mysterious", "神秘"), ("Notice", "告示"), ("Oba", "奧巴"),
        ("Paracosm", "異世界"), ("Placeholder", "佔位符"), ("Reconstructor", "重構器"),
        ("Reprimanding", "斥責"), ("Remains", "遺骸"), ("Remembrance", "紀念"),
        ("Revenant", "復仇亡魂"), ("Revive", "復活"), ("Rope", "繩索"), ("Rotting", "腐爛"),
        ("Royal", "皇室"), ("Saviour", "救世主"), ("Scrawl", "潦草字跡"), ("Shaman", "薩滿"),
        ("Shambler", "蹣跚者"), ("Skald", "吟遊詩人"), ("Song", "歌謠"), ("Summoner", "召喚師"),
        ("Surgeon", "外科醫師"), ("Tale", "故事"), ("Thane", "領主"), ("Thresher", "粉碎者"),
        ("Tome", "典籍"), ("Triumph", "勝利"), ("Ugly", "醜陋"), ("Writings", "文字"),
        ("Zarg", "扎格"), ("Zombie", "殭屍"), ("Mandibles", "顎"), ("Spike", "尖刺"),
        ("Shore", "海岸"), ("Surface", "地表"), ("Ship", "船艦"), ("Living", "活著的")
        ,
        // Additional live labels observed in the combat radar/entity atlas.  These are
        // deliberately display-only aliases: metadata paths and rule keys remain English.
        ("Explosive", "爆炸"), ("Explosives", "爆炸物"), ("Carver", "雕刻者"),
        ("Tribe", "部族"), ("Wicker", "柳條"), ("Basket", "籃子"),
        ("Carver Tribe Wicker Basket", "雕刻者部族柳條籃"),
        ("Stacked Boulder", "堆疊巨石"), ("Pirate Corpse", "海盜屍體"),
        ("Stone Altar", "石祭壇"), ("Spirit of Balbala", "巴爾巴拉之魂"),
        ("Spirit Of Balbala", "巴爾巴拉之魂"), ("Vaal Embalmed Archer", "瓦爾防腐弓箭手"),
        ("Balbala", "巴爾巴拉"), ("Atziri", "阿茲里"), ("Kirac", "基拉克"),
        ("Site", "地點"), ("Legacy", "舊版"), ("League", "聯盟"),
        ("Classify", "分類"), ("Show Name", "顯示名稱"), ("Show label", "顯示標籤"),
        ("Extra reward", "額外獎勵"), ("Forbidden Rites", "禁忌儀式"),
        ("Site (legacy Monster)", "地點（舊版怪物）"), ("Site (legacy monster)", "地點（舊版怪物）")
    };

    private static readonly IReadOnlyDictionary<string, string> DynamicWordTranslations = BuildDynamicWordTranslations();

    private static IReadOnlyDictionary<string, string> BuildNameTranslations()
    {
        var result = new Dictionary<string, string>(Poe2DbTranslationCatalog.Shared.Entries, StringComparer.OrdinalIgnoreCase);
        foreach (var (en, zh) in Phrases) result.TryAdd(en, zh);
        foreach (var (en, zh) in Poe2Aliases) result[en] = zh;
        return new System.Collections.ObjectModel.ReadOnlyDictionary<string, string>(result);
    }

    private static IReadOnlyDictionary<string, string> BuildDynamicWordTranslations()
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (en, zh) in NameTranslations)
        {
            // Stop-words are deliberately excluded: translating `of`, `the`, or `to` in a
            // partially-known proper name produces worse output than leaving that word intact.
            if (en.Length < 3 || en.Any(char.IsWhiteSpace) || en.Any(c => !char.IsLetter(c))) continue;
            if (en.Equals("the", StringComparison.OrdinalIgnoreCase)
                || en.Equals("and", StringComparison.OrdinalIgnoreCase)
                || en.Equals("of", StringComparison.OrdinalIgnoreCase)
                || en.Equals("to", StringComparison.OrdinalIgnoreCase)
                || en.Equals("in", StringComparison.OrdinalIgnoreCase)
                || en.Equals("on", StringComparison.OrdinalIgnoreCase)) continue;
            result.TryAdd(en, zh);
        }
        foreach (var (en, zh) in DynamicRadarPairs) result[en] = zh;
        return new System.Collections.ObjectModel.ReadOnlyDictionary<string, string>(result);
    }

    /* All fallback phrases are replaced in one pass: no per-frame traversal of the catalog. */
    // All fallback phrases are replaced in one pass: no per-frame traversal of the catalog.

    public static string Localize(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return value ?? "";
        var input = value.Trim();
        if (NameTranslations.TryGetValue(input, out var translated))
        {
            // POE2DB occasionally returns a partially translated value (for example
            // “靈魂 of Balbala”).  Run the same bounded token pass over that value so the
            // display never regresses to mixed Chinese/English while preserving the exact
            // catalog translation and all proper-name spellings.
            return LocalizeDynamicLabel(translated);
        }
        // Preserve line breaks in route instructions and never reinterpret internal keys.
        if (input.Contains("Metadata/", StringComparison.OrdinalIgnoreCase)) return input;
        string output;
        try
        {
            output = ReplacementPattern.Replace(input, match => Phrases[match.Value]);
        }
        catch (RegexMatchTimeoutException)
        {
            // A malformed/runtime-generated label must never break the world tick.  Keep the
            // raw display value and let the bounded dynamic-word pass below provide any safe
            // token translations it can; the timeout is diagnostic rather than fatal.
            output = input;
        }
        // Campaign notes and guide text often embed the English chapter marker inside a
        // longer sentence.  Convert it with the POE2DB-style Traditional Chinese presentation
        // without adding a broad "Act" dictionary entry that could damage internal IDs.
        output = ActPattern.Replace(output, m => $"第 {m.Groups["n"].Value} 章");
        return LocalizeDynamicLabel(output);
    }

    /// <summary>Best-effort localization for runtime-generated entity labels.  This is kept at
    /// the display boundary and never runs for metadata paths, rule keys, or memory values.</summary>
    public static string LocalizeDynamicLabel(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return value;
        var input = value.Trim();
        if (input.Length > 128) return value;
        // Entity display names may contain CJK from a partial catalog translation plus
        // English fragments, commas, parentheses, slashes, colons and ordinal numbers (for
        // example “靈魂 of Balbala” or “1st Place ...”).  Keep a conservative printable-text
        // guard, but do not require the string to start with ASCII: exact POE2DB names can
        // legitimately start with Traditional Chinese.
        if (!Regex.IsMatch(input, @"^[\p{L}\p{M}\p{N}\p{P}\p{Zs}…]{2,128}$", RegexOptions.CultureInvariant))
            return value;
        if (!input.Any(c => c is >= 'A' and <= 'Z' or >= 'a' and <= 'z')) return value;
        var expanded = IdentifierBoundary.Replace(input.Replace('_', ' ').Replace('-', ' '), " ");
        expanded = string.Join(' ', expanded.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        return DynamicWordPattern.Replace(expanded, m =>
            DynamicWordTranslations.TryGetValue(m.Groups["word"].Value, out var zh) ? zh : m.Value);
    }

    public static string LocalizeArea(string? value) => Localize(value);

    /// <summary>Converts generic UI copy to Traditional Chinese without touching game data keys.</summary>
    public static string ToTraditionalUiText(string? value)
    {
        if (string.IsNullOrEmpty(value)) return value ?? "";
        var result = value;
        foreach (var (simplified, traditional) in UiTraditionalPairs)
            result = result.Replace(simplified, traditional, StringComparison.Ordinal);
        return result;
    }

    /// <summary>
    /// Converts fixed interface copy to Simplified Chinese while preserving game data that was
    /// resolved from the POE2DB Traditional Chinese catalog. A route/status sentence can contain
    /// both kinds of text, so protect catalog values before applying the UI conversion.
    /// </summary>
    public static string ToSimplifiedUiTextPreservingGameNames(string? value)
    {
        if (string.IsNullOrEmpty(value)) return value ?? "";
        var protectedValues = NameTranslations.Values
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .Distinct(StringComparer.Ordinal)
            .OrderByDescending(v => v.Length)
            .ToArray();
        var saved = new List<string>(protectedValues.Length);
        var result = value;
        for (var i = 0; i < protectedValues.Length; i++)
        {
            var token = $"\uE000{i}\uE001";
            if (!result.Contains(protectedValues[i], StringComparison.Ordinal)) continue;
            result = result.Replace(protectedValues[i], token, StringComparison.Ordinal);
            saved.Add(token + "\u0000" + protectedValues[i]);
        }
        result = ToSimplifiedUiText(result);
        foreach (var entry in saved)
        {
            var split = entry.IndexOf('\u0000');
            result = result.Replace(entry[..split], entry[(split + 1)..], StringComparison.Ordinal);
        }
        return result;
    }

    /// <summary>Converts only the fixed UI vocabulary to Simplified Chinese.</summary>
    public static string ToSimplifiedUiText(string? value)
    {
        if (string.IsNullOrEmpty(value)) return value ?? "";
        var result = value;
        foreach (var (simplified, traditional) in UiTraditionalPairs
            .OrderByDescending(pair => pair.Traditional.Length))
            result = result.Replace(traditional, simplified, StringComparison.Ordinal);
        var chars = result.ToCharArray();
        for (var i = 0; i < chars.Length; i++)
            if (TraditionalCharacterMap.TryGetValue(chars[i], out var simplified)) chars[i] = simplified;
        result = new string(chars);
        return result;
    }

    private static string Cleanup(string value)
    {
        var sb = new StringBuilder(value.Length);
        var lastSpace = false;
        foreach (var ch in value)
        {
            if (char.IsWhiteSpace(ch))
            {
                if (!lastSpace) sb.Append(' ');
                lastSpace = true;
            }
            else { sb.Append(ch); lastSpace = false; }
        }
        return sb.ToString().Trim(' ', '·', '-');
    }
}
