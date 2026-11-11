"""Run flight changes as SQL Server transactions with bound parameters."""

from ..db import LOCK_INVENTORY_SQL, query


_SAVE_FLIGHT = f"""
SET NOCOUNT ON;
SET XACT_ABORT ON;
DECLARE @FlightID int=?, @FlightNumber varchar(8)=?, @AircraftID int=?,
        @OriginID int=?, @DestinationID int=?, @DepartureTime datetime2(0)=?, @ArrivalTime datetime2(0)=?;
BEGIN TRY
 BEGIN TRAN;
 {LOCK_INVENTORY_SQL}
 IF @FlightID IS NOT NULL
 BEGIN
  IF NOT EXISTS(SELECT 1 FROM dbo.Flights WHERE FlightID=@FlightID AND Status='SCHEDULED') THROW 51010,N'Chỉ sửa chuyến đang mở bán.',1;
  IF EXISTS(SELECT 1 FROM dbo.BookingSegments WHERE FlightID=@FlightID) THROW 51011,N'Chuyến đã có lịch sử đặt vé. Hãy tạo chuyến mới nếu cần đổi lịch hoặc máy bay.',1;
 END;
 IF @OriginID=@DestinationID OR @ArrivalTime<=@DepartureTime OR @DepartureTime<=SYSUTCDATETIME()
  OR NULLIF(TRIM(@FlightNumber),'') IS NULL THROW 51004,N'Lịch bay không hợp lệ.',1;
 IF NOT EXISTS(SELECT 1 FROM dbo.Aircraft WHERE AircraftID=@AircraftID AND IsActive=1)
  OR (SELECT COUNT(*) FROM dbo.Airports WHERE AirportID IN (@OriginID,@DestinationID) AND IsActive=1)<>2
  THROW 51004,N'Máy bay hoặc sân bay không hoạt động.',1;
 IF EXISTS(SELECT 1 FROM dbo.Flights WHERE AircraftID=@AircraftID AND Status<>'CANCELLED' AND FlightID<>COALESCE(@FlightID,0)
  AND DepartureTime<DATEADD(minute,45,@ArrivalTime) AND ArrivalTime>DATEADD(minute,-45,@DepartureTime))
  THROW 51012,N'Máy bay có lịch trùng hoặc chưa đủ 45 phút quay đầu.',1;
 IF EXISTS(SELECT 1 FROM dbo.Flights f WHERE f.FlightID=(SELECT TOP(1) FlightID FROM dbo.Flights
  WHERE AircraftID=@AircraftID AND Status<>'CANCELLED' AND FlightID<>COALESCE(@FlightID,0) AND ArrivalTime<=@DepartureTime ORDER BY ArrivalTime DESC)
  AND f.DestinationID<>@OriginID)
  OR EXISTS(SELECT 1 FROM dbo.Flights f WHERE f.FlightID=(SELECT TOP(1) FlightID FROM dbo.Flights
  WHERE AircraftID=@AircraftID AND Status<>'CANCELLED' AND FlightID<>COALESCE(@FlightID,0) AND DepartureTime>=@ArrivalTime ORDER BY DepartureTime)
  AND f.OriginID<>@DestinationID)
  THROW 51012,N'Máy bay không ở đúng sân bay trước hoặc sau chuyến này.',1;
 IF @FlightID IS NULL
 BEGIN
  INSERT dbo.Flights(FlightNumber,AircraftID,OriginID,DestinationID,DepartureTime,ArrivalTime)
   VALUES(@FlightNumber,@AircraftID,@OriginID,@DestinationID,@DepartureTime,@ArrivalTime);
  SET @FlightID=SCOPE_IDENTITY();
 END
 ELSE UPDATE dbo.Flights SET FlightNumber=@FlightNumber,AircraftID=@AircraftID,OriginID=@OriginID,
  DestinationID=@DestinationID,DepartureTime=@DepartureTime,ArrivalTime=@ArrivalTime WHERE FlightID=@FlightID;
 COMMIT;
 SELECT @FlightID FlightID;
END TRY BEGIN CATCH IF @@TRANCOUNT>0 ROLLBACK; THROW; END CATCH;
"""


_UPDATE_FLIGHT_STATUS = f"""
SET NOCOUNT ON;
SET XACT_ABORT ON;
DECLARE @FlightID int=?, @Status varchar(12)=?;
BEGIN TRY
 BEGIN TRAN;
 {LOCK_INVENTORY_SQL}
 DECLARE @old varchar(12)=(SELECT Status FROM dbo.Flights WHERE FlightID=@FlightID);
 IF @old IS NULL THROW 51006,N'Không tìm thấy chuyến bay.',1;
 IF @old=@Status BEGIN COMMIT; RETURN; END;
 IF @Status IS NULL OR NOT ((@old='SCHEDULED' AND @Status IN ('BOARDING','CANCELLED'))
  OR (@old='BOARDING' AND @Status IN ('DEPARTED','CANCELLED')) OR (@old='DEPARTED' AND @Status='ARRIVED'))
  THROW 51010,N'Chuyển trạng thái chuyến bay không hợp lệ.',1;
 DECLARE @affected TABLE(BookingID int PRIMARY KEY);
 IF @Status IN ('CANCELLED','BOARDING')
 BEGIN
  INSERT @affected SELECT b.BookingID FROM dbo.Bookings b WHERE b.Status='HELD'
   AND EXISTS(SELECT 1 FROM dbo.BookingSegments s WHERE s.BookingID=b.BookingID AND s.FlightID=@FlightID);
  IF @Status='CANCELLED'
  BEGIN
   INSERT @affected SELECT b.BookingID FROM dbo.Bookings b WHERE b.Status='CONFIRMED'
    AND EXISTS(SELECT 1 FROM dbo.BookingSegments s WHERE s.BookingID=b.BookingID AND s.FlightID=@FlightID);
   INSERT dbo.Payments(BookingID,IdempotencyKey,Amount,Kind,Status)
   SELECT b.BookingID,CONCAT('refund-booking-',b.BookingID),SUM(t.BaseFare+t.TaxAmount+t.SeatFee),'REFUND','SUCCESS'
   FROM @affected x JOIN dbo.Bookings b ON b.BookingID=x.BookingID
   JOIN dbo.BookingPassengers p ON p.BookingID=b.BookingID JOIN dbo.Tickets t ON t.BookingPassengerID=p.BookingPassengerID
   JOIN dbo.BookingSegments s ON s.BookingSegmentID=t.BookingSegmentID JOIN dbo.Flights f ON f.FlightID=s.FlightID
   WHERE b.Status='CONFIRMED' AND t.Status='VALID' AND f.Status IN ('SCHEDULED','BOARDING')
   GROUP BY b.BookingID;
  END;
  UPDATE t SET Status='VOID' FROM dbo.Tickets t JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID
  JOIN dbo.Bookings b ON b.BookingID=p.BookingID JOIN @affected x ON x.BookingID=b.BookingID
  JOIN dbo.BookingSegments s ON s.BookingSegmentID=t.BookingSegmentID JOIN dbo.Flights f ON f.FlightID=s.FlightID
  WHERE b.Status='HELD' OR (@Status='CANCELLED' AND f.Status IN ('SCHEDULED','BOARDING'));
  UPDATE a SET IsActive=0 FROM dbo.FlightSeatAssignments a JOIN dbo.Tickets t ON t.AssignmentID=a.AssignmentID
  JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID JOIN @affected x ON x.BookingID=p.BookingID WHERE t.Status='VOID';
  UPDATE b SET Status=CASE WHEN @Status='BOARDING' THEN 'EXPIRED' ELSE 'CANCELLED' END
  FROM dbo.Bookings b JOIN @affected x ON x.BookingID=b.BookingID
  WHERE NOT EXISTS(SELECT 1 FROM dbo.Tickets t JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID WHERE p.BookingID=b.BookingID AND t.Status='VALID');
 END;
 UPDATE dbo.Flights SET Status=@Status WHERE FlightID=@FlightID;
 COMMIT;
END TRY BEGIN CATCH IF @@TRANCOUNT>0 ROLLBACK; THROW; END CATCH;
"""


def save_flight(flight_id, flight_number, aircraft_id, origin_id, destination_id, departure_time, arrival_time):
    return query(_SAVE_FLIGHT, (
        flight_id, flight_number, aircraft_id, origin_id, destination_id, departure_time, arrival_time,
    ), one=True)


def update_flight_status(flight_id, status):
    query(_UPDATE_FLIGHT_STATUS, (flight_id, status))
