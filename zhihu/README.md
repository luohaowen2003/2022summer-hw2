## 程序简介：
该程序会每隔10分钟爬取一次知乎热榜（只爬取其中的“问题”），并将爬取的问题id，问题名称，访问量等数据保存在database下的名为record的table中。

## 使用方法：
在mysql中预先建好名为“zhihu”的database，并在zhihu.json中完成数据库和浏览器配置后运行zhihu.py即可。