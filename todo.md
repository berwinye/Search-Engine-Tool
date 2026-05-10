项目名称： 搜索引擎工具 (Search Engine Tool) - COMP/XJCO3011 Coursework 2 目标网站： https://quotes.toscrape.com/ （用于爬取数据 ）编程语言与技术栈： Python 。推荐使用 Requests 库处理 HTTP 请求 ，使用 Beautiful Soup 库解析 HTML 页面 。  

1. 核心业务逻辑与约束



礼貌原则 (Politeness Window)： 这是绝对红线，两次连续的 HTTP 请求之间必须至少等待 6 秒钟 。  



大小写不敏感 (Case Sensitivity)： 搜索功能在处理查询时忽略大小写（例如 'Good' 和 'good' 视为同一个词汇）。  



倒排索引 (Inverted Index)： 必须在爬取时实时构建，存储每个单词在每个页面中的统计信息（如：词频、出现位置等）。为了简化操作，可以将整个索引序列化保存到单个文件中 。  

2. 命令行接口 (CLI) 需求

主程序必须提供一个命令行 Shell 交互界面，支持以下 4 个核心命令 ：  



build：触发爬虫抓取目标网站，构建倒排索引，并将结果保存到本地文件系统中 。  



load：从文件系统中读取并加载之前使用 build 生成的索引文件 。  



print <word>：打印指定单词的倒排索引信息（例如：print nonsense）。  



find <query>：支持单词或多词查询（例如：find good friends），返回包含这些查询词的所有页面列表 。必须能妥善处理边缘情况（如：不存在的词、空查询、特殊字符等）。  

3. 项目目录结构要求

请严格按照以下结构组织代码库 ：  

Plaintext



repository-name/

├── src/

│   ├── crawler.py       [cite: 103, 104]

│   ├── indexer.py       [cite: 105]

│   ├── search.py        [cite: 106]

│   └── main.py          [cite: 107]

├── tests/

│   ├── test_crawler.py  [cite: 108, 109]│   ├── test_indexer.py  

│   └── test_search.py   [cite: 111]

├── data/

│   └── [compiled index file]  [cite: 112, 114]

├── requirements.txt     [cite: 115]

└── README.md            [cite: 116]

开发待办事项清单 (To-Do List)

请按照以下阶段逐步实现该项目，并确保每个组件都可以独立测试。

阶段 1：项目初始化

[ ] 创建标准的目录结构 。  

[ ] 初始化虚拟环境，安装 requests 和 beautifulsoup4，并生成 requirements.txt 。  

阶段 2：开发爬虫模块 (src/crawler.py)

[ ] 编写爬虫脚本抓取 https://quotes.toscrape.com/ 的所有页面 。  

[ ] 关键：实现请求节流机制，确保每次 HTTP 请求间隔 > 6 秒 。  

[ ] 实现异常处理机制，妥善处理网络请求失败等情况 。  

阶段 3：开发索引模块 (src/indexer.py)

[ ] 设计高效的数据结构来表示倒排索引 。  

[ ] 提取网页中的文本，去除标点符号，转换为小写形式（满足大小写不敏感要求）。  

[ ] 记录每个单词在网页中的词频和位置，写入倒排索引字典 。  

[ ] 实现将索引序列化保存到 data/ 目录下的功能 。  

[ ] 实现从文件反序列化加载索引的功能 。  

阶段 4：开发搜索模块 (src/search.py)

[ ] 实现 print 查询逻辑：格式化输出单个单词的统计与位置信息 。  

[ ] 实现 find 查询逻辑：支持多词查询，找出包含所有查询词的页面交集 。  

[ ] 高分项实现：考虑加入 TF-IDF 排名算法或其他高级查询处理（以满足 80-100 分段的要求）。  

阶段 5：开发 CLI 交互入口 (src/main.py)

[ ] 使用 argparse 或标准 input() 循环构建命令行 shell 。  

[ ] 集成并正确路由 build、load、print、find 四个指令 。  

阶段 6：编写测试用例 (tests/)

[ ] 为 crawler.py 编写测试，包括模拟 (mock) 网络请求 。  

[ ] 为 indexer.py 编写测试，验证统计数据的准确性和大小写处理 。  

[ ] 为 search.py 编写边缘用例测试（如：查询不存在的单词、输入为空等）。  

[ ] 确保测试覆盖率达到较高水平（目标 >85%）。  

阶段 7：完善文档规范

[ ] 在代码中添加清晰的内联注释、类型提示 (type hints) 和 docstrings 。  

[ ] 编写 README.md，必须包含：项目概览、安装设置步骤、全部四个命令的使用示例，以及测试指南 。  