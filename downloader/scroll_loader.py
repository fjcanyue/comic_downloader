from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options
from time import sleep

def load_all_images(url):
    # 设置 Firefox 选项
    options = Options()
    #options.add_argument('--headless')
    
    # 初始化浏览器
    driver = webdriver.Firefox(options=options)
    try:
        # 访问页面
        driver.get(url)
        
        # 等待页面初始加载
        sleep(5)
        
        # 获取初始页面高度
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        max_attempts = 30  # 最大滚动尝试次数
        
        while scroll_attempts < max_attempts:
            # 滚动到页面底部
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            
            # 等待页面加载，增加等待时间
            sleep(3)
            
            # 检查懒加载的图片是否已加载
            driver.execute_script("""
                var images = document.getElementsByTagName('img');
                for (var i = 0; i < images.length; i++) {
                    var img = images[i];
                    if (img.getAttribute('data-src')) {
                        img.src = img.getAttribute('data-src');
                    }
                }
            """)
            
            # 计算新的页面高度
            new_height = driver.execute_script("return document.body.scrollHeight")
            
            # 如果页面高度没有变化，并且已经尝试了足够多次，则退出
            if new_height == last_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0  # 如果高度变化，重置计数器
                
            last_height = new_height
            
            # 每次滚动后检查图片加载状态
            try:
                WebDriverWait(driver, 5).until(
                    lambda x: len([img for img in x.find_elements(By.TAG_NAME, "img") 
                                 if img.get_attribute('src') and 
                                 not img.get_attribute('src').endswith('load.gif') and
                                 img.get_attribute('complete')]) > 0
                )
            except:
                pass  # 继续滚动即使等待超时
        
        # 最后等待确保图片加载完成
        sleep(5)
        
        # 获取所有图片元素，使用更严格的筛选条件
        images = [img for img in driver.find_elements(By.TAG_NAME, "img") 
                 if img.get_attribute('src') and 
                 not img.get_attribute('src').endswith('load.gif') and
                 img.get_attribute('complete') and
                 img.get_attribute('naturalWidth') != '0' and
                 'shimolife.com' in img.get_attribute('src')]
        
        print(f"加载完成，共找到 {len(images)} 张真实图片")
        
        # 返回图片URL列表
        return [img.get_attribute('src') for img in images]
        
    finally:
        # 关闭浏览器
        driver.quit()

if __name__ == "__main__":
    url = "https://www.dumanwu.com/GZwZJZe/CIazLLY.html"
    image_urls = load_all_images(url)
    for i, url in enumerate(image_urls, 1):
        print(f"图片 {i}: {url}")