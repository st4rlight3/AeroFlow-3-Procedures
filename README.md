# AeroFlow — Hướng dẫn chạy dự án

Website đặt vé máy bay một chiều và khứ hồi, sử dụng Python Flask và SQL Server. Thanh toán trên website là mô phỏng.

## 1. Chuẩn bị

| Phần mềm | Dùng để làm gì? |
| --- | --- |
| [Python 3.11 trở lên, bản 64-bit](https://www.python.org/downloads/windows/) | Chạy website. Khi cài, chọn **Add Python to PATH**. |
| [SQL Server 2019 trở lên, bản Express dùng được](https://www.microsoft.com/en-us/sql-server/sql-server-downloads) | Lưu dữ liệu của dự án. |
| [SQL Server Management Studio — SSMS](https://learn.microsoft.com/en-us/ssms/install/install) | Kết nối SQL Server, xem bảng và chạy truy vấn. SSMS và SQL Server là hai phần mềm riêng. |
| [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) | Kết nối Python với SQL Server. |

Mở PowerShell từ menu Start, nhập:

```powershell
python --version
```

Nếu chưa hiện phiên bản Python, hoàn tất cài Python rồi mở lại PowerShell.

## 2. Mở thư mục dự án

Tải mã nguồn bằng **Code → Download ZIP**, giải nén, rồi mở thư mục có `run.py`, `requirements.txt` và thư mục `app`.

Bấm thanh địa chỉ của File Explorer, gõ `powershell` rồi nhấn Enter. Những lệnh dưới đây đều chạy trong cửa sổ này. Mỗi dòng là một lệnh riêng; chờ chạy xong rồi nhập dòng tiếp theo.

## 3. Cài thư viện và tạo cấu hình

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\configure.py
```

- Dòng 1 tạo môi trường Python riêng trong `.venv`.
- Dòng 2 cài thư viện cần dùng.
- Dòng 3 tạo file `.env` và khóa bảo vệ phiên đăng nhập. Nếu file đã có, chương trình giữ nguyên.

## 4. Kết nối SQL Server

Mở SSMS, chọn **Database Engine → Windows Authentication**, rồi kết nối bằng tên SQL Server trên máy bạn. Với bản Express cài mặc định, tên thường là `.\SQLEXPRESS`.

Sau khi SSMS kết nối được, quay về PowerShell và mở cấu hình:

```powershell
notepad .env
```

Kiểm tra các dòng sau, lưu bằng `Ctrl+S`:

```dotenv
SQL_SERVER=.\SQLEXPRESS
SQL_DATABASE=AeroFlow
SQL_DRIVER=ODBC Driver 18 for SQL Server
SQL_TRUSTED_CONNECTION=yes
HOST=127.0.0.1
PORT=5000
```

`SQL_SERVER` phải giống **Server name** bạn vừa dùng trong SSMS. `SQL_DATABASE` là tên database sẽ tạo. Nếu tên đó đã có dữ liệu, chọn một tên chưa sử dụng, chẳng hạn `AeroFlow_HocTap`. Giữ các dòng khác, đặc biệt `SECRET_KEY`. Không đổi tên file thành `.env.txt`.

Nếu SSMS dùng **SQL Server Authentication**, đặt `SQL_TRUSTED_CONNECTION=no`, điền `SQL_USERNAME` và `SQL_PASSWORD` trong `.env` bằng tài khoản đang sử dụng.

## 5. Tạo database và nạp dữ liệu mẫu

Chỉ chạy bước này khi cài đặt vào một database mới:

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py
```

Lệnh này chạy bộ SQL để tạo bảng, ràng buộc, view, function, procedure, trigger và nạp đầy đủ dữ liệu mẫu. Chờ đến khi chương trình báo database đã sẵn sàng. Nếu database đã có bảng, bộ cài dừng để giữ dữ liệu của bạn.

Toàn bộ dữ liệu mẫu nằm trong `sql/04_seed_data.sql`, dưới dạng `INSERT INTO ... VALUES` với ID, tên, ngày giờ và giá vé được ghi sẵn. Không cần chạy thêm script sinh dữ liệu. Bộ dữ liệu gồm **42 sân bay, 176 chuyến bay và 352 dòng giá vé**, cùng danh mục máy bay, ghế và các đơn mẫu. Các bản ghi liên quan giữ đúng ID của nhau.

Muốn xem điểm đi, điểm đến và giá trong SSMS, mở `sql/09_business_queries.sql`. Muốn xem toàn bộ giá đã lưu, chạy `SELECT * FROM dbo.FlightFares;`. `BasePrice` là giá cơ sở, `TaxRate` là tỷ lệ thuế; phí của ghế cụ thể nằm trong `AircraftSeats.SeatFee`.

### Nếu muốn chạy SQL bằng SSMS

Mở một database mới và chạy các file trong `sql` theo thứ tự:

**01 → 02 → 03 → 04 → 06 → 05 → 07 → 08**.

File `04` nạp dữ liệu vào các bảng trống trước khi tạo trigger ở file `08`, để giữ nguyên cả lịch sử giao dịch và nhật ký mẫu. File `06` tạo hàm tính giá trước khi view ở file `05` sử dụng hàm đó. Nếu dùng tên database khác `AeroFlow`, sửa tên trong file `01` và dòng `USE AeroFlow;` đầu mỗi file cho khớp.

Bạn chỉ cần chọn **một** cách tạo database: dùng `init_db.py` hoặc mở từng file trong SSMS. Cả hai cách đều nạp cùng bộ dữ liệu. File `04` chỉ nạp vào bảng trống, không ghi đè dữ liệu đã có; không cần chạy lại mỗi lần mở web.

Sau khi cài xong, chạy `09_business_queries.sql` trong SSMS để xem kết quả truy vấn nghiệp vụ. Chạy `10_test_cases.sql` trên database mới có dữ liệu mẫu để kiểm tra ràng buộc và tính nhất quán. Xem các dòng `PASS` trong thẻ **Messages** của SSMS. Nếu đặt tên database khác `AeroFlow`, sửa dòng `USE AeroFlow;` trong cả hai file.

File `sql/07_stored_procedures.sql` có ba thủ tục nghiệp vụ:

- `sp_GetAvailableSeats` đọc sơ đồ ghế và tình trạng giữ ghế của một chuyến. Khi gọi từ web, backend giải phóng các lượt giữ đã hết hạn trước khi đọc.
- `sp_SaveFare` kiểm tra chuyến đang mở bán và khoang ghế phù hợp, rồi cập nhật hoặc thêm giá vé.
- `sp_GetRevenueReport` tổng hợp tiền thu, tiền hoàn và doanh thu ròng theo ngày.

Backend thực hiện đặt vé, thanh toán mô phỏng, hủy vé và cập nhật chuyến bay bằng các lệnh SQL có tham số trong giao dịch.

Để chạy thử thủ tục báo cáo doanh thu, chọn database dự án trong cửa sổ truy vấn SSMS và chạy:

```sql
DECLARE @From date = (SELECT MIN(CreatedAt) FROM dbo.Payments);
DECLARE @To date = (SELECT MAX(CreatedAt) FROM dbo.Payments);
EXEC dbo.sp_GetRevenueReport @From = @From, @To = @To;
```

ERD nằm trong [`docs/ERD.svg`](docs/ERD.svg), phần mô tả nằm trong [`docs/ERD.md`](docs/ERD.md).

## 6. Bật website

```powershell
.\.venv\Scripts\python.exe run.py
```

PowerShell sẽ in địa chỉ, ví dụ:

```text
AeroFlow: http://127.0.0.1:5000
```

Mở Chrome, Edge hoặc Cốc Cốc rồi dán **đúng địa chỉ được in ra** vào thanh địa chỉ. `127.0.0.1` là máy tính bạn đang dùng; `5000` là số cổng để trình duyệt kết nối với chương trình.

Giữ PowerShell mở trong lúc dùng website. Nhấn `Ctrl+C` trong PowerShell khi muốn dừng. Nếu chương trình báo cổng đang được sử dụng, đổi `PORT` trong `.env` sang một số khác, chạy lại và mở địa chỉ mới được in ra.

## 7. Đăng ký tài khoản

Trên website, chọn **Đăng nhập → Đăng ký**. Điền họ tên, email và mật khẩu ít nhất **12 ký tự**. Sau đó đăng nhập để đặt vé. Các tài khoản mẫu trong database bị khóa; bạn tự tạo tài khoản của mình.

Nếu cần quản trị chuyến bay và xem báo cáo, mở PowerShell tại thư mục dự án và chạy:

```powershell
.\.venv\Scripts\python.exe scripts\create_user.py --role ADMIN --email admin@example.test --name "Quản trị AeroFlow"
```

Nhập mật khẩu từ 12 ký tự khi được hỏi, rồi nhập lại để xác nhận. Mật khẩu không hiện ký tự khi gõ. Khi thấy `Account created.`, đăng nhập bằng email và mật khẩu vừa tạo. Menu quản trị chỉ hiện cho tài khoản quản trị.

## 8. Những lần mở tiếp theo

Mở PowerShell trong thư mục có `run.py`, chạy:

```powershell
.\.venv\Scripts\python.exe run.py
```

Mở địa chỉ chương trình in ra. Không cần cài lại thư viện, tạo database hoặc nạp dữ liệu mỗi lần mở web.

## Khi chưa chạy được

| Hiện tượng | Cách xử lý |
| --- | --- |
| Không tìm thấy `requirements.txt` hoặc `run.py` | Mở PowerShell đúng thư mục có các file này. |
| Không tìm thấy `.venv\Scripts\python.exe` | Kiểm tra lệnh tạo `.venv` ở bước 3 đã chạy thành công. |
| Thiếu ODBC Driver | Cài Driver 18 bản 64-bit và so lại `SQL_DRIVER` trong `.env`. |
| Không kết nối được SQL Server | Kết nối bằng SSMS trước; so lại tên server, database và cách đăng nhập. |
| Trình duyệt không mở được web | Kiểm tra PowerShell vẫn chạy và địa chỉ trình duyệt đúng dòng chương trình in ra. |
| Tìm chuyến không có kết quả | Dùng ngày và tuyến có trong `Flights`; kiểm tra bước 5 đã chạy xong hoặc xóa bộ lọc trên web. |
