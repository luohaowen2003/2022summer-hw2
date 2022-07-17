from selenium.webdriver.remote.webdriver import WebDriver as wd
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait as wdw
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains as AC
import selenium
from bs4 import BeautifulSoup as BS
import json
from selenium import webdriver
import re

class WebVPN:
    def __init__(self, opt: dict, headless=False):
        self.root_handle = None
        self.driver: wd = None
        self.passwd = opt["password"]
        self.userid = opt["username"]
        self.headless = headless

    def login_webvpn(self):
        """
        Log in to WebVPN with the account specified in `self.userid` and `self.passwd`

        :return:
        """

        options=webdriver.ChromeOptions()
        options.add_argument('blink-settings=imagesEnabled=false')
        options.add_argument('--headless')

        d = self.driver
        if d is not None:
            d.close()
        d = selenium.webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()),options=options)
        d.get("https://webvpn.tsinghua.edu.cn/login")
        username = d.find_elements(By.XPATH,
                                   '//div[@class="login-form-item"]//input'
                                   )[0]
        password = d.find_elements(By.XPATH,
                                   '//div[@class="login-form-item password-field" and not(@id="captcha-wrap")]//input'
                                   )[0]
        username.send_keys(str(self.userid))
        password.send_keys(self.passwd)
        d.find_element(By.ID, "login").click()
        self.root_handle = d.current_window_handle
        self.driver = d
        return d

    def access(self, url_input):
        """
        Jump to the target URL in WebVPN

        :param url_input: target URL
        :return:
        """
        d = self.driver
        url = By.ID, "quick-access-input"
        btn = By.ID, "go"
        wdw(d, 5).until(EC.visibility_of_element_located(url))
        actions = AC(d)
        actions.move_to_element(d.find_element(*url))
        actions.click()
        actions.\
            key_down(Keys.CONTROL).\
            send_keys("A").\
            key_up(Keys.CONTROL).\
            send_keys(Keys.DELETE).\
            perform()

        d.find_element(*url)
        d.find_element(*url).send_keys(url_input)
        d.find_element(*btn).click()

    def switch_another(self):
        """
        If there are only 2 windows handles, switch to the other one

        :return:
        """
        d = self.driver
        assert len(d.window_handles) == 2
        wdw(d, 5).until(EC.number_of_windows_to_be(2))
        for window_handle in d.window_handles:
            if window_handle != d.current_window_handle:
                d.switch_to.window(window_handle)
                return

    def to_root(self):
        """
        Switch to the home page of WebVPN

        :return:
        """
        self.driver.switch_to.window(self.root_handle)

    def close_all(self):
        """
        Close all window handles

        :return:
        """
        while True:
            try:
                l = len(self.driver.window_handles)
                if l == 0:
                    break
            except selenium.common.exceptions.InvalidSessionIdException:
                return
            self.driver.switch_to.window(self.driver.window_handles[0])
            self.driver.close()

    def login_info(self):
        """
        TODO: After successfully logged into WebVPN, login to info.tsinghua.edu.cn

        :return:
        """

        uid = By.XPATH, '//input[@name="userName"]'
        pwd = By.XPATH, '//input[@name="password"]'
        button = By.XPATH, '//input[@src="initial/all/images/t_09.gif"]'

        wdw(self.driver,50).until(EC.visibility_of_element_located(button))
        uid_in = self.driver.find_element(*uid)
        pwd_in = self.driver.find_element(*pwd)
        uid_in.send_keys(self.userid)
        pwd_in.send_keys(self.passwd)
        but=self.driver.find_element(*button)
        but.click()

        wdw(self.driver, 5).until(EC.visibility_of_element_located((By.LINK_TEXT,"全部成绩")))
        self.driver.implicitly_wait(5)
        grades=self.driver.find_element(By.LINK_TEXT,"全部成绩")
        grades.click()

        # print(self.driver.window_handles)

        for window_handle in self.driver.window_handles:
            if window_handle != self.driver.current_window_handle and window_handle != self.root_handle:
                self.driver.switch_to.window(window_handle)
                return


        # Hint: - Use `access` method to jump to info.tsinghua.edu.cn
        #       - Use `switch_another` method to change the window handle
        #       - Wait until the elements are ready, then preform your actions
        #       - Before return, make sure that you have logged in successfully
        

    def get_grades(self):
        """
        TODO: Get and calculate the GPA for each semester.

        Example return / print:
            2020-秋: *.**
            2021-春: *.**
            2021-夏: *.**
            2021-秋: *.**
            2022-春: *.**

        :return:
        """
        d=self.driver
        table_path = '//table[@class="table table-striped  table-condensed"]'
        tables = d.find_elements(By.XPATH,table_path)
        table = tables[0]
        courses = table.find_elements(By.XPATH, "./tbody/tr")
        n = len(courses)-2
        semester=""
        semester_pattern=re.compile('\d{4}-\d{4}-\d')
        gpa={}
        credits=0
        total_score=0

        for i in range(1,n+1):
            info = courses[i].find_elements(By.XPATH,'./td/div[@align="center"]')
            
            semester_i = info[7].text
            if not semester_pattern.match(info[7].text):
                if semester_pattern.match(info[8].text):
                    semester_i = info[8].text
                else:
                    semester_i=info[9].text
            if semester != semester_i:
                if semester:
                    gpa[semester] = total_score / credits
                semester = semester_i
                credits=0
                total_score=0
            
            credits += int(info[2].text)
            total_score += float(info[5].text) * int(info[2].text)

            if(i==n):
                gpa[semester] = total_score / credits

        for key in gpa:
            sem = ""
            if key[-1]=='1':
                sem = key[:4]+"秋: "
            elif key[-1]=='2':
                sem = key[5:9]+"春: "
            elif key[-1]=='3':
                sem = key[5:9]+"夏: "

            print(sem, gpa[key])

        # Hint: - You can directly switch into
        #         `zhjw.cic.tsinghua.edu.cn/cj.cjCjbAll.do?m=bks_cjdcx&cjdlx=zw`
        #         after logged in
        #       - You can use Beautiful Soup to parse the HTML content or use
        #         XPath directly to get the contents
        #       - You can use `element.get_attribute("innerHTML")` to get its
        #         HTML code


if __name__ == "__main__":
    with open("settings.json","r") as f:
        w=WebVPN(json.load(f))
        w.login_webvpn()
        print('*'*20,'\n',"Checking your gpa, it can take a while...",'\n','*'*20)
        w.access("http://info.tsinghua.edu.cn")
        w.switch_another()
        w.login_info()
        w.get_grades()
    