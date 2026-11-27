# BangBang HTML5 — Hướng dẫn cài và chơi

Bản chạy trên máy cá nhân, có sẵn server, dữ liệu game và Python đi kèm. Chỉ cần giải nén đầy đủ rồi mở **Choi_Ngay.bat**.

## 1. Chuẩn bị

- Máy chạy **Windows 10/11 64-bit**.
- Có trình duyệt web, chẳng hạn Microsoft Edge hoặc Google Chrome.
- Có khoảng **5 GB trống** để chứa thư mục game và dữ liệu phát sinh; nếu giữ cả ZIP tải về thì cần thêm chỗ cho ZIP.
- Không cần cài Python, pip, Flash Player hoặc phần mềm quản lý database.

File BAT đi kèm dùng cho Windows. Không dùng file này để khởi động trên macOS, Linux hoặc điện thoại.

## 2. Tải và giải nén

1. Tải **toàn bộ gói**, không tải riêng file `Choi_Ngay.bat`.
2. Giải nén ra thư mục bạn có quyền ghi, ví dụ `C:\Games\BangBang`. Không chạy trực tiếp từ bên trong ZIP.
3. Trong thư mục game phải thấy `Choi_Ngay.bat`, `data`, `runtime`, `server` và `www`.

Giữ các thư mục này nằm cạnh nhau. Không đổi tên hoặc xóa các thư mục tài nguyên chỉ vì tên có số phiên bản cũ: game hiện tại vẫn sử dụng chúng.

## 3. Mở game và đăng nhập

1. Nhấp đúp **Choi_Ngay.bat**.
2. Giữ cửa sổ server mở và đợi dòng **SẴN SÀNG**.
3. Trình duyệt mặc định sẽ mở hai trang: **game** và **web buff**.
4. Trong trang game, nhập tài khoản rồi bấm **Đăng nhập & vào sảnh**.

Tài khoản có sẵn để bắt đầu:

| Mục | Giá trị |
|---|---|
| Tài khoản | `html5_m5_xayda` |
| Mật khẩu | `nxAZXXe5MzepFg` |

Đây là dữ liệu mẫu đi kèm. Nếu muốn dùng tài khoản riêng, tạo tài khoản trong web buff theo mục 5.

Game thường mở tại `http://127.0.0.1:19083/html5/`. Khi cổng đó đang được dùng, chương trình tự chọn cổng khác và mở đúng địa chỉ. Hãy dùng địa chỉ hiện trong cửa sổ server, không cố truy cập cổng cũ.

Nếu trình duyệt không tự mở, sao chép địa chỉ **Game** trong cửa sổ server vào thanh địa chỉ trình duyệt. Nhấp BAT lần nữa khi cùng bản game đã chạy sẽ mở lại hai trang, không cần mở thêm một server.

`127.0.0.1` là máy đang chạy game. Gói này mặc định dùng trên một máy; gửi địa chỉ đó cho người khác sẽ không giúp họ vào server của bạn. Xem mục 9 về giới hạn LAN hiện tại.

## 4. Bắt đầu chơi

1. Vào sảnh, chọn tank muốn sử dụng.
2. Chọn **Đấu trường (PvP)** hoặc **Phụ bản (PvE)**. Có thể bắt đầu với luyện tập để làm quen.
3. Chọn phòng/chế độ, thiết lập các lựa chọn đang hiện rồi bắt đầu trận. Nếu tham gia phòng của người khác, làm theo trạng thái sẵn sàng của phòng.

Điều khiển cơ bản khi chưa đổi phím:

| Thao tác | Điều khiển |
|---|---|
| Di chuyển | W, A, S, D hoặc các phím mũi tên |
| Ngắm | Di chuyển chuột trong vùng trận |
| Bắn thường | Chuột trái |
| Kỹ năng | Xem phím ngay trên ô kỹ năng; thường là E, Space, R và Q tùy tank |

Mỗi tank có kỹ năng khác nhau. Xem biểu tượng, mô tả và thời gian hồi trong game. Có thể chỉnh phím và cách dùng kỹ năng trong phần cài đặt; tài khoản mẫu có thể đã lưu lựa chọn riêng. Nếu đang nhập chat hoặc ô chữ, đưa thao tác trở lại vùng trận trước khi điều khiển tank.

Khi túi đầy, vào **Túi đồ → Vật phẩm hoặc Nguyên liệu**, chọn món không cần rồi bấm **Bán**. Chọn số lượng hoặc **Chọn cả chồng**, bấm **Xem trước tại máy chủ**, kiểm tra rồi **Xác nhận bán**. Bấm **Hủy** để giữ nguyên đồ. Muốn giải phóng một ô phải bán hết chồng đồ trong ô đó; bán bớt số lượng chưa làm trống ô. Mỗi đơn vị bán được 1 Xu vàng. Đồ khóa, đang dùng hoặc có thời hạn chưa hỗ trợ bán.

## 5. Dùng web buff

Web buff là trang quản lý local: tạo tài khoản và gửi đồ/tiền qua hòm thư. Trang này có thể mở cùng lúc với game.

### Mở khóa

1. Mở thư mục game, vào `data` rồi mở file **admin_buff.key** bằng Notepad.
2. Sao chép toàn bộ nội dung file vào ô **Khóa quản trị riêng** trên web buff.
3. Bấm **Mở khóa**.

File khóa tự được tạo ở lần chạy đầu. Nếu chưa thấy file, đợi server báo sẵn sàng. Không nhập đường dẫn file vào ô khóa; phải nhập nội dung bên trong. Không dùng khóa này làm mật khẩu đăng nhập game.

### Tạo tài khoản riêng

1. Mở **Quản lý tài khoản** trong web buff.
2. Chọn tạo tài khoản và nhập tên/mật khẩu theo biểu mẫu.
3. Đăng nhập tài khoản mới trong game ít nhất một lần để tạo nhân vật.
4. Quay lại web buff và tìm nhân vật nếu muốn gửi đồ cho tài khoản đó.

### Gửi đồ hoặc tiền

1. Chọn đúng **người nhận**.
2. Chọn vật phẩm/tiền trong **kho tiếp tế**, thêm vào thư và đặt số lượng.
3. Bấm **Kiểm tra trước khi gửi**, kiểm tra lại rồi xác nhận gửi.
4. Vào **Hòm thư** trong game để nhận. Đồ không tự cộng thẳng vào túi lúc gửi.

Nếu túi đầy, thu xếp chỗ trống rồi nhận thư lại. Khi trang báo mất kết nối hoặc kết quả chưa rõ, kiểm tra trạng thái yêu cầu theo nút trên trang trước khi tạo thư khác để tránh gửi trùng.

## 6. Bật/tắt ghi log khi cần tìm lỗi

- Mặc định **tắt ghi log** mỗi lần mở server. Chơi bình thường có thể giữ tắt.
- Sau khi mở khóa web buff, tìm phần **Ghi log chẩn đoán** và bấm **Bật ghi log**.
- Tái hiện lỗi, sau đó bấm **Tắt ghi log**. Thao tác có hiệu lực ngay, không cần khởi động lại server.
- File nằm trong `data/packet_log/`: `diagnostic.log` và tối đa hai file cũ. Tổng dung lượng thường không quá khoảng 15 MB.
- Tắt log ngừng ghi nhưng vẫn giữ file đã có để xem/gửi kèm khi báo lỗi. Nếu muốn xóa chúng, dừng server rồi xóa các file trong thư mục `packet_log`.

Khi báo lỗi, ghi rõ thao tác, chế độ/map/tank, điều mong đợi và điều thực tế xảy ra; kèm ảnh hoặc log nếu có. Không cần gửi file khóa web buff.

## 7. Thoát game và giữ dữ liệu

1. Kết thúc/rời trận về sảnh.
2. Đóng các tab game và web buff.
3. Quay lại cửa sổ server, nhấn **Ctrl+C** để dừng. Đóng cửa sổ server cũng sẽ dừng game.

Chỉ đóng tab trình duyệt thì server vẫn còn chạy. Muốn chơi lại, mở `Choi_Ngay.bat` như bình thường.

Tài khoản, túi đồ và tiến độ được lưu trong **data/bangbang.sqlite3**. Đây là database thật, không phải file log; không xóa nó để dọn dung lượng.

Để sao lưu: dừng server, sao chép **toàn bộ thư mục `data`** ra một nơi riêng. Không chép đè dữ liệu mẫu lên thư mục `data` đang chơi. Không tự xóa các file `bangbang.sqlite3-wal` hoặc `bangbang.sqlite3-shm` khi server còn chạy.

## 8. Lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| Báo thiếu Python portable | Giải nén lại toàn bộ gói, kiểm tra `runtime/python/python.exe` còn nằm đúng chỗ. Không cần cài Python vào Windows. |
| Báo thiếu database mẫu | Kiểm tra `data/bangbang.sqlite3`. Khôi phục từ gói đầy đủ hoặc bản sao lưu của bạn; không tạo file rỗng cùng tên. |
| Trình duyệt không tự mở | Dùng địa chỉ Game/Web buff in trong cửa sổ server. |
| Trang không kết nối được | Kiểm tra cửa sổ server vẫn mở và đã báo sẵn sàng; dùng đúng cổng hiện tại. |
| Cửa sổ báo không khởi động được | Đọc dòng lỗi phía trên, kiểm tra đã giải nén đầy đủ và thư mục có quyền ghi. Nếu mọi cổng đều bận, đóng các bản server không dùng rồi thử lại. |
| Web buff báo khóa không đúng | Dùng nội dung `data/admin_buff.key` của đúng thư mục/server đang mở, không dùng khóa của một bản game khác. |
| Không tìm thấy tài khoản mới trong danh sách người nhận | Đăng nhập game bằng tài khoản đó một lần để tạo nhân vật, rồi tìm lại trong web buff. |
| Game báo thiếu tài nguyên | Kiểm tra giải nén đủ `www`, giữ nguyên cấu trúc thư mục; nhấn Ctrl+F5 để tải lại trang. |
| Phím điều khiển không phản hồi | Kiểm tra không đang nhập chat/ô chữ, xem lại phím trong cài đặt và đưa thao tác trở lại vùng trận. |

## 9. Chơi LAN — giới hạn của bản hiện tại

**Bản này chưa được cấu hình để tải về rồi chơi LAN ngay.** `Choi_Ngay.bat` mặc định chỉ nhận kết nối từ chính máy chạy server (`127.0.0.1`). Máy khác cùng Wi-Fi/mạng dây không thể dùng địa chỉ này để vào game trên máy chủ.

### Đổi địa chỉ bind thôi có đủ không?

Chưa đủ. Client lấy địa chỉ WebSocket theo trang đang mở, nên không bị cố định vào localhost. Nhưng game còn dùng `crypto.subtle` để kiểm tra tài nguyên và `crypto.randomUUID` cho một số thao tác. Các chức năng này cần môi trường trình duyệt an toàn: localhost được chấp nhận, còn địa chỉ dạng `http://192.168.1.10:19083` thông thường thì không. Vì vậy đổi sang `--bind 0.0.0.0` và mở cổng có thể giúp máy khác mở trang, nhưng game vẫn có thể lỗi nạp tài nguyên, giao diện hoặc giao dịch. Xem [quy định Web Crypto của trình duyệt](https://developer.mozilla.org/en-US/docs/Web/API/Crypto).

Kết nối qua Radmin VPN/ZeroTier cũng không tự giải quyết yêu cầu này nếu trình duyệt vẫn truy cập bằng HTTP qua IP mạng.

### Nếu triển khai LAN sau này

Cần có đủ các phần sau trước khi coi là dùng được:

1. Một máy chạy server, nhận kết nối qua địa chỉ LAN và cho phép cổng HTTP/HTTPS tương ứng qua tường lửa. Máy khách mở địa chỉ của máy chủ bằng trình duyệt; không chạy server riêng để tham gia cùng phòng.
2. Thiết lập HTTPS với chứng chỉ được các máy khách tin cậy, hoặc dùng phiên bản client đã bổ sung tương thích HTTP LAN mà vẫn giữ kiểm tra tài nguyên. Gói hiện tại chưa cấu hình sẵn hai cách này.
3. Mỗi người dùng tài khoản riêng; dữ liệu chơi chung được lưu ở máy chủ. Cần kiểm tra đăng nhập, tải trận và tham gia cùng phòng từ các máy khác nhau.

Web buff hiện chỉ cho truy cập từ chính máy chủ qua `localhost`/`127.0.0.1`, dù server có nhận kết nối LAN. Nếu tự chạy `server/app.py`, phải có `--enable-admin-buff` mới bật chức năng quản trị; `Choi_Ngay.bat` đã truyền tùy chọn này. Máy khách không cần khóa web buff để đăng nhập chơi game.

Hiện hãy dùng mục 3 để chơi trên một máy. Phần LAN này giải thích điều kiện và giới hạn, không phải hướng dẫn xác nhận rằng chỉ đổi bind là chơi LAN được.

## Thành phần đi kèm

Gói gồm mã nguồn chạy game, database mẫu, tài nguyên và Python 3.13.15 x64. Giấy phép của Python và thư viện đi kèm được giữ trong các thư mục tương ứng.
