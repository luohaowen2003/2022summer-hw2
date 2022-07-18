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
        Fetch current hot questions

        :return: hot question list, ranking from high to low
        """

        url = "https://www.zhihu.com/hot"
        headers = self.settings["headers"]
        res = requests.get(url,headers = headers)
        soup = BS(res.text,'lxml')
        sections = soup.find_all('section',class_ = "HotItem")
        question_list=[]

        for i in sections:
            try:
                # get url
                dic = {}
                dic['url'] = i.find('a')['href']

                # get qid (also check whether the item is a question)
                qid_pattern = re.compile('question/(\d+)')
                m_list = qid_pattern.findall(dic['url'])
                if m_list:
                    dic['qid']=m_list[0]
                else:
                    continue

                # get title
                dic["title"] = i.find('a')['title']

                # get excerpt, if any
                excerpt = i.find('p',class_ = "HotItem-excerpt")
                if excerpt:
                    dic["excerpt"]=excerpt.txt
                else:
                    dic["excerpt"]=None

                # get heat
                dic['heat'] = i.find('div',class_ = "HotItem-metrics").text
                heat_pattern = re.compile('.+热度')
                dic['heat'] = heat_pattern.findall(dic['heat'])[0]

                question_list.append(dic)
            except:
                continue

        return question_list

    def get_question(self, qid: int) -> dict:
        """
        Fetch question info by question ID

        :param qid: Question ID
        :return: a dict of question info
        """

        qid = str(qid)
        url = "https://www.zhihu.com/question/" + qid
        headers = self.settings["headers"]
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

if __name__ == "__main__":
    z = ZhihuCrawler()
    z.watch()