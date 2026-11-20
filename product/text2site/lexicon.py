"""中文词表：把用户的说法对应到知识库的产品类型、目标、功能、风格。
词表是数据，可以随修复记录不断补充（学习回路会统计哪些说法没被识别）。"""

PRODUCT = {
    "Bakery/Cafe": ["咖啡馆", "咖啡店", "咖啡", "面包店", "烘焙", "甜品", "蛋糕", "奶茶", "茶饮"],
    "Restaurant/Food Service": ["餐厅", "饭店", "餐馆", "火锅", "烧烤", "小吃", "料理", "菜馆", "酒楼", "私房菜", "饭馆"],
    "Brewery/Winery": ["酒庄", "精酿", "啤酒", "酒吧"],
    "Hotel/Hospitality": ["酒店", "民宿", "客栈", "宾馆"],
    "Beauty/Spa/Wellness Service": ["美容", "美甲", "美发", "理发", "按摩", "养生馆", "皮肤管理", "spa"],
    "Fitness/Gym App": ["健身房", "健身", "私教", "普拉提", "瑜伽馆", "瑜伽"],
    "Dental Practice": ["牙科", "口腔", "牙医"],
    "Medical Clinic": ["诊所", "门诊", "中医馆", "医院"],
    "Veterinary Clinic": ["宠物医院", "兽医"],
    "Childcare/Daycare": ["托儿所", "幼儿园", "早教", "托育"],
    "Online Course/E-learning": ["网课", "在线课程", "课程", "培训", "辅导", "补习", "教育机构"],
    "Real Estate/Property": ["房产", "地产", "房屋中介", "租房", "楼盘"],
    "Legal Services": ["律师事务所", "律所", "律师", "法律咨询"],
    "Marketing Agency": ["营销公司", "广告公司", "营销", "推广"],
    "Creative Agency": ["设计工作室", "品牌设计", "创意公司"],
    "Photography Studio": ["摄影工作室", "婚纱摄影", "写真", "照相馆"],
    "Wedding/Event Planning": ["婚礼", "婚庆", "活动策划"],
    "Conference / Symposium Landing Page": ["峰会", "大会", "研讨会", "展会", "会议报名"],
    "Portfolio/Personal": ["作品集", "个人网站", "个人主页", "插画师", "设计师", "摄影师", "自由职业"],
    "E-commerce Luxury": ["奢侈品", "珠宝", "腕表", "高定"],
    "Florist/Plant Shop": ["花店", "鲜花", "绿植"],
    "E-commerce": ["网店", "商城", "电商", "卖货", "在线商店"],
    "AI/Chatbot Platform": ["人工智能", "智能客服", "聊天机器人", "ai"],
    "SaaS (General)": ["saas", "软件", "管理系统", "云服务", "系统", "工具"],
    "Non-profit/Charity": ["公益", "慈善", "基金会", "志愿者"],
    "Museum/Gallery": ["博物馆", "美术馆", "画廊", "展览"],
    "Travel/Tourism Agency": ["旅行社", "旅游", "旅行", "导游"],
    "Automotive/Car Dealership": ["4s店", "车行", "二手车", "汽修", "汽车"],
    "Home Services (Plumber/Electrician)": ["家政", "保洁", "家电维修", "水电维修", "开锁", "搬家"],
    "Home Decoration & Interior Design": ["装修", "室内设计", "家装", "软装"],
    "Construction/Architecture": ["建筑公司", "施工", "工程公司"],
    "Coworking Space": ["共享办公", "联合办公"],
    "Magazine/Blog": ["博客", "杂志", "专栏"],
    "News/Media Platform": ["新闻", "媒体", "资讯网"],
    "Podcast Platform": ["播客"],
    "Job Board/Recruitment": ["招聘网站", "求职", "人才网"],
    "Sports Team/Club": ["球队", "俱乐部", "篮球", "足球"],
    "Theater/Cinema": ["剧场", "剧院", "影院", "话剧"],
    "Agriculture/Farm Tech": ["农场", "果园", "农产品", "茶园"],
    "Senior Care/Elderly": ["养老院", "养老", "护理院"],
    "Insurance Platform": ["保险"],
    "Pharmacy/Drug Store": ["药店", "药房"],
    "Mental Health App": ["心理咨询", "心理"],
    "Logistics/Delivery": ["物流", "快递", "货运"],
    "Membership/Community": ["社群", "会员社区", "社区"],
    "Open Source Project Landing": ["开源项目", "开源"],
    "Coding Bootcamp": ["编程培训", "编程课"],
    "Sustainable Energy / Climate Tech": ["新能源", "光伏", "储能"],
    "B2B Service": ["企业服务", "外包", "咨询公司", "代理记账"],
}

# 每个目标：触发词。出现顺序最靠前的目标定为 P0。
GOALS = {
    "booking": ["预约", "预订", "订座", "订位", "挂号", "约课", "订房", "订桌"],
    "sell": ["卖", "购买", "下单", "网购", "销售"],
    "leads": ["咨询", "联系我", "联系我们", "询价", "获客", "约稿", "找我合作", "报价", "留下联系方式", "客户找到"],
    "signup": ["注册", "试用", "报名", "招新", "体验课"],
    "showcase": ["展示", "作品", "案例", "形象", "品牌"],
    "inform": ["介绍", "了解", "菜单", "价目", "看看", "信息"],
    "community": ["加入社区", "社群", "招募", "志愿者"],
    "recruit": ["招聘", "招人", "加入我们"],
    "download": ["下载"],
}

FEATURES = {
    "booking": ["预约", "预订", "订座", "订位", "挂号", "订房", "约课", "订桌"],
    "contact_form": ["咨询", "联系", "留言", "表单", "约稿", "报价", "询价"],
    "map": ["地址", "地图", "位置", "怎么走", "到店", "门店"],
    "gallery": ["相册", "作品", "照片", "图片", "案例"],
    "catalog": ["产品", "商品", "菜单", "服务项目", "价目", "课程表"],
    "cart": ["购物车", "下单"],
    "payment": ["在线支付", "付款", "支付", "定金"],
    "multilingual": ["英文", "双语", "多语言", "中英"],
    "blog": ["博客", "文章", "动态", "新闻"],
    "faq": ["常见问题", "faq", "问答"],
    "newsletter": ["订阅", "邮件通知"],
    "membership": ["会员", "登录", "账号"],
    "search": ["搜索"],
}

# 中文风格说法 → 风格 ID（必须是词表里可用的 ID；生成时会校验）
STYLE = {
    "minimalism-and-swiss-style": ["简约", "极简", "干净", "简洁", "清爽"],
    "minimalist-monochrome": ["高级", "高端", "奢华", "质感", "黑白"],
    "claymorphism": ["可爱", "童趣", "卡通", "萌"],
    "glassmorphism": ["科技感", "玻璃", "通透"],
    "cyberpunk-ui": ["赛博", "赛博朋克", "霓虹"],
    "retro-futurism": ["未来感", "复古未来"],
    "vintage-analog-retro-film": ["复古", "怀旧", "胶片", "老派"],
    "dark-mode-oled": ["暗黑", "深色", "黑色背景", "夜间"],
    "organic-biophilic": ["自然", "清新", "环保", "有机", "森系"],
    "soft-ui-evolution": ["温馨", "温暖", "柔和", "治愈", "亲切"],
    "neubrutalism": ["个性", "大胆", "潮", "冲击力"],
    "editorial-grid-magazine": ["杂志风", "文艺", "编辑感"],
    "flat-design": ["扁平"],
    "bauhaus": ["包豪斯"],
    "motion-driven": ["动感", "酷炫", "有活力"],
}

# 含义宽泛、经常只是在描述位置或泛指的词：命中时只算一半分
AMBIGUOUS = {"社区", "系统", "工具", "品牌", "心理", "旅行", "媒体", "保险", "汽车", "课程", "培训", "ai"}
SHOP_SUFFIX = "店馆铺厅所院坊房"  # 紧跟这些字的词（火锅店、牙科诊所）更像是在说“我是做什么的”

NEGATIONS = ["不要", "别", "不想", "不喜欢", "避免", "不能太", "不要太", "别太"]
CALM = ["别太花哨", "不要太花哨", "不要花哨", "别花哨", "安静", "稳重", "低调", "朴素"]
LIVELY = ["动感", "酷炫", "有活力", "动画", "炫"]
TWO_LANG = ["英文", "双语", "中英", "多语言", "外国客人", "外国人"]
