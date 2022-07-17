import requests
import json
import pymysql
from bs4 import BeautifulSoup as BS
import logging
import time
import re

fmt = '%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s'
datefmt = '%Y-%m-%d %H:%M:%S'
level = logging.INFO

formatter = logging.Formatter(fmt, datefmt)
logger = logging.getLogger()
logger.setLevel(level)

file = logging.FileHandler("../zhihu.log", encoding='utf-8')
file.setLevel(level)
file.setFormatter(formatter)
logger.addHandler(file)

console = logging.StreamHandler()
console.setLevel(level)
console.setFormatter(formatter)
logger.addHandler(console)


class ZhihuCrawler:
    def __init__(self):
        with open("zhihu.json", "r", encoding="utf8") as f:
            self.settings = json.load(f)  # Load settings
        logger.info("Settings loaded")


    def sleep(self, sleep_key, delta=0):
        """
        Execute sleeping for a time configured in the settings

        :param sleep_key: the sleep time label
        :param delta: added to the sleep time
        :return:
        """
        _t = self.settings["config"][sleep_key] + delta
        logger.info(f"Sleep {_t} second(s)")
        time.sleep(_t)

    def query(self, sql, args=None, op=None):
        """
        Execute an SQL query

        :param sql: the SQL query to execute
        :param args: the arguments in the query
        :param op: the operation to cursor after query
        :return: op(cur)
        """
        conn = pymysql.connect(
            cursorclass=pymysql.cursors.DictCursor,
            client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS,
            **self.settings['mysql']
        )
        if args and not (isinstance(args, tuple) or isinstance(args, list)):
            args = (args,)
        with conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(sql, args)
                    conn.commit()
                    if op is not None:
                        return op(cur)
                except:  # Log query then exit
                    if hasattr(cur, "_last_executed"):
                        logger.error("Exception @ " + cur._last_executed)
                    else:
                        logger.error("Exception @ " + sql)
                    raise

    def watch(self, top=None):
        """
        The crawling flow

        :param top: only look at the first `top` entries in the board. It can be used when debugging
        :return:
        """
        self.create_table()
        while True:
            logger.info("Begin crawling ...")
            try:
                crawl_id = None
                begin_time = time.time()
                crawl_id = self.begin_crawl(begin_time)

                try:
                    board_entries = self.get_board()
                except RuntimeError as e:
                    if isinstance(e.args[0], requests.Response):
                        logger.exception(e.args[0].status_code, e.args[0].text)
                    raise
                else:
                    logger.info(
                        f"Get {len(board_entries)} items: {','.join(map(lambda x: x['title'][:20], board_entries))}")
                if top:
                    board_entries = board_entries[:top]

                # Process each entry in the hot list
                for idx, item in enumerate(board_entries):
                    self.sleep("interval_between_question")
                    detail = {
                        "created": None,
                        "visitCount": None,
                        "followerCount": None,
                        "answerCount": None,
                        "raw": None,
                        "hit_at": None
                    }
                    if item["qid"] is None:
                        logger.warning(f"Unparsed URL @ {item['url']} ranking {idx} in crawl {crawl_id}.")
                    else:
                        try:
                            detail = self.get_question(item["qid"])
                        except Exception as e:
                            if len(e.args) > 0 and isinstance(e.args[0], requests.Response):
                                logger.exception(f"{e}; {e.args[0].status_code}; {e.args[0].text}")
                            else:
                                logger.exception(f"{str(e)}")
                        else:
                            logger.info(f"Get question detail for {item['title']}: raw detail length {len(detail['raw']) if detail['raw'] else 0}")
                    try:
                        self.add_entry(crawl_id, idx, item, detail)
                    except Exception as e:
                        logger.exception(f"Exception when adding entry {e}")
                self.end_crawl(crawl_id)
            except Exception as e:
                logger.exception(f"Crawl {crawl_id} encountered an exception {e}. This crawl stopped.")
            self.sleep("interval_between_board", delta=(begin_time - time.time()))

    def create_table(self):
        """
        Create tables to store the hot question records and crawl records

        """
        sql = f"""
CREATE TABLE IF NOT EXISTS `crawl` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `begin` DOUBLE NOT NULL,
    `end` DOUBLE,
    PRIMARY KEY (`id`) USING BTREE
)
AUTO_INCREMENT = 1 
CHARACTER SET = utf8mb4 
COLLATE = utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `record`  (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `qid` INT NOT NULL,
    `crawl_id` BIGINT NOT NULL,
    `hit_at` DOUBLE,
    `ranking` INT NOT NULL,
    `title` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL ,
    `heat` VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
    `created` INT,
    `visitCount` INT,
    `followerCount` INT,
    `answerCount` INT,
    `excerpt` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
    `raw` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci ,
    `url` VARCHAR(255),
    PRIMARY KEY (`id`) USING BTREE,
    INDEX `CrawlAssociation` (`crawl_id`) USING BTREE,
    CONSTRAINT `CrawlAssociationFK` FOREIGN KEY (`crawl_id`) REFERENCES `crawl` (`id`)
) 
AUTO_INCREMENT = 1 
CHARACTER SET = utf8mb4 
COLLATE = utf8mb4_unicode_ci;

"""
        self.query(sql)

    def begin_crawl(self, begin_time) -> (int, float):
        """
        Mark the beginning of a crawl
        :param begin_time:
        :return: (Crawl ID, the time marked when crawl begin)
        """
        sql = """
INSERT INTO crawl (begin) VALUES(%s);
"""
        return self.query(sql, begin_time, lambda x: x.lastrowid)

    def end_crawl(self, crawl_id: int):
        """
        Mark the ending time of a crawl

        :param crawl_id: Crawl ID
        """
        sql = """
UPDATE crawl SET end = %s WHERE id = %s;
"""
        self.query(sql, (time.time(), crawl_id))

    def add_entry(self, crawl_id, idx, board, detail):
        """
        Add a question entry to database

        :param crawl_id: Crawl ID
        :param idx: Ranking in the board
        :param board: dict, info from the board
        :param detail: dict, info from the detail page
        """
        sql = \
            """
INSERT INTO record (`qid`, `crawl_id`, `title`, `heat`, `created`, `visitCount`, `followerCount`, `answerCount`,`excerpt`, `raw`, `ranking`, `hit_at`, `url`)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
"""
        self.query(
            sql,
            (
                board["qid"],
                crawl_id,
                board["title"],
                board["heat"],
                detail["created"],
                detail["visitCount"],
                detail["followerCount"],
                detail["answerCount"],
                board["excerpt"],
                detail["raw"],
                idx,
                detail["hit_at"],
                board["url"]
            )
        )

    def get_board(self) -> list:
        """
        TODO: Fetch current hot questions

        :return: hot question list, ranking from high to low

        Return Example:
        [
            {
                'title': '针对近期生猪市场非理性行为，国家发展改革委研究投放猪肉储备，此举对市场将产生哪些积极影响？',
                'heat': '76万热度',
                'excerpt': '据国家发展改革委微信公众号 7 月 5 日消息，针对近期生猪市场出现盲目压栏惜售等非理性行为，国家发展改革委价格司正研究启动投放中央猪肉储备，并指导地方适时联动投放储备，形成调控合力，防范生猪价格过快上涨。',
                'url': 'https://www.zhihu.com/question/541600869',
                'qid': 541600869,
            },
            {
                'title': '有哪些描写夏天的古诗词？',
                'heat': '41万热度',
                'excerpt': None,
                'url': 'https://www.zhihu.com/question/541032225',
                'qid': 541032225,
            },
            {
                'title':    # 问题标题
                'heat':     # 问题热度
                'excerpt':  # 问题摘要
                'url':      # 问题网址
                'qid':      # 问题编号
            }
            ...
        ]
        """

        url = "https://www.zhihu.com/hot"
        headers = self.settings["headers"]
        res = requests.get(url,headers = headers)
        soup = BS(res.text,'lxml')
        sections = soup.find_all('section',class_ = "HotItem")
        question_list=[]

        for i in sections:
            try:
                dic = {}
                dic['url'] = i.find('a')['href']
                qid_pattern = re.compile('question/(\d+)')
                m_list = qid_pattern.findall(dic['url'])
                if m_list:
                    dic['qid']=m_list[0]
                else:
                    continue
                dic["title"] = i.find('a')['title']
                excerpt = i.find('p',class_ = "HotItem-excerpt")
                if excerpt:
                    dic["excerpt"]=excerpt.txt
                else:
                    dic["excerpt"]=None
                dic['heat'] = i.find('div',class_ = "HotItem-metrics").text
                heat_pattern = re.compile('.+热度')
                dic['heat'] = heat_pattern.findall(dic['heat'])[0]
                question_list.append(dic)
                # print(len(question_list))
            except:
                continue

        return question_list

        # Hint: - Parse HTML, pay attention to the <section> tag.
        #       - Use keyword argument `class_` to specify the class of a tag in `find`
        #       - Hot Question List can be accessed in https://www.zhihu.com/hot

        # raise NotImplementedError

    def get_question(self, qid: int) -> dict:
        """
        TODO: Fetch question info by question ID

        :param qid: Question ID
        :return: a dict of question info

        Return Example:
        {
            "created": 1657248657,      # 问题的创建时间
            "followerCount": 5980,      # 问题的关注数量
            "visitCount": 2139067,      # 问题的浏览次数
            "answerCount": 2512         # 问题的回答数量
            "title": "日本前首相安倍      # 问题的标题
                晋三胸部中枪已无生命
                体征 ，嫌疑人被控制，
                目前最新进展如何？背
                后原因为何？",
            "raw": "<p>据央视新闻，        # 问题的详细描述
                当地时间8日，日本前
                首相安倍晋三当天上午
                在奈良发表演讲时中枪
                。据悉，安倍晋三在上
                救护车时还有意。。。",
            "hit_at": 1657264954.3134503  # 请求的时间戳
        }
        """

        qid = str(qid)
        url = "https://www.zhihu.com/question/" + qid
        headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
                "Cookie": '_zap=0095d9c6-45e8-4670-93d5-2e164d6876e2; _xsrf=IWDoh8eD3Chb8094wbsSMGu52i6KLKyJ; d_c0="AKBRzNebQRWPTj7xC4fffJ0MrfSmXz2rf2k=|1657960182"; __snaker__id=FjOPfv7h6UdRET2M; _9755xjdesxxd_=32; YD00517437729195%3AWM_NI=Q81WY8%2BGluyLTYAP0xmIW9Vzpiwt%2FNuCg%2F%2BH1ORQGJjoa3LmUw0wtyboCpcqfZNC%2FvuGg1scJuM6BcUJwggrE%2Bi5q2F%2FXV2gXn3vQBrflvdNJNb%2FQH%2F7EpdGqUrRiDJbMWQ%3D; YD00517437729195%3AWM_NIKE=9ca17ae2e6ffcda170e2e6eed4d33e90e9add5c83e96b48eb6c84b868f9bb0d154978ebdb4d149f595e596c82af0fea7c3b92a93e8ffb8dc34e999a496fc4898878fb1b374af9799dad572b4b7b995ae46b79da9d0aa44f3919eb2c642aab1afd4cf6797a90098f773a2b18d91e27ba68682a4ae7eb799a9d2f2698aab83d7c1699796b988e67a87f5a7d6f43a86f198b7b16d9cb2fd97d44ab2baa497e7468a92aed0d444ede98b91e74db38bbeb3ec508abe83b8d437e2a3; YD00517437729195%3AWM_TID=dJvXNiE7GRpEVUVFRBPATRU8WEH7KurB; gdxidpyhxdE=tlWtge%2FiNWQxep4D60%5CnPmQJB7mMLu7U1pKAxvV1s3fLUdjlpwVZ5ug9WDM7y0WAqWSirut%2FoQqqZb6S%5C3U4arV1CA1WIG43rP9ot92IjGN5QPHZxttqeRAYLcN%2F9Q2IX2x%5Ccj9injOvS%2BvRa4eu%2Bomyua30DT%2FpPlyXVaml274QO1%2Fc%3A1657972288657; o_act=login; ref_source=other_https://www.zhihu.com/signin?next=/; auth_type=wechat; token=58_FhYkOGjzMk7j_elv4J6fvBfpuKtT-A78UGfIV4EbtwQJ1w5zAK1BaomCtfBRPpE8lVe4tc2OPgPaV2Mrk868VO8jY7mmE6kdgv6vclpdnfw; atoken=58_FhYkOGjzMk7j_elv4J6fvBfpuKtT-A78UGfIV4EbtwQJ1w5zAK1BaomCtfBRPpE8lVe4tc2OPgPaV2Mrk868VO8jY7mmE6kdgv6vclpdnfw; atoken_expired_in=7200; client_id=o3p2-jh7itGYP6k_XMx4sLZkbkCE; capsion_ticket=2|1:0|10:1657971972|14:capsion_ticket|44:MDIxOWQ3NDA5MjNhNDAxOWI1YjdkMDI4ZTVkZGRiNDg=|9b0fc41bc765368b4bd1f48085e4a93aae67744a5c2153702710c08bc9a94973; captcha_session_v2=2|1:0|10:1657972027|18:captcha_session_v2|88:MmJ1YnpRNWMvN3NpN0FxUEhHenRaSlROVkJoQVhEM1dSNWtDMTVoRCt4eTIxbzUyS3JjbnNsVGRwSmZYTzc2Rg==|85ac3966d35dc4c337bb9b26b48d1371ce25da0604b6392cc2768108e7412a6e; z_c0=2|1:0|10:1657972052|4:z_c0|92:Mi4xdHZod0FBQUFBQUFBb0ZITTE1dEJGU2NBQUFCZ0FsVk5WREw2WWdDVWJabExwWUNmbWk0WTl4Y2tuRlpRZWxaM2hR|e78217d42f672668bac32a8b05d24db43189649d9d1d3d160549aa4b3a57b2b0; q_c1=254f23451a63411cbc5a2d5442b0137e|1657972052000|1657972052000; NOT_UNREGISTER_WAITING=1; Hm_lvt_98beee57fd2ef70ccdd5ca52b9740c49=1657960184,1657970535,1657972060; tst=h; Hm_lpvt_98beee57fd2ef70ccdd5ca52b9740c49=1657972084; SESSIONID=avjzwW4xq25qvcaz82IppXgrbpLmFtYGCXzk152kN6C; JOID=WlsTC0jrAoM7xbVYQOuCX-IYLhlbgXHnSrnpaTaRO7NEuN0yP5OsVFnFu1NFFrM0T4ZlFxqGO5omxnMknrB1H_A=; osd=UFESBkPhCII2zr9SQeaJVegZIxJRi3DqQbPjaDuaMblFtdY4NZKhX1PPul5OHLk1Qo1vHRuLMJAsx34vlLp0Evs=; KLBRSID=2177cbf908056c6654e972f5ddc96dc2|1657972097|1657971930'
            }
        res = requests.get(url,headers = headers).text
        soup = BS(res,'lxml')
        script = soup.find('script',id = "js-initialData").text

        dic = {}
        info = json.loads(script)
        dic["title"] = info['initialState']["entities"]["questions"][qid]["title"]
        dic["created"] = info['initialState']["entities"]["questions"][qid]["created"]
        dic["followerCount"] = info['initialState']["entities"]["questions"][qid]["followerCount"]
        dic["visitCount"] = info['initialState']["entities"]["questions"][qid]["visitCount"]
        dic["answerCount"] = info['initialState']["entities"]["questions"][qid]["answerCount"]
        dic["raw"] = info['initialState']["entities"]["questions"][qid]["detail"]
        dic["hit_at"] = time.time()

        return dic

        # Hint: - Parse JSON, which is embedded in a <script> and contains all information you need.
        #       - After find the element in soup, use `.text` attribute to get the inner text
        #       - Use `json.loads` to convert JSON string to `dict` or `list`
        #       - You may first save the JSON in a file, format it and locate the info you need
        #       - Use `time.time()` to create the time stamp
        #       - Question can be accessed in https://www.zhihu.com/question/<Question ID>

        raise NotImplementedError

if __name__ == "__main__":
    z = ZhihuCrawler()
    z.watch()