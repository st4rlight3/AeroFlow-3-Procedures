USE AeroFlow;
GO
CREATE OR ALTER VIEW dbo.vw_FlightAvailability AS
 SELECT f.FlightID,f.FlightNumber,f.AircraftID,f.OriginID,f.DestinationID,
 o.Code OriginCode,o.City OriginCity,o.IanaTimeZone OriginTimeZone,
 d.Code DestinationCode,d.City DestinationCity,d.IanaTimeZone DestinationTimeZone,
 f.DepartureTime,f.ArrivalTime,f.Status,a.Model,l.Name AirlineName,l.Code AirlineCode,
 (SELECT COUNT(*) FROM dbo.AircraftSeats s WHERE s.AircraftID=f.AircraftID AND s.IsActive=1) TotalSeats,
 (SELECT COUNT(*) FROM dbo.AircraftSeats s WHERE s.AircraftID=f.AircraftID AND s.IsActive=1)
 - (SELECT COUNT(*) FROM dbo.FlightSeatAssignments x JOIN dbo.Tickets t ON t.AssignmentID=x.AssignmentID
    JOIN dbo.BookingPassengers bp ON bp.BookingPassengerID=t.BookingPassengerID JOIN dbo.Bookings b ON b.BookingID=bp.BookingID
    WHERE x.FlightID=f.FlightID AND x.IsActive=1 AND (t.Status='VALID' OR (b.Status='HELD' AND b.ExpiresAt>SYSUTCDATETIME()))) AvailableSeats,
 (SELECT MIN(dbo.fn_CalculateTicketPrice(ff.BasePrice,ff.TaxRate)+s.SeatFee)
  FROM dbo.FlightFares ff JOIN dbo.FareClasses c ON c.FareClassID=ff.FareClassID
  JOIN dbo.AircraftSeats s ON s.AircraftID=f.AircraftID AND s.Cabin=c.Cabin AND s.IsActive=1
  WHERE ff.FlightID=f.FlightID AND NOT EXISTS(
   SELECT 1 FROM dbo.FlightSeatAssignments x JOIN dbo.Tickets t ON t.AssignmentID=x.AssignmentID
   JOIN dbo.BookingPassengers bp ON bp.BookingPassengerID=t.BookingPassengerID JOIN dbo.Bookings b ON b.BookingID=bp.BookingID
   WHERE x.FlightID=f.FlightID AND x.SeatID=s.SeatID AND x.IsActive=1
     AND (t.Status='VALID' OR (b.Status='HELD' AND b.ExpiresAt>SYSUTCDATETIME())))) FromPrice
 FROM dbo.Flights f JOIN dbo.Airports o ON o.AirportID=f.OriginID
 JOIN dbo.Airports d ON d.AirportID=f.DestinationID JOIN dbo.Aircraft a ON a.AircraftID=f.AircraftID
 JOIN dbo.Airlines l ON l.AirlineID=a.AirlineID;
GO
CREATE OR ALTER VIEW dbo.vw_BookingDetails AS
 SELECT b.BookingID,b.PNR,b.UserID,s.FlightID,b.Status,b.CreatedAt,b.ExpiresAt,
 u.FullName CustomerName,u.Email,f.FlightNumber,o.Code OriginCode,d.Code DestinationCode,f.DepartureTime,f.ArrivalTime,
 o.IanaTimeZone OriginTimeZone,d.IanaTimeZone DestinationTimeZone,
 (SELECT COUNT(*) FROM dbo.BookingSegments x WHERE x.BookingID=b.BookingID) SegmentCount,
 r.FlightNumber ReturnFlightNumber,r.DepartureTime ReturnDepartureTime,r.ArrivalTime ReturnArrivalTime,
 COALESCE((SELECT SUM(t.BaseFare+t.TaxAmount+t.SeatFee) FROM dbo.Tickets t JOIN dbo.BookingPassengers p ON p.BookingPassengerID=t.BookingPassengerID WHERE p.BookingID=b.BookingID),0) TotalAmount,
 (SELECT COUNT(*) FROM dbo.BookingPassengers p WHERE p.BookingID=b.BookingID) PassengerCount
 FROM dbo.Bookings b JOIN dbo.Users u ON u.UserID=b.UserID
 JOIN dbo.BookingSegments s ON s.BookingID=b.BookingID AND s.SegmentOrder=1
 JOIN dbo.Flights f ON f.FlightID=s.FlightID
 JOIN dbo.Airports o ON o.AirportID=f.OriginID
 JOIN dbo.Airports d ON d.AirportID=f.DestinationID
 LEFT JOIN dbo.BookingSegments rs ON rs.BookingID=b.BookingID AND rs.SegmentOrder=2
 LEFT JOIN dbo.Flights r ON r.FlightID=rs.FlightID;
GO
CREATE OR ALTER VIEW dbo.vw_MonthlyRevenue AS
 SELECT YEAR(CreatedAt) [Year],MONTH(CreatedAt) [Month],
 SUM(CASE WHEN Kind='CHARGE' THEN Amount ELSE 0 END) GrossRevenue,
 SUM(CASE WHEN Kind='REFUND' THEN Amount ELSE 0 END) Refunds,
 SUM(CASE WHEN Kind='CHARGE' THEN Amount ELSE -Amount END) NetRevenue,
 SUM(CASE WHEN Kind='CHARGE' THEN 1 ELSE 0 END) PaidBookings
 FROM dbo.Payments WHERE Status='SUCCESS' GROUP BY YEAR(CreatedAt),MONTH(CreatedAt);
GO
CREATE OR ALTER VIEW dbo.vw_FlightOccupancy AS
 SELECT f.FlightID,f.FlightNumber,f.DepartureTime,
 (SELECT COUNT(*) FROM dbo.AircraftSeats s WHERE s.AircraftID=f.AircraftID AND s.IsActive=1) TotalSeats,
 (SELECT COUNT(*) FROM dbo.FlightSeatAssignments x JOIN dbo.Tickets t ON t.AssignmentID=x.AssignmentID
  WHERE x.FlightID=f.FlightID AND x.IsActive=1 AND t.Status='VALID') SoldSeats
 FROM dbo.Flights f;
GO
