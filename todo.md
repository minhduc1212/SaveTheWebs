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