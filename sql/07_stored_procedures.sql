USE AeroFlow;
GO

-- Xem sơ đồ ghế và tình trạng giữ ghế của một chuyến.
CREATE OR ALTER PROCEDURE dbo.sp_GetAvailableSeats @FlightID int AS
BEGIN
 SET NOCOUNT ON;
 SELECT s.SeatID,s.SeatNumber,s.RowNumber,s.ColumnLetter,s.Cabin,s.SeatFee,s.IsPriority,
 CAST(CASE WHEN a.AssignmentID IS NULL THEN 1 ELSE 0 END AS bit) AS Available
 FROM dbo.AircraftSeats s JOIN dbo.Flights f ON f.AircraftID=s.AircraftID
 LEFT JOIN dbo.FlightSeatAssignments a ON a.FlightID=f.FlightID AND a.SeatID=s.SeatID AND a.IsActive=1
 WHERE f.FlightID=@FlightID AND s.IsActive=1 ORDER BY s.RowNumber,s.ColumnLetter;
END;
GO

-- Cập nhật giá của chuyến đang mở bán, hoặc thêm giá nếu chưa có.
CREATE OR ALTER PROCEDURE dbo.sp_SaveFare @FlightID int,@FareClassID int,@BasePrice decimal(14,2),@TaxRate decimal(5,4) AS
BEGIN
 SET NOCOUNT ON; SET XACT_ABORT ON;
 BEGIN TRY
  BEGIN TRAN;
  -- Dùng cùng khóa với luồng đặt vé để giá không đổi giữa lúc xác nhận.
  DECLARE @result int;
  EXEC @result=sys.sp_getapplock @Resource='AeroFlow:inventory',
   @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000;
  IF @result<0 THROW 51001,N'Đặt chỗ đang được xử lý. Vui lòng thử lại.',1;
  IF NOT EXISTS(SELECT 1 FROM dbo.Flights WHERE FlightID=@FlightID AND Status='SCHEDULED') THROW 51010,N'Chỉ sửa giá chuyến đang mở bán.',1;
  IF NOT EXISTS(SELECT 1 FROM dbo.Flights f JOIN dbo.AircraftSeats s ON s.AircraftID=f.AircraftID AND s.IsActive=1
   JOIN dbo.FareClasses c ON c.Cabin=s.Cabin WHERE f.FlightID=@FlightID AND c.FareClassID=@FareClassID)
   THROW 51004,N'Máy bay không có ghế thuộc khoang của hạng vé này.',1;
  UPDATE dbo.FlightFares SET BasePrice=@BasePrice,TaxRate=@TaxRate WHERE FlightID=@FlightID AND FareClassID=@FareClassID;
  IF @@ROWCOUNT=0 INSERT dbo.FlightFares(FlightID,FareClassID,BasePrice,TaxRate) VALUES(@FlightID,@FareClassID,@BasePrice,@TaxRate);
  COMMIT;
 END TRY BEGIN CATCH IF @@TRANCOUNT>0 ROLLBACK; THROW; END CATCH;
END;
GO

-- Tổng hợp tiền thu, tiền hoàn và doanh thu ròng theo ngày.
CREATE OR ALTER PROCEDURE dbo.sp_GetRevenueReport @From date,@To date AS
BEGIN
 SET NOCOUNT ON;
 IF @From IS NULL OR @To IS NULL OR @From>@To OR @To='99991231' THROW 51004,N'Khoảng ngày không hợp lệ.',1;
 SELECT CONVERT(date,CreatedAt) [Date],
 SUM(CASE WHEN Kind='CHARGE' THEN Amount ELSE 0 END) GrossRevenue,
 SUM(CASE WHEN Kind='REFUND' THEN Amount ELSE 0 END) Refunds,
 SUM(CASE WHEN Kind='CHARGE' THEN Amount ELSE -Amount END) NetRevenue
 FROM dbo.Payments WHERE Status='SUCCESS' AND CreatedAt>=@From AND CreatedAt<DATEADD(day,1,@To)
 GROUP BY CONVERT(date,CreatedAt) ORDER BY [Date];
END;
GO
