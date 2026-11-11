USE AeroFlow;
GO
-- Active ownership includes temporary holds and paid seats. Expiry releases ownership.
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='UX_Assignments_ActiveSeat')
 CREATE UNIQUE INDEX UX_Assignments_ActiveSeat ON dbo.FlightSeatAssignments(FlightID,SeatID) WHERE IsActive=1;
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='UX_Payments_SuccessCharge')
 CREATE UNIQUE INDEX UX_Payments_SuccessCharge ON dbo.Payments(BookingID) WHERE Kind='CHARGE' AND Status='SUCCESS';
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='UX_Payments_Refund')
 CREATE UNIQUE INDEX UX_Payments_Refund ON dbo.Payments(BookingID) WHERE Kind='REFUND';
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_Flights_Search')
 CREATE INDEX IX_Flights_Search ON dbo.Flights(OriginID,DestinationID,DepartureTime) INCLUDE(ArrivalTime,Status,AircraftID,FlightNumber);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_Bookings_Expiry')
 CREATE INDEX IX_Bookings_Expiry ON dbo.Bookings(Status,ExpiresAt) INCLUDE(UserID);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_Bookings_User')
 CREATE INDEX IX_Bookings_User ON dbo.Bookings(UserID,CreatedAt DESC);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_Payments_Report')
 CREATE INDEX IX_Payments_Report ON dbo.Payments(CreatedAt,Status,Kind) INCLUDE(Amount,BookingID);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_BP_Booking')
 CREATE INDEX IX_BP_Booking ON dbo.BookingPassengers(BookingID) INCLUDE(PassengerID);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_Segments_Flight')
 CREATE INDEX IX_Segments_Flight ON dbo.BookingSegments(FlightID,BookingID);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_Audit_Created')
 CREATE INDEX IX_Audit_Created ON dbo.AuditLogs(CreatedAt DESC);
GO
