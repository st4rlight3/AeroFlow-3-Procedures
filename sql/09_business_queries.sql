USE AeroFlow;
GO
-- 01. Danh sách sân bay; chọn theo tên thành phố và trạng thái hoạt động.
SELECT * FROM dbo.Airports
WHERE IsActive=1 AND (City LIKE N'%Hà%' OR City LIKE N'%Hồ Chí Minh%') ORDER BY Code;

-- 02. Nhóm giá cao nhất trong khoảng đã chọn, kèm hãng và hai sân bay.
SELECT TOP(10) PERCENT WITH TIES f.FlightNumber,l.Name Airline,o.City Origin,d.City Destination,
 ff.BasePrice,dbo.fn_CalculateTicketPrice(ff.BasePrice,ff.TaxRate) PriceWithTax
FROM dbo.Flights f INNER JOIN dbo.Airports o ON o.AirportID=f.OriginID
INNER JOIN dbo.Airports d ON d.AirportID=f.DestinationID
INNER JOIN dbo.Aircraft a ON a.AircraftID=f.AircraftID INNER JOIN dbo.Airlines l ON l.AirlineID=a.AirlineID
INNER JOIN dbo.FlightFares ff ON ff.FlightID=f.FlightID
WHERE ff.BasePrice BETWEEN 1000000 AND 4000000 ORDER BY ff.BasePrice DESC;

-- 03. Khách hàng và số lần đặt vé, kể cả người chưa đặt lần nào.
SELECT u.UserID,u.FullName,COUNT(b.BookingID) BookingCount
FROM dbo.Users u LEFT JOIN dbo.Bookings b ON b.UserID=u.UserID
GROUP BY u.UserID,u.FullName ORDER BY BookingCount DESC;

-- 04. Số chuyến xuất phát từ mỗi sân bay, kể cả nơi chưa có chuyến đi.
SELECT a.Code,a.City,COUNT(f.FlightID) Departures
FROM dbo.Flights f RIGHT JOIN dbo.Airports a ON a.AirportID=f.OriginID
GROUP BY a.Code,a.City ORDER BY a.Code;

-- 05. Đối chiếu lượt đi và đến; giữ cả nơi chỉ có một trong hai loại.
WITH departures AS(SELECT OriginID AirportID,COUNT(*) N FROM dbo.Flights GROUP BY OriginID),
 arrivals AS(SELECT DestinationID AirportID,COUNT(*) N FROM dbo.Flights GROUP BY DestinationID)
SELECT COALESCE(d.AirportID,a.AirportID) AirportID,COALESCE(d.N,0) Departures,COALESCE(a.N,0) Arrivals
FROM departures d FULL OUTER JOIN arrivals a ON a.AirportID=d.AirportID;

-- 06. Những giá vé cao hơn mức trung bình toàn bộ bảng giá (truy vấn con vô hướng).
SELECT FlightID,FareClassID,BasePrice FROM dbo.FlightFares
WHERE BasePrice>(SELECT AVG(BasePrice) FROM dbo.FlightFares) ORDER BY BasePrice DESC;

-- 07. Khách có ít nhất hai đơn, dùng kết quả truy vấn con như một bảng.
SELECT u.UserID,u.FullName,s.BookingCount FROM dbo.Users u
JOIN(SELECT UserID,COUNT(*) BookingCount FROM dbo.Bookings GROUP BY UserID HAVING COUNT(*)>=2) s
 ON s.UserID=u.UserID ORDER BY s.BookingCount DESC;

-- 08. Hợp các sân bay có chuyến đi hoặc đến; mỗi sân bay xuất hiện một lần.
SELECT OriginID AirportID FROM dbo.Flights UNION SELECT DestinationID FROM dbo.Flights;
-- 09. Giao: những sân bay có cả chuyến đi lẫn chuyến đến.
SELECT OriginID AirportID FROM dbo.Flights INTERSECT SELECT DestinationID FROM dbo.Flights;
-- 10. Hiệu: những sân bay chưa có chuyến xuất phát.
SELECT AirportID FROM dbo.Airports EXCEPT SELECT OriginID FROM dbo.Flights;
GO
