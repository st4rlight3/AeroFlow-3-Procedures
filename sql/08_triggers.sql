USE AeroFlow;
GO
CREATE OR ALTER TRIGGER dbo.tr_Bookings_Audit ON dbo.Bookings AFTER INSERT,UPDATE AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM inserted b JOIN dbo.BookingPassengers p ON p.BookingID=b.BookingID
  JOIN dbo.Tickets t ON t.BookingPassengerID=p.BookingPassengerID WHERE t.Status='VALID' AND b.Status<>'CONFIRMED')
  THROW 51004,N'Đặt chỗ có vé còn hiệu lực phải ở trạng thái đã xác nhận.',1;
 IF EXISTS(SELECT 1 FROM inserted b WHERE b.Status='CONFIRMED' AND NOT EXISTS(
  SELECT 1 FROM dbo.Payments p WHERE p.BookingID=b.BookingID AND p.Kind='CHARGE' AND p.Status='SUCCESS'))
  THROW 51004,N'Chỉ xác nhận đặt chỗ đã thanh toán thành công.',1;
 IF EXISTS(SELECT 1 FROM inserted i JOIN deleted d ON d.BookingID=i.BookingID WHERE i.UserID<>d.UserID OR i.PNR<>d.PNR)
  THROW 51011,N'Không thay chủ sở hữu hoặc mã đặt chỗ.',1;
 INSERT dbo.AuditLogs(ActorID,Entity,EntityID,Action,Details)
 SELECT TRY_CONVERT(int,SESSION_CONTEXT(N'ActorID')),'Bookings',i.BookingID,
 CASE WHEN d.BookingID IS NULL THEN 'CREATE' ELSE 'STATUS_CHANGE' END,CONCAT(COALESCE(d.Status,'NEW'),' -> ',i.Status)
 FROM inserted i LEFT JOIN deleted d ON d.BookingID=i.BookingID WHERE d.BookingID IS NULL OR d.Status<>i.Status;
END;
GO
CREATE OR ALTER TRIGGER dbo.tr_Flights_Audit ON dbo.Flights AFTER INSERT,UPDATE AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM inserted i JOIN deleted d ON d.FlightID=i.FlightID
  WHERE (i.AircraftID<>d.AircraftID OR i.OriginID<>d.OriginID OR i.DestinationID<>d.DestinationID
   OR i.DepartureTime<>d.DepartureTime OR i.ArrivalTime<>d.ArrivalTime OR i.FlightNumber<>d.FlightNumber)
   AND EXISTS(SELECT 1 FROM dbo.BookingSegments s WHERE s.FlightID=i.FlightID))
  THROW 51011,N'Không sửa lịch trình đã có lịch sử đặt vé.',1;
 INSERT dbo.AuditLogs(ActorID,Entity,EntityID,Action,Details)
 SELECT TRY_CONVERT(int,SESSION_CONTEXT(N'ActorID')),'Flights',i.FlightID,
 CASE WHEN d.FlightID IS NULL THEN 'CREATE' ELSE 'UPDATE' END,
 CONCAT(COALESCE(d.Status,'NEW'),' -> ',i.Status,': ',i.FlightNumber)
 FROM inserted i LEFT JOIN deleted d ON d.FlightID=i.FlightID;
END;
GO
CREATE OR ALTER TRIGGER dbo.tr_Assignments_Integrity ON dbo.FlightSeatAssignments AFTER INSERT,UPDATE AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM inserted a JOIN dbo.Flights f ON f.FlightID=a.FlightID
  JOIN dbo.AircraftSeats s ON s.SeatID=a.SeatID WHERE s.AircraftID<>f.AircraftID)
  THROW 51004,N'Ghế không thuộc máy bay của chuyến bay.',1;
 IF EXISTS(SELECT 1 FROM inserted i JOIN deleted d ON d.AssignmentID=i.AssignmentID
  WHERE i.FlightID<>d.FlightID OR i.SeatID<>d.SeatID)
  THROW 51011,N'Lịch sử cấp ghế không được thay đổi.',1;
END;
GO
CREATE OR ALTER TRIGGER dbo.tr_Tickets_Integrity ON dbo.Tickets AFTER INSERT,UPDATE AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM inserted t JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID
  JOIN dbo.Bookings b ON b.BookingID=p.BookingID JOIN dbo.BookingSegments g ON g.BookingSegmentID=t.BookingSegmentID
  JOIN dbo.FlightSeatAssignments a ON a.AssignmentID=t.AssignmentID JOIN dbo.AircraftSeats s ON s.SeatID=a.SeatID
  JOIN dbo.FareClasses c ON c.FareClassID=t.FareClassID
  WHERE g.BookingID<>p.BookingID OR a.FlightID<>g.FlightID OR s.Cabin<>c.Cabin
   OR (t.Status='VALID' AND (b.Status<>'CONFIRMED' OR a.IsActive<>1)) OR (t.Status='PENDING' AND b.Status<>'HELD'))
  THROW 51004,N'Vé, hành trình, ghế và hạng vé không nhất quán.',1;
 IF EXISTS(SELECT 1 FROM inserted i JOIN deleted d ON d.TicketID=i.TicketID
  WHERE i.AssignmentID<>d.AssignmentID OR i.BookingPassengerID<>d.BookingPassengerID
   OR i.BookingSegmentID<>d.BookingSegmentID OR i.FareClassID<>d.FareClassID OR i.TicketNumber<>d.TicketNumber
   OR i.BaseFare<>d.BaseFare OR i.TaxAmount<>d.TaxAmount OR i.SeatFee<>d.SeatFee OR i.BaggageKg<>d.BaggageKg
   OR i.RefundPercent<>d.RefundPercent OR (d.Status='VOID' AND i.Status<>'VOID'))
  THROW 51011,N'Không sửa liên kết, giá hoặc quyền lợi của vé đã tạo.',1;
END;
GO
CREATE OR ALTER TRIGGER dbo.tr_Payments_Audit ON dbo.Payments AFTER INSERT AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM inserted r WHERE r.Kind='REFUND' AND r.Amount>COALESCE((
  SELECT SUM(c.Amount) FROM dbo.Payments c WHERE c.BookingID=r.BookingID AND c.Kind='CHARGE' AND c.Status='SUCCESS'),0))
  THROW 51004,N'Tiền hoàn không được vượt số tiền đã thanh toán.',1;
 INSERT dbo.AuditLogs(ActorID,Entity,EntityID,Action,Details)
 SELECT TRY_CONVERT(int,SESSION_CONTEXT(N'ActorID')),'Payments',PaymentID,Kind,CONCAT(Status,': ',Amount) FROM inserted;
END;
GO
CREATE OR ALTER TRIGGER dbo.tr_Seats_ImmutableLayout ON dbo.AircraftSeats AFTER INSERT,UPDATE,DELETE AS
BEGIN
 SET NOCOUNT ON;
 IF EXISTS(SELECT 1 FROM dbo.Flights f JOIN (SELECT AircraftID FROM inserted UNION SELECT AircraftID FROM deleted) x ON x.AircraftID=f.AircraftID)
  THROW 51011,N'Sơ đồ ghế đã dùng cho chuyến bay không thể thay đổi. Hãy tạo máy bay mới.',1;
END;
GO
