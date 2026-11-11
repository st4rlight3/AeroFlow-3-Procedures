USE AeroFlow;
GO
SET XACT_ABORT ON;
IF EXISTS(SELECT 1 FROM sys.tables WHERE is_ms_shipped=0)
 THROW 51000,N'Cơ sở dữ liệu đã có bảng. Hãy chọn một cơ sở dữ liệu trống.',1;
CREATE TABLE dbo.Roles (
 RoleID int IDENTITY CONSTRAINT PK_Roles PRIMARY KEY,
 Name varchar(20) NOT NULL CONSTRAINT UQ_Roles_Name UNIQUE,
 CONSTRAINT CK_Roles_Name CHECK(Name IN ('ADMIN','CUSTOMER'))
);
CREATE TABLE dbo.Users (
 UserID int IDENTITY CONSTRAINT PK_Users PRIMARY KEY,
 RoleID int NOT NULL CONSTRAINT FK_Users_Roles REFERENCES dbo.Roles,
 Email nvarchar(254) NOT NULL CONSTRAINT UQ_Users_Email UNIQUE,
 FullName nvarchar(120) NOT NULL,
 PasswordHash varchar(256) NOT NULL,
 Phone varchar(20) NULL,
 IsActive bit NOT NULL CONSTRAINT DF_Users_Active DEFAULT 1,
 SessionVersion int NOT NULL CONSTRAINT DF_Users_Session DEFAULT 1,
 CreatedAt datetime2(0) NOT NULL CONSTRAINT DF_Users_Created DEFAULT SYSUTCDATETIME(),
 CONSTRAINT CK_Users_Name CHECK(LEN(FullName)>=2),
 CONSTRAINT CK_Users_Email CHECK(Email LIKE '%_@_%._%')
);
CREATE TABLE dbo.Airports (
 AirportID int IDENTITY CONSTRAINT PK_Airports PRIMARY KEY,
 Code char(3) NOT NULL CONSTRAINT UQ_Airports_Code UNIQUE,
 Name nvarchar(120) NOT NULL,
 City nvarchar(80) NOT NULL,
 CountryName nvarchar(80) NOT NULL CONSTRAINT DF_Airports_Country DEFAULT N'Việt Nam',
 IanaTimeZone nvarchar(64) NOT NULL CONSTRAINT DF_Airports_TimeZone DEFAULT N'Asia/Ho_Chi_Minh',
 IsActive bit NOT NULL CONSTRAINT DF_Airports_Active DEFAULT 1,
 CONSTRAINT CK_Airports_Code CHECK(Code NOT LIKE '%[^A-Z]%')
);
CREATE TABLE dbo.Airlines (
 AirlineID int IDENTITY CONSTRAINT PK_Airlines PRIMARY KEY,
 Code char(2) NOT NULL CONSTRAINT UQ_Airlines_Code UNIQUE,
 Name nvarchar(100) NOT NULL
);
CREATE TABLE dbo.Aircraft (
 AircraftID int IDENTITY CONSTRAINT PK_Aircraft PRIMARY KEY,
 AirlineID int NOT NULL CONSTRAINT FK_Aircraft_Airlines REFERENCES dbo.Airlines,
 Registration varchar(20) NOT NULL CONSTRAINT UQ_Aircraft_Registration UNIQUE,
 Model nvarchar(80) NOT NULL,
 IsActive bit NOT NULL CONSTRAINT DF_Aircraft_Active DEFAULT 1
);
CREATE TABLE dbo.FareClasses (
 FareClassID int IDENTITY CONSTRAINT PK_FareClasses PRIMARY KEY,
 Code varchar(10) NOT NULL CONSTRAINT UQ_FareClasses_Code UNIQUE,
 Name nvarchar(60) NOT NULL,
 Cabin varchar(12) NOT NULL,
 BaggageKg int NOT NULL,
 RefundPercent decimal(5,2) NOT NULL,
 CONSTRAINT CK_FareClasses_Cabin CHECK(Cabin IN ('ECONOMY','PREMIUM','BUSINESS','FIRST')),
 CONSTRAINT CK_FareClasses_Baggage CHECK(BaggageKg BETWEEN 0 AND 60),
 CONSTRAINT CK_FareClasses_Refund CHECK(RefundPercent BETWEEN 0 AND 100)
);
CREATE TABLE dbo.AircraftSeats (
 SeatID int IDENTITY CONSTRAINT PK_AircraftSeats PRIMARY KEY,
 AircraftID int NOT NULL CONSTRAINT FK_Seats_Aircraft REFERENCES dbo.Aircraft,
 SeatNumber varchar(5) NOT NULL,
 RowNumber int NOT NULL,
 ColumnLetter char(1) NOT NULL,
 Cabin varchar(12) NOT NULL,
 IsActive bit NOT NULL CONSTRAINT DF_Seats_Active DEFAULT 1,
 SeatFee decimal(14,2) NOT NULL CONSTRAINT DF_Seats_Fee DEFAULT 0,
 IsPriority bit NOT NULL CONSTRAINT DF_Seats_Priority DEFAULT 0,
 CONSTRAINT UQ_Seats_Number UNIQUE(AircraftID,SeatNumber),
 CONSTRAINT UQ_Seats_Position UNIQUE(AircraftID,RowNumber,ColumnLetter),
 CONSTRAINT UQ_Seats_AircraftKey UNIQUE(SeatID,AircraftID),
 CONSTRAINT CK_Seats_Row CHECK(RowNumber BETWEEN 1 AND 80),
 CONSTRAINT CK_Seats_Fee CHECK(SeatFee>=0),
 CONSTRAINT CK_Seats_Column CHECK(ColumnLetter IN ('A','B','C','D','E','F')),
 CONSTRAINT CK_Seats_Number CHECK(SeatNumber=ColumnLetter+CONVERT(varchar(3),RowNumber)),
 CONSTRAINT CK_Seats_Cabin CHECK(Cabin IN ('ECONOMY','PREMIUM','BUSINESS','FIRST'))
);
CREATE TABLE dbo.Flights (
 FlightID int IDENTITY CONSTRAINT PK_Flights PRIMARY KEY,
 FlightNumber varchar(8) NOT NULL,
 AircraftID int NOT NULL CONSTRAINT FK_Flights_Aircraft REFERENCES dbo.Aircraft,
 OriginID int NOT NULL CONSTRAINT FK_Flights_Origin REFERENCES dbo.Airports(AirportID),
 DestinationID int NOT NULL CONSTRAINT FK_Flights_Destination REFERENCES dbo.Airports(AirportID),
 DepartureTime datetime2(0) NOT NULL,
 ArrivalTime datetime2(0) NOT NULL,
 Status varchar(12) NOT NULL CONSTRAINT DF_Flights_Status DEFAULT 'SCHEDULED',
 CONSTRAINT UQ_Flights_NumberTime UNIQUE(FlightNumber,DepartureTime),
 CONSTRAINT UQ_Flights_AircraftKey UNIQUE(FlightID,AircraftID),
 CONSTRAINT CK_Flights_Route CHECK(OriginID<>DestinationID),
 CONSTRAINT CK_Flights_Time CHECK(ArrivalTime>DepartureTime),
 CONSTRAINT CK_Flights_Status CHECK(Status IN ('SCHEDULED','BOARDING','DEPARTED','ARRIVED','CANCELLED'))
);
CREATE TABLE dbo.FlightFares (
 FlightID int NOT NULL CONSTRAINT FK_Fares_Flight REFERENCES dbo.Flights,
 FareClassID int NOT NULL CONSTRAINT FK_Fares_Class REFERENCES dbo.FareClasses,
 BasePrice decimal(14,2) NOT NULL,
 TaxRate decimal(5,4) NOT NULL CONSTRAINT DF_Fares_Tax DEFAULT 0.10,
 CONSTRAINT PK_FlightFares PRIMARY KEY(FlightID,FareClassID),
 CONSTRAINT CK_Fares_Price CHECK(BasePrice>0 AND BasePrice<=100000000),
 CONSTRAINT CK_Fares_Tax CHECK(TaxRate BETWEEN 0 AND 1)
);
CREATE TABLE dbo.Passengers (
 PassengerID int IDENTITY CONSTRAINT PK_Passengers PRIMARY KEY,
 FullName nvarchar(120) NOT NULL,
 DateOfBirth date NOT NULL,
 DocumentNumber nvarchar(30) NOT NULL,
 CONSTRAINT CK_Passengers_Name CHECK(LEN(FullName)>=2),
 CONSTRAINT CK_Passengers_Doc CHECK(LEN(DocumentNumber)>=5)
);
CREATE TABLE dbo.Bookings (
 BookingID int IDENTITY CONSTRAINT PK_Bookings PRIMARY KEY,
 PNR char(8) NOT NULL CONSTRAINT UQ_Bookings_PNR UNIQUE,
 UserID int NOT NULL CONSTRAINT FK_Bookings_User REFERENCES dbo.Users,
 Status varchar(12) NOT NULL CONSTRAINT DF_Bookings_Status DEFAULT 'HELD',
 CreatedAt datetime2(0) NOT NULL CONSTRAINT DF_Bookings_Created DEFAULT SYSUTCDATETIME(),
 ExpiresAt datetime2(0) NOT NULL,
 CONSTRAINT CK_Bookings_Status CHECK(Status IN ('HELD','CONFIRMED','CANCELLED','EXPIRED')),
 CONSTRAINT CK_Bookings_Expiry CHECK(ExpiresAt>=CreatedAt)
);
CREATE TABLE dbo.BookingSegments (
 BookingSegmentID int IDENTITY CONSTRAINT PK_BookingSegments PRIMARY KEY,
 BookingID int NOT NULL CONSTRAINT FK_Segments_Booking REFERENCES dbo.Bookings,
 FlightID int NOT NULL CONSTRAINT FK_Segments_Flight REFERENCES dbo.Flights,
 SegmentOrder tinyint NOT NULL,
 CONSTRAINT UQ_Segments_Order UNIQUE(BookingID,SegmentOrder),
 CONSTRAINT UQ_Segments_Flight UNIQUE(BookingID,FlightID),
 CONSTRAINT CK_Segments_Order CHECK(SegmentOrder IN (1,2))
);
CREATE TABLE dbo.BookingPassengers (
 BookingPassengerID int IDENTITY CONSTRAINT PK_BookingPassengers PRIMARY KEY,
 BookingID int NOT NULL CONSTRAINT FK_BP_Booking REFERENCES dbo.Bookings,
 PassengerID int NOT NULL CONSTRAINT FK_BP_Passenger REFERENCES dbo.Passengers,
 CONSTRAINT UQ_BP_Passenger UNIQUE(BookingID,PassengerID),
 CONSTRAINT UQ_BP_BookingKey UNIQUE(BookingPassengerID,BookingID)
);
CREATE TABLE dbo.FlightSeatAssignments (
 AssignmentID int IDENTITY CONSTRAINT PK_Assignments PRIMARY KEY,
 FlightID int NOT NULL CONSTRAINT FK_Assignments_Flight REFERENCES dbo.Flights,
 SeatID int NOT NULL CONSTRAINT FK_Assignments_Seat REFERENCES dbo.AircraftSeats,
 IsActive bit NOT NULL CONSTRAINT DF_Assignments_Active DEFAULT 1
);
CREATE TABLE dbo.Tickets (
 TicketID int IDENTITY CONSTRAINT PK_Tickets PRIMARY KEY,
 AssignmentID int NOT NULL CONSTRAINT UQ_Tickets_Assignment UNIQUE CONSTRAINT FK_Tickets_Assignment REFERENCES dbo.FlightSeatAssignments,
 TicketNumber varchar(20) NOT NULL CONSTRAINT UQ_Tickets_Number UNIQUE,
 BookingPassengerID int NOT NULL
   CONSTRAINT FK_Tickets_BP REFERENCES dbo.BookingPassengers,
 BookingSegmentID int NOT NULL CONSTRAINT FK_Tickets_Segment REFERENCES dbo.BookingSegments,
 FareClassID int NOT NULL CONSTRAINT FK_Tickets_Class REFERENCES dbo.FareClasses,
 BaseFare decimal(14,2) NOT NULL,
 TaxAmount decimal(14,2) NOT NULL,
 SeatFee decimal(14,2) NOT NULL,
 BaggageKg int NOT NULL,
 RefundPercent decimal(5,2) NOT NULL,
 Status varchar(12) NOT NULL CONSTRAINT DF_Tickets_Status DEFAULT 'PENDING',
 CONSTRAINT UQ_Tickets_PassengerSegment UNIQUE(BookingPassengerID,BookingSegmentID),
 CONSTRAINT CK_Tickets_Price CHECK(BaseFare>0 AND TaxAmount>=0 AND SeatFee>=0
   AND BaseFare+TaxAmount+SeatFee<=999999999999.99),
 CONSTRAINT CK_Tickets_Baggage CHECK(BaggageKg BETWEEN 0 AND 60),
 CONSTRAINT CK_Tickets_Refund CHECK(RefundPercent BETWEEN 0 AND 100),
 CONSTRAINT CK_Tickets_Status CHECK(Status IN ('PENDING','VALID','VOID'))
);
CREATE TABLE dbo.Payments (
 PaymentID int IDENTITY CONSTRAINT PK_Payments PRIMARY KEY,
 BookingID int NOT NULL CONSTRAINT FK_Payments_Booking REFERENCES dbo.Bookings,
 IdempotencyKey varchar(80) NOT NULL CONSTRAINT UQ_Payments_Key UNIQUE,
 Amount decimal(14,2) NOT NULL,
 Kind varchar(10) NOT NULL,
 Status varchar(10) NOT NULL,
 CreatedAt datetime2(0) NOT NULL CONSTRAINT DF_Payments_Created DEFAULT SYSUTCDATETIME(),
 CONSTRAINT CK_Payments_Amount CHECK(Amount>=0),
 CONSTRAINT CK_Payments_Kind CHECK(Kind IN ('CHARGE','REFUND')),
 CONSTRAINT CK_Payments_Status CHECK(Status IN ('SUCCESS','FAILED')),
 CONSTRAINT CK_Payments_Refund CHECK(Kind='CHARGE' OR Status='SUCCESS')
);
CREATE TABLE dbo.AuditLogs (
 AuditID bigint IDENTITY CONSTRAINT PK_AuditLogs PRIMARY KEY,
 ActorID int NULL CONSTRAINT FK_Audit_User REFERENCES dbo.Users,
 Entity varchar(40) NOT NULL,
 EntityID int NOT NULL,
 Action varchar(40) NOT NULL,
 Details nvarchar(1000) NULL,
 CreatedAt datetime2(0) NOT NULL CONSTRAINT DF_Audit_Created DEFAULT SYSUTCDATETIME()
);
GO
