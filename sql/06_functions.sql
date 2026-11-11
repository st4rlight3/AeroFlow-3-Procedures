USE AeroFlow;
GO
CREATE OR ALTER FUNCTION dbo.fn_CalculateTicketPrice(@Base decimal(14,2),@Tax decimal(5,4))
RETURNS decimal(14,2) WITH SCHEMABINDING AS
BEGIN
 RETURN CONVERT(decimal(14,2),@Base+ROUND(@Base*@Tax,2));
END;
GO
CREATE OR ALTER FUNCTION dbo.fn_GetFlightOccupancyRate(@FlightID int)
RETURNS decimal(5,2) AS
BEGIN
 DECLARE @total int,@sold int;
 SELECT @total=COUNT(*) FROM dbo.AircraftSeats s JOIN dbo.Flights f ON f.AircraftID=s.AircraftID
 WHERE f.FlightID=@FlightID AND s.IsActive=1;
 SELECT @sold=COUNT(*) FROM dbo.FlightSeatAssignments a JOIN dbo.Tickets t ON t.AssignmentID=a.AssignmentID
 WHERE a.FlightID=@FlightID AND a.IsActive=1 AND t.Status='VALID';
 RETURN CONVERT(decimal(5,2),COALESCE(100.0*@sold/NULLIF(@total,0),0));
END;
GO
