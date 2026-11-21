Proposal & Requirements Report
SJSU Campus Weather Monitoring & Alerts Platform

1. Project Overview
Our application is a web-based weather data platform that turns raw SJSU’s meteorology surface-station data (published as downloadable CSV files) into a searchable database. Today the data is only available as flat .csv files, which are hard to filter, compare and monitor trends over time. Our platform lets students/researchers explore campus weather history and get notified when conditions cross thresholds they’re tracking.    source: https://www.met.sjsu.edu/weather/sfcdata/
Primary users and roles:
Student (registered user): Browses and compares weather data, exports results, and creates personal alert rules.
Admin/Researcher: Imports new data files, manages stations and measurement types, reviews import history, and views all available tables.
Value: Students and researchers get fast, filterable access to campus weather trends (temperature, humidity, wind, solar radiation, rainfall) without handling raw CSV files, and automatic notifications for conditions that matter to them, such as high wind or heat.

2. Functional Requirements
Users can register, log in and manage their accounts.
Users can browse and search observations by station, measurement type and date range.
Users can view trends and statistics (minimum, maximum, average) for a selected period, displayed as tables and charts.
Users can compare measurements across time periods and across different stations.
Users can create, edit, enable/disable, and delete personal alert rules (e.g. “notify me when wind speed exceeds 30 mph”).
The system evaluates alert rules when new data arrives, records each triggered alert, and sends an in-app notification to the rule's owner.
Users can view their notifications and mark them as read.
Users can export filtered data as a CSV file.
Admins can upload weather CSV files and review import history (who imported what, when, how many rows, and whether it succeeded).

3. Non-Functional Requirements
Performance: User-facing queries (browsing, filtering, summary statistics) should return in under 4 seconds.
Indexing: Frequently queried fields, like station and timestamp on observations, must be indexed for running efficient queries. 
Integrity: Foreign key constraints enforce referential integrity across all related tables, and unique constraints prevent duplicate readings when the same file is imported twice.
Reliable imports: Each import runs as a single transaction, so a failed or invalid file leaves no partial data. Imported values are validated (e.g., correct data types and timestamps).
Security: Only authenticated users can create, update or delete records and access to admin functions is restricted by role. Passwords are stored hashed, never in plain text.

4. Data Model and Complexity Expectations
Entities :

User
Role (Student, Admin-Researcher)
Station
Weather Variables (temperature, humidity, wind speed, solar radiation, rainfall)
StationVariable (which variables each station reports and where in the source file)
DataImport
Observation (one timestamped reading event at a station)
ObservationValue (the measured value for each variable in an observation)
AlertRule
AlertEvent
Notification


How the data is related:
Each user has exactly one role, and a role can have many users.
A station reports many weather variables, and a weather variable can be reported by many stations.
A station has many observations, where each observation belongs to one station and has one value per variable measured.
Each observation is tied to the data import that loaded it, and each import is run by one admin user, so any import can be traced or rolled back.
A user can create many alert rules, where each rule watches one variable at one station and can trigger many alert events, producing a notification for the rule's owner.
User types: Student (registered user) with core create/view/update capabilities, plus an Admin/Researcher role with elevated permissions (import and management).
Functional features: The system supports 10 features: Account Management, Observation Search, Trends & Statistics, Comparison, Alert Rules, Alert Detection, Notifications, Data Export, Data Import (Admin) and System Management (Admin). 

5. Technology Stack
Backend: Python with Flask
Frontend: HTML/CSS with Bootstrap and JS, using a charting library for trend charts
Database: MySQL 
Other tools: GitHub for version control

6. Team Details
Include the names, student IDs, and email addresses of all team members.
Devarsh Shroff : 018412212, devarsh.shroff@sjsu.edu
Don Dang : 017536493, dang.dang@sjsu.edu
Hrishikesh Giri : 017867668, hrishikesh.giri@sjsu.edu
Kunj Shah : 016970226, kunj.shah@sjsu.edu
