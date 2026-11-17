CREATE DATABASE IF NOT EXISTS sjsu_weather
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sjsu_weather;

CREATE TABLE IF NOT EXISTS roles (
  id TINYINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(32) NOT NULL UNIQUE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  role_id TINYINT UNSIGNED NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  display_name VARCHAR(100) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_user_role FOREIGN KEY (role_id) REFERENCES roles(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS stations (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(40) NOT NULL UNIQUE,
  name VARCHAR(120) NOT NULL,
  latitude DECIMAL(9,6) NULL,
  longitude DECIMAL(9,6) NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS weather_variables (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(50) NOT NULL UNIQUE,
  name VARCHAR(100) NOT NULL,
  unit VARCHAR(30) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS station_variables (
  station_id BIGINT UNSIGNED NOT NULL,
  variable_id BIGINT UNSIGNED NOT NULL,
  source_column VARCHAR(100) NOT NULL,
  PRIMARY KEY (station_id, variable_id),
  UNIQUE KEY uq_station_source_column (station_id, source_column),
  CONSTRAINT fk_sv_station FOREIGN KEY (station_id) REFERENCES stations(id),
  CONSTRAINT fk_sv_variable FOREIGN KEY (variable_id) REFERENCES weather_variables(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS data_imports (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  station_id BIGINT UNSIGNED NOT NULL,
  imported_by BIGINT UNSIGNED NOT NULL,
  filename VARCHAR(255) NOT NULL,
  file_hash CHAR(64) NOT NULL,
  status ENUM('processing', 'succeeded', 'failed') NOT NULL DEFAULT 'processing',
  rows_imported INT UNSIGNED NOT NULL DEFAULT 0,
  error_message TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TIMESTAMP NULL,
  UNIQUE KEY uq_import_file (station_id, file_hash),
  CONSTRAINT fk_import_station FOREIGN KEY (station_id) REFERENCES stations(id),
  CONSTRAINT fk_import_user FOREIGN KEY (imported_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS observations (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  station_id BIGINT UNSIGNED NOT NULL,
  data_import_id BIGINT UNSIGNED NOT NULL,
  observed_at DATETIME NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_station_time (station_id, observed_at),
  KEY idx_observation_time (observed_at),
  CONSTRAINT fk_observation_station FOREIGN KEY (station_id) REFERENCES stations(id),
  CONSTRAINT fk_observation_import FOREIGN KEY (data_import_id) REFERENCES data_imports(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS observation_values (
  observation_id BIGINT UNSIGNED NOT NULL,
  variable_id BIGINT UNSIGNED NOT NULL,
  value DECIMAL(16,6) NOT NULL,
  PRIMARY KEY (observation_id, variable_id),
  KEY idx_value_variable (variable_id, value),
  CONSTRAINT fk_value_observation FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE CASCADE,
  CONSTRAINT fk_value_variable FOREIGN KEY (variable_id) REFERENCES weather_variables(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS alert_rules (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  station_id BIGINT UNSIGNED NOT NULL,
  variable_id BIGINT UNSIGNED NOT NULL,
  operator ENUM('>', '>=', '<', '<=', '=') NOT NULL,
  threshold DECIMAL(16,6) NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_rule_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_rule_station FOREIGN KEY (station_id) REFERENCES stations(id),
  CONSTRAINT fk_rule_variable FOREIGN KEY (variable_id) REFERENCES weather_variables(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS alert_events (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  alert_rule_id BIGINT UNSIGNED NOT NULL,
  observation_id BIGINT UNSIGNED NOT NULL,
  observed_value DECIMAL(16,6) NOT NULL,
  triggered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_rule_observation (alert_rule_id, observation_id),
  CONSTRAINT fk_event_rule FOREIGN KEY (alert_rule_id) REFERENCES alert_rules(id) ON DELETE CASCADE,
  CONSTRAINT fk_event_observation FOREIGN KEY (observation_id) REFERENCES observations(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS notifications (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  alert_event_id BIGINT UNSIGNED NOT NULL UNIQUE,
  message VARCHAR(500) NOT NULL,
  is_read BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_notification_user_read (user_id, is_read, created_at),
  CONSTRAINT fk_notification_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_notification_event FOREIGN KEY (alert_event_id) REFERENCES alert_events(id) ON DELETE CASCADE
) ENGINE=InnoDB;

INSERT IGNORE INTO roles (name) VALUES ('student'), ('admin');

