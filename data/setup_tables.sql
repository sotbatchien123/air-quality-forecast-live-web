-- TiDB Setup Script - Run this as admin/database owner
-- Execute this script to create all required tables

CREATE TABLE IF NOT EXISTS `tree_green_data` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `province` VARCHAR(255),
    `district` VARCHAR(255),
    `green_area_m2` VARCHAR(255),
    `green_per_capita_m2` VARCHAR(255),
    `num_trees` VARCHAR(255),
    `co2_absorption_g_per_hour` VARCHAR(255),
    `co2_absorption_kg_per_hour` VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `population_southeast` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `district` VARCHAR(255),
    `province_city` VARCHAR(255),
    `type` VARCHAR(255),
    `area_km2` VARCHAR(255),
    `population` VARCHAR(255),
    `density_person_km2` VARCHAR(255),
    `emission_population_g_per_hour` VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `weather_hcm` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `date` VARCHAR(255),
    `hour` VARCHAR(255),
    `location_name` VARCHAR(255),
    `lat` VARCHAR(255),
    `lon` VARCHAR(255),
    `temperature_2m` VARCHAR(255),
    `relative_humidity_2m` VARCHAR(255),
    `precipitation` VARCHAR(255),
    `rain` VARCHAR(255),
    `wind_speed_10m` VARCHAR(255),
    `cloud_cover` VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `traffic_ho_chi_minh` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `date` VARCHAR(255),
    `hour` VARCHAR(255),
    `location_name` VARCHAR(255),
    `lat` VARCHAR(255),
    `lon` VARCHAR(255),
    `currentspeed` VARCHAR(255),
    `freeflowspeed` VARCHAR(255),
    `congestion_ratio` VARCHAR(255),
    `traffic_density` VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `traffic_long_an` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `date` VARCHAR(255),
    `hour` VARCHAR(255),
    `location_name` VARCHAR(255),
    `lat` VARCHAR(255),
    `lon` VARCHAR(255),
    `currentspeed` VARCHAR(255),
    `freeflowspeed` VARCHAR(255),
    `congestion_ratio` VARCHAR(255),
    `traffic_density` VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `traffic_dong_nai` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `date` VARCHAR(255),
    `hour` VARCHAR(255),
    `location_name` VARCHAR(255),
    `lat` VARCHAR(255),
    `lon` VARCHAR(255),
    `currentspeed` VARCHAR(255),
    `freeflowspeed` VARCHAR(255),
    `congestion_ratio` VARCHAR(255),
    `traffic_density` VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `traffic_tay_ninh` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `date` VARCHAR(255),
    `hour` VARCHAR(255),
    `location_name` VARCHAR(255),
    `lat` VARCHAR(255),
    `lon` VARCHAR(255),
    `currentspeed` VARCHAR(255),
    `freeflowspeed` VARCHAR(255),
    `congestion_ratio` VARCHAR(255),
    `traffic_density` VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `traffic_ba_ria_vung_tau` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `date` VARCHAR(255),
    `hour` VARCHAR(255),
    `location_name` VARCHAR(255),
    `lat` VARCHAR(255),
    `lon` VARCHAR(255),
    `currentspeed` VARCHAR(255),
    `freeflowspeed` VARCHAR(255),
    `congestion_ratio` VARCHAR(255),
    `traffic_density` VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `vehicle_count` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `location_name` VARCHAR(255),
    `province` VARCHAR(255),
    `total_vehicles` VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

