"""Parameterized commands for booking operations and expired seat holds."""

from textwrap import indent

from ..db import LOCK_INVENTORY_SQL, query


# An expired booking releases all of its seats, even if only one leg was requested.
_EXPIRE_HOLDS_SQL = """DECLARE @expired TABLE(BookingID int PRIMARY KEY);
UPDATE b SET Status='EXPIRED' OUTPUT inserted.BookingID INTO @expired
FROM dbo.Bookings b WHERE b.Status='HELD' AND b.ExpiresAt<=SYSUTCDATETIME()
  AND EXISTS(SELECT 1 FROM dbo.BookingSegments s WHERE s.BookingID=b.BookingID AND s.FlightID IN (@expire_flight_id, @expire_return_flight_id));
UPDATE t SET Status='VOID' FROM dbo.Tickets t JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID JOIN @expired e ON e.BookingID=p.BookingID;
UPDATE a SET IsActive=0 FROM dbo.FlightSeatAssignments a JOIN dbo.Tickets t ON t.AssignmentID=a.AssignmentID
JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID JOIN @expired e ON e.BookingID=p.BookingID;
"""

# Payment and cancellation can lock twice in separate transactions of one batch.
_EXPIRY_LOCK_SQL = LOCK_INVENTORY_SQL.replace('@inventory_lock_result', '@expiry_lock_result')
_EXPIRE_HOLDS_TRANSACTION_SQL = f"""
BEGIN TRY
    BEGIN TRAN;
{indent(_EXPIRY_LOCK_SQL, "    ")}
{indent(_EXPIRE_HOLDS_SQL, "    ")}
    COMMIT;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK;
    THROW;
END CATCH;
"""

_EXPIRE_FLIGHT_HOLDS_SQL = f"""
SET NOCOUNT ON;
SET XACT_ABORT ON;
DECLARE @expire_flight_id int = ?, @expire_return_flight_id int = NULL;
{_EXPIRE_HOLDS_TRANSACTION_SQL}
"""

_CREATE_BOOKING_SQL = f"""
DECLARE @UserID int = ?, @FlightID int = ?, @Passengers nvarchar(max) = ?,
        @ReturnFlightID int = ?, @ExpectedTotal decimal(14,2) = ?, @BookingID int;
 SET NOCOUNT ON; SET XACT_ABORT ON;
 BEGIN TRY
  BEGIN TRAN;
{indent(LOCK_INVENTORY_SQL, "  ")}
  DECLARE @expire_flight_id int = @FlightID, @expire_return_flight_id int = @ReturnFlightID;
{indent(_EXPIRE_HOLDS_SQL, "  ")}
  IF NOT EXISTS(SELECT 1 FROM dbo.Users WHERE UserID=@UserID AND IsActive=1)
   THROW 51002,N'Tài khoản không hoạt động.',1;
  DECLARE @legs TABLE(SegmentOrder tinyint PRIMARY KEY,FlightID int,AircraftID int,SegmentID int);
  INSERT @legs(SegmentOrder,FlightID) VALUES(1,@FlightID);
  IF @ReturnFlightID IS NOT NULL INSERT @legs(SegmentOrder,FlightID) VALUES(2,@ReturnFlightID);
  UPDATE l SET AircraftID=f.AircraftID FROM @legs l JOIN dbo.Flights f WITH(UPDLOCK,HOLDLOCK) ON f.FlightID=l.FlightID
   JOIN dbo.Aircraft a ON a.AircraftID=f.AircraftID AND a.IsActive=1
   JOIN dbo.Airports o ON o.AirportID=f.OriginID AND o.IsActive=1 JOIN dbo.Airports d ON d.AirportID=f.DestinationID AND d.IsActive=1
   WHERE f.Status='SCHEDULED' AND f.DepartureTime>DATEADD(hour,2,SYSUTCDATETIME());
  IF EXISTS(SELECT 1 FROM @legs WHERE AircraftID IS NULL) THROW 51003,N'Chuyến bay không còn mở bán.',1;
  IF @ReturnFlightID IS NOT NULL AND NOT EXISTS(
   SELECT 1 FROM dbo.Flights f JOIN dbo.Flights r ON r.FlightID=@ReturnFlightID
   WHERE f.FlightID=@FlightID AND r.OriginID=f.DestinationID AND r.DestinationID=f.OriginID
     AND r.DepartureTime>=DATEADD(minute,60,f.ArrivalTime))
   THROW 51004,N'Chiều về phải ngược chiều đi và cách giờ đến ít nhất 60 phút.',1;
  IF @Passengers IS NULL OR ISJSON(@Passengers)<>1 OR LEFT(LTRIM(@Passengers),1)<>'['
   THROW 51004,N'Danh sách hành khách không hợp lệ.',1;
  DECLARE @p TABLE(RowID int IDENTITY,SeatID int,FareClassID int,ReturnSeatID int,ReturnFareClassID int,
   FullName nvarchar(120),DateOfBirth date,DocumentNumber nvarchar(30),BookingPassengerID int);
  INSERT @p(SeatID,FareClassID,ReturnSeatID,ReturnFareClassID,FullName,DateOfBirth,DocumentNumber)
  SELECT SeatID,FareClassID,ReturnSeatID,ReturnFareClassID,TRIM(FullName),TRY_CONVERT(date,DateOfBirth),TRIM(DocumentNumber)
  FROM OPENJSON(@Passengers) WITH(SeatID int,FareClassID int,ReturnSeatID int,ReturnFareClassID int,
   FullName nvarchar(120),DateOfBirth nvarchar(30),DocumentNumber nvarchar(30));
  DECLARE @count int=(SELECT COUNT(*) FROM @p);
  IF @count NOT BETWEEN 1 AND 9 THROW 51004,N'Cần từ 1 đến 9 hành khách.',1;
  IF EXISTS(SELECT 1 FROM @p WHERE FullName IS NULL OR LEN(FullName)<2 OR DateOfBirth IS NULL
   OR DateOfBirth>CONVERT(date,SYSUTCDATETIME()) OR DateOfBirth<'19000101' OR DocumentNumber IS NULL OR LEN(DocumentNumber)<5)
   THROW 51004,N'Thông tin hành khách chưa đầy đủ.',1;
  IF (SELECT COUNT(DISTINCT DocumentNumber) FROM @p)<>@count
   THROW 51004,N'Giấy tờ hành khách trong một đơn không được trùng.',1;
  DECLARE @items TABLE(RowID int,SegmentOrder tinyint,FlightID int,SeatID int,FareClassID int,
   BaseFare decimal(14,2),TaxAmount decimal(14,2),SeatFee decimal(14,2),BaggageKg int,RefundPercent decimal(5,2));
  INSERT @items(RowID,SegmentOrder,FlightID,SeatID,FareClassID)
  SELECT p.RowID,l.SegmentOrder,l.FlightID,CASE l.SegmentOrder WHEN 1 THEN p.SeatID ELSE p.ReturnSeatID END,
   CASE l.SegmentOrder WHEN 1 THEN p.FareClassID ELSE p.ReturnFareClassID END FROM @p p CROSS JOIN @legs l;
  IF EXISTS(SELECT 1 FROM @items GROUP BY FlightID,SeatID HAVING COUNT(*)>1)
   THROW 51004,N'Mỗi hành khách phải chọn một ghế khác nhau.',1;
  UPDATE i SET BaseFare=f.BasePrice,TaxAmount=ROUND(f.BasePrice*f.TaxRate,2),SeatFee=s.SeatFee,
   BaggageKg=c.BaggageKg,RefundPercent=c.RefundPercent
  FROM @items i JOIN @legs l ON l.SegmentOrder=i.SegmentOrder
  JOIN dbo.AircraftSeats s ON s.SeatID=i.SeatID AND s.AircraftID=l.AircraftID AND s.IsActive=1
  JOIN dbo.FareClasses c ON c.FareClassID=i.FareClassID AND c.Cabin=s.Cabin
  JOIN dbo.FlightFares f ON f.FlightID=i.FlightID AND f.FareClassID=i.FareClassID;
  IF EXISTS(SELECT 1 FROM @items WHERE BaseFare IS NULL)
   THROW 51004,N'Ghế hoặc hạng vé không phù hợp với chuyến bay.',1;
  IF EXISTS(SELECT 1 FROM @items i JOIN dbo.FlightSeatAssignments a WITH(UPDLOCK,HOLDLOCK)
   ON a.FlightID=i.FlightID AND a.SeatID=i.SeatID AND a.IsActive=1)
   THROW 51005,N'Ghế vừa được người khác giữ. Vui lòng chọn ghế khác.',1;
  IF @ExpectedTotal IS NOT NULL AND @ExpectedTotal<>(SELECT SUM(BaseFare+TaxAmount+SeatFee) FROM @items)
   THROW 51013,N'Giá vé đã thay đổi. Vui lòng kiểm tra lại trước khi đặt.',1;
  DECLARE @pnr char(8)=UPPER(LEFT(REPLACE(CONVERT(varchar(36),NEWID()),'-',''),8));
  WHILE EXISTS(SELECT 1 FROM dbo.Bookings WHERE PNR=@pnr)
   SET @pnr=UPPER(LEFT(REPLACE(CONVERT(varchar(36),NEWID()),'-',''),8));
  INSERT dbo.Bookings(PNR,UserID,ExpiresAt) VALUES(@pnr,@UserID,DATEADD(minute,10,SYSUTCDATETIME()));
  SET @BookingID=SCOPE_IDENTITY();
  INSERT dbo.BookingSegments(BookingID,FlightID,SegmentOrder) SELECT @BookingID,FlightID,SegmentOrder FROM @legs;
  UPDATE l SET SegmentID=s.BookingSegmentID FROM @legs l JOIN dbo.BookingSegments s ON s.BookingID=@BookingID AND s.SegmentOrder=l.SegmentOrder;
  DECLARE @i int=1,@passenger int,@bp int,@assignment int,@leg tinyint;
  WHILE @i<=@count
  BEGIN
   INSERT dbo.Passengers(FullName,DateOfBirth,DocumentNumber) SELECT FullName,DateOfBirth,DocumentNumber FROM @p WHERE RowID=@i;
   SET @passenger=SCOPE_IDENTITY();
   INSERT dbo.BookingPassengers(BookingID,PassengerID) VALUES(@BookingID,@passenger);
   SET @bp=SCOPE_IDENTITY(); SET @leg=1;
   WHILE @leg<=(SELECT COUNT(*) FROM @legs)
   BEGIN
    INSERT dbo.FlightSeatAssignments(FlightID,SeatID) SELECT FlightID,SeatID FROM @items WHERE RowID=@i AND SegmentOrder=@leg;
    SET @assignment=SCOPE_IDENTITY();
    INSERT dbo.Tickets(TicketNumber,BookingPassengerID,BookingSegmentID,FareClassID,AssignmentID,
     BaseFare,TaxAmount,SeatFee,BaggageKg,RefundPercent)
    SELECT CONCAT('AF',RIGHT(REPLACE(CONVERT(varchar(36),NEWID()),'-',''),16)),@bp,l.SegmentID,i.FareClassID,@assignment,
     i.BaseFare,i.TaxAmount,i.SeatFee,i.BaggageKg,i.RefundPercent
    FROM @items i JOIN @legs l ON l.SegmentOrder=i.SegmentOrder WHERE i.RowID=@i AND i.SegmentOrder=@leg;
    SET @leg+=1;
   END;
   SET @i+=1;
  END;
  COMMIT;
  SELECT * FROM dbo.vw_BookingDetails WHERE BookingID=@BookingID;
 END TRY BEGIN CATCH IF @@TRANCOUNT>0 ROLLBACK; THROW; END CATCH;
"""

_CONFIRM_PAYMENT_SQL = f"""
DECLARE @UserID int = ?, @BookingID int = ?, @IdempotencyKey varchar(80) = ?, @Success bit = ?;
 SET NOCOUNT ON; SET XACT_ABORT ON;
 DECLARE @flight int=(SELECT MIN(s.FlightID) FROM dbo.BookingSegments s JOIN dbo.Bookings b ON b.BookingID=s.BookingID WHERE b.BookingID=@BookingID AND b.UserID=@UserID);
 IF @flight IS NULL THROW 51006,N'Không tìm thấy đơn đặt vé.',1;
 DECLARE @expire_flight_id int = @flight, @expire_return_flight_id int = NULL;
{_EXPIRE_HOLDS_TRANSACTION_SQL}
 BEGIN TRY
  BEGIN TRAN;
{indent(LOCK_INVENTORY_SQL, "  ")}
  IF @IdempotencyKey IS NULL OR LEN(TRIM(@IdempotencyKey))<16 OR @Success IS NULL THROW 51004,N'Mã thanh toán không hợp lệ.',1;
  IF EXISTS(SELECT 1 FROM dbo.Payments WHERE IdempotencyKey=@IdempotencyKey)
  BEGIN
   IF NOT EXISTS(SELECT 1 FROM dbo.Payments WHERE IdempotencyKey=@IdempotencyKey AND BookingID=@BookingID AND Kind='CHARGE'
    AND Status=CASE WHEN @Success=1 THEN 'SUCCESS' ELSE 'FAILED' END)
    THROW 51007,N'Mã thanh toán đã được dùng cho yêu cầu khác.',1;
   COMMIT;
   SELECT * FROM dbo.Payments WHERE IdempotencyKey=@IdempotencyKey; RETURN;
  END;
  IF NOT EXISTS(SELECT 1 FROM dbo.Bookings WHERE BookingID=@BookingID AND Status='HELD' AND ExpiresAt>SYSUTCDATETIME())
   THROW 51008,N'Đơn đã thanh toán, đã hủy hoặc hết hạn giữ ghế.',1;
  IF EXISTS(SELECT 1 FROM dbo.BookingSegments s JOIN dbo.Flights f ON f.FlightID=s.FlightID
   WHERE s.BookingID=@BookingID AND (f.Status<>'SCHEDULED' OR f.DepartureTime<=DATEADD(hour,2,SYSUTCDATETIME())))
   THROW 51003,N'Chuyến bay không còn cho phép thanh toán.',1;
  DECLARE @amount decimal(14,2)=(SELECT SUM(t.BaseFare+t.TaxAmount+t.SeatFee) FROM dbo.Tickets t JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID WHERE p.BookingID=@BookingID);
  INSERT dbo.Payments(BookingID,IdempotencyKey,Amount,Kind,Status)
   VALUES(@BookingID,@IdempotencyKey,@amount,'CHARGE',CASE WHEN @Success=1 THEN 'SUCCESS' ELSE 'FAILED' END);
  IF @Success=1
  BEGIN
   UPDATE dbo.Bookings SET Status='CONFIRMED' WHERE BookingID=@BookingID;
   UPDATE t SET Status='VALID' FROM dbo.Tickets t JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID WHERE p.BookingID=@BookingID;
  END;
  COMMIT;
  SELECT * FROM dbo.Payments WHERE IdempotencyKey=@IdempotencyKey;
 END TRY BEGIN CATCH IF @@TRANCOUNT>0 ROLLBACK; THROW; END CATCH;
"""

_CANCEL_BOOKING_SQL = f"""
DECLARE @UserID int = ?, @BookingID int = ?;
 SET NOCOUNT ON; SET XACT_ABORT ON;
 DECLARE @flight int,@status varchar(12),@refund decimal(14,2)=0;
 SELECT @flight=MIN(s.FlightID) FROM dbo.Bookings b JOIN dbo.BookingSegments s ON s.BookingID=b.BookingID
 WHERE b.BookingID=@BookingID AND (b.UserID=@UserID OR EXISTS(SELECT 1 FROM dbo.Users u JOIN dbo.Roles r ON r.RoleID=u.RoleID WHERE u.UserID=@UserID AND u.IsActive=1 AND r.Name='ADMIN'));
 IF @flight IS NULL THROW 51006,N'Không tìm thấy đơn đặt vé.',1;
 DECLARE @expire_flight_id int = @flight, @expire_return_flight_id int = NULL;
{_EXPIRE_HOLDS_TRANSACTION_SQL}
 BEGIN TRY
  BEGIN TRAN;
{indent(LOCK_INVENTORY_SQL, "  ")}
  SELECT @status=Status FROM dbo.Bookings WHERE BookingID=@BookingID;
  IF @status='CANCELLED' BEGIN COMMIT; SELECT CAST(1 AS bit) Cancelled,CAST(0 AS decimal(14,2)) RefundAmount; RETURN; END;
  IF @status='EXPIRED' THROW 51008,N'Đơn đã hết hạn giữ ghế.',1;
  IF @status='CONFIRMED'
  BEGIN
   IF EXISTS(SELECT 1 FROM dbo.BookingSegments s JOIN dbo.Flights f ON f.FlightID=s.FlightID WHERE s.BookingID=@BookingID
    AND (f.DepartureTime<=DATEADD(hour,24,SYSUTCDATETIME()) OR f.Status<>'SCHEDULED'))
    THROW 51009,N'Chỉ được hủy cả hành trình trước giờ bay ít nhất 24 giờ.',1;
   SELECT @refund=SUM(ROUND((t.BaseFare+t.TaxAmount+t.SeatFee)*t.RefundPercent/100,2)) FROM dbo.Tickets t JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID WHERE p.BookingID=@BookingID AND t.Status='VALID';
   INSERT dbo.Payments(BookingID,IdempotencyKey,Amount,Kind,Status) VALUES(@BookingID,CONCAT('refund-booking-',@BookingID),@refund,'REFUND','SUCCESS');
  END;
  UPDATE t SET Status='VOID' FROM dbo.Tickets t JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID WHERE p.BookingID=@BookingID;
  UPDATE a SET IsActive=0 FROM dbo.FlightSeatAssignments a JOIN dbo.Tickets t ON t.AssignmentID=a.AssignmentID JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID WHERE p.BookingID=@BookingID;
  UPDATE dbo.Bookings SET Status='CANCELLED' WHERE BookingID=@BookingID;
  COMMIT;
  SELECT CAST(1 AS bit) Cancelled,@refund RefundAmount;
 END TRY BEGIN CATCH IF @@TRANCOUNT>0 ROLLBACK; THROW; END CATCH;
"""


def expire_flight_holds(flight_id):
    query(_EXPIRE_FLIGHT_HOLDS_SQL, (flight_id,))


def get_available_seats(flight_id):
    return query(_EXPIRE_FLIGHT_HOLDS_SQL + 'EXEC dbo.sp_GetAvailableSeats @expire_flight_id;', (flight_id,))


def create_booking_db(user_id, flight_id, passengers_json, return_flight_id, expected_total):
    return query(_CREATE_BOOKING_SQL,
                 (user_id, flight_id, passengers_json, return_flight_id, expected_total), one=True)


def confirm_payment(user_id, booking_id, idempotency_key, success):
    return query(_CONFIRM_PAYMENT_SQL, (user_id, booking_id, idempotency_key, success), one=True)


def cancel_booking(user_id, booking_id):
    return query(_CANCEL_BOOKING_SQL, (user_id, booking_id), one=True)
