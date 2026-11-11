-- SQL Server 2019 or later. Select a new database name before running this script.
USE master;
GO
IF DB_ID(N'AeroFlow') IS NULL CREATE DATABASE AeroFlow;
GO
USE AeroFlow;
GO
IF (SELECT compatibility_level FROM sys.databases WHERE name=DB_NAME()) < 150
 ALTER DATABASE AeroFlow SET COMPATIBILITY_LEVEL=150;
GO
