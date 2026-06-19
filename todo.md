# idea
    auto scroll to get all
    make the replay faster
    access the http://localhost:8080/__archive__ is so slow

     Đánh chặn Request trong quá trình Replay:

    Khi file HTML gốc được load lên, các thẻ <script> hay các hàm JS trên trang bắt đầu chạy lại. Chúng sẽ cố gắng gọi các Web API như lúc ở trang live (ví dụ: fetch('https://api.example.com/data')).

    Thay vì để các request này bay ra ngoài mạng internet (điều sẽ dẫn đến lỗi 404, CORS, hoặc trả về dữ liệu mới không khớp với thời điểm lưu), Service Worker sẽ chặn đứng toàn bộ các request này.
    -> static html

    Đóng vai trò "Máy chủ ảo" (Service Worker):

    Quá trình bắt dữ liệu (Intercepting):

Sử dụng chrome.debugger API: Khi bạn nhấn "Record" trên extension, ArchiveWeb.page sẽ gắn (attach) một debugger vào tab hiện tại. Nó đăng ký lắng nghe các luồng mạng ở tầng thấp nhất thông qua các domain Network và Fetch của Chrome.

Chặn và bắt Web API / JS: Khi trang web thực thi mã JavaScript và gọi các Web API (qua XHR hoặc Fetch) để tải dữ liệu JSON, trình duyệt sẽ gửi các sự kiện (events) qua CDP. Extension sử dụng các lệnh như Fetch.getResponseBody hoặc Network.getResponseBody để trích xuất chính xác payload (phần nội dung body của API response hoặc source code của file .js) trực tiếp từ luồng mạng của trình duyệt, trước khi hoặc ngay khi trình duyệt render.

Bảo toàn Metadata: Không chỉ lưu nội dung, nó còn bắt toàn bộ Headers, Status Codes (200, 404,...), và Cookies của request/response đó để phục vụ cho việc giả lập sau này.

ưu tiên html, giao diện , thì mới gọi cái đó

the url in replay still go out to the real web -> make the private env that replay web -> not interact with outer

# REF
    https://github.com/internetarchive/heritrix3
    https://github.com/webrecorder/archiveweb.page
    https://github.com/firecrawl/firecrawl
    https://crawlee.dev/python/docs/introduction

--> remake the old code-> get the text, data of the saved web from the title, anner, all of the data in the web -> save to json, md but still all icon, image, all web flow, to know the flow of the web, replay to show data base on new struct, from the data json got prev
  
the section of json, md data should be more detailed that: for example, in html file: we have the code 
    """
    <li data-rid="6"><div class="book-img"><a href="//www.qidian.com/book/1049114386/" target="_blank" data-eid="qd_A142" data-bid="1049114386"><img class="lazy" src="//bookcover.yuewen.com/qdbimg/349573/1049114386/90.webp" data-original="//bookcover.yuewen.com/qdbimg/349573/1049114386/90.webp" alt="我在非洲当皇帝" style="">  </a></div><div class="book-info"><h3><a href="//www.qidian.com/book/1049114386/" target="_blank" data-eid="qd_A143" data-bid="1049114386" title="我在非洲当皇帝">我在非洲当皇帝</a></h3><p>19世纪末，群雄崛起，瓜分世界。非洲是最后的无主之地。
我来，我见，我征服！
多年以后，站在乞力马扎罗之巅，刘奕德环视天下：这就是我的封狼居胥！
-------------------------
林觉民：能使汉旗飘扬，则死也瞑目
严复：“他们才是蛮夷，才是贼，我们夺回自己的天下，天经地义！刘奕德，膺符受命、天纵之圣、文治武功、四海归心，可承大汉正统矣！”
威廉二世:非洲，只要刘奕德的非洲加入，我们就会赢得战争。
邱胖子:老天保佑！我们还有刘奕德！
瑞典国王奥斯卡二世：“你是说第一届诺贝尔奖全都要颁给一个人？”
本书又名《非洲帝国风云录》《当世第一财阀传》《财阀，帝国的崛起》《西汉帝国兴起录》</p><div class="state-box"><div class="left"><img src="//qdfepccdn.qidian.com/www.qidian.com/images/ico/user.png"><a class="author" href="//my.qidian.com/author/431151392/" data-eid="qd_A144" target="_blank">小鱼的命运</a> </div><div class="right"><span class="count">日更4千+</span><i class="type">外国历史</i></div></div></div></li>
    """
    -> the exact data for this section should be: 
    {
    "book-img": {
        "href": "//www.qidian.com/book/1049114386/",
        "img_src": "//bookcover.yuewen.com/qdbimg/349573/1049114386/90.webp",
        "img_alt": "我在非洲当皇帝"
    },
    "book-info": {
        "title": "我在非洲当皇帝",
        "title_href": "//www.qidian.com/book/1049114386/",
        "description": "19世纪末，群雄崛起，瓜分世界。非洲是最后的无主之地。\n我来，我见，我征服！\n多年以后，站在乞力马扎罗之巅，刘奕德环视天下：这就是我的封狼居胥！\n-------------------------\n林觉民：能使汉旗飘扬，则死也瞑目\n严复：“他们才是蛮夷，才是贼，我们夺回自己的天下，天经地义！刘奕德，膺符受命、天纵之圣、文治武功、四海归心，可承大汉正统矣！”\n威廉二世:非洲，只要刘奕德的非洲加入，我们就会赢得战争。\n邱胖子:老天保佑！我们还有刘奕德！\n瑞典国王奥斯卡二世：“你是说第一届诺贝尔奖全都要颁给一个人？”\n本书又名《非洲帝国风云录》《当世第一财阀传》《财阀，帝国的崛起》《西汉帝国兴起录》",
        "state-box": {
        "left": {
            "icon_src": "//qdfepccdn.qidian.com/www.qidian.com/images/ico/user.png",
            "author_href": "//my.qidian.com/author/431151392/",
            "author_name": "小鱼的命运"
        },
        "right": {
            "count": "日更4千+",
            "type": "外国历史"
        }
        }
    }
    }. The struct above just the example, the importatn that keep the data of a section perfectly: img, text, for  the people to understand not only the information but also the struct of html
    it means remake data to json struct, the level, .. should be like in the web, but still kêp the data struct divided byL type: img_tag, section in current version, the md file is oke


remake Hierarchical Areas that display the data: text, img, ... with the struct of html code of all web, all type, all kind of wweb , all type, has to be full - html file but cleaner, structable, easy to understand. REMMEMBER THAT ALL WWEB< ALL KIND OF Web. THE DATA in
  Hierarchical Areas  shoukd be clean, remove the data not neeed, js, css, ... width, ... -? just the core data to understand the struct of web easy to read, to understand

i want the old version of showing the html code in hierachy struct that: contain like a json file, can open, minize, maximize, like a element in chrome dev tool, this current of html code in Hierarchical Areas is so hard to see, very confusing

auto exact when record, after record -> get all need data: json, md, replay,.. not to click exact in web replay
the javascriipt to control the button, click, the things affect to the work of web has to work like the original web when replay (Ex: if ads -> click to close), remove the Invisible Overlay, Clickjacking, Pop-under