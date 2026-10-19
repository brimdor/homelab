-- Ensure the application database exists
CREATE DATABASE IF NOT EXISTS bc_database CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Switch to the application database for table creation
USE bc_database;

-- Create the Users table
CREATE TABLE IF NOT EXISTS Users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    steamid VARCHAR(32) UNIQUE NULL,
    steam_api_key VARCHAR(128),
    preferred_theme ENUM('light', 'dark') DEFAULT 'light',
    library_sort VARCHAR(64) NULL,
    role ENUM('admin', 'user', 'pending') DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Create the AuditLogs table for admin actions
CREATE TABLE IF NOT EXISTS AuditLogs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    admin_id INT NOT NULL,
    action VARCHAR(64) NOT NULL,
    target_user_id INT NULL,
    details TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES Users(id) ON DELETE CASCADE,
    FOREIGN KEY (target_user_id) REFERENCES Users(id) ON DELETE SET NULL
);

-- Create the RecoveryCodes table
CREATE TABLE IF NOT EXISTS RecoveryCodes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    code VARCHAR(255) NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE
);

-- Add indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_users_username ON Users(username);
CREATE INDEX IF NOT EXISTS idx_recoverycodes_user_id ON RecoveryCodes(user_id);

-- Create the GameData table (game data from multiple sources)
CREATE TABLE IF NOT EXISTS GameData (
    appid VARCHAR(255) PRIMARY KEY, -- Prefixed game ID (e.g., hltb_12345 or steam_12345)
    name VARCHAR(255) NOT NULL,
    image_url VARCHAR(255),
    main_story FLOAT,
    main_extra FLOAT,
    completionist FLOAT,
    platforms VARCHAR(255),
    release_year INT,
    review_score INT, -- HLTB review score
    metacritic_score INT, -- Steam Metacritic score
    steam_categories TEXT, -- Comma-separated Steam categories
    steam_genres TEXT, -- Comma-separated Steam genres
    source VARCHAR(50) -- Source of the game data (e.g., 'HLTB', 'Steam', etc.)
);

-- Create the UserLibrary table (user-game relationship and user-specific fields)
CREATE TABLE IF NOT EXISTS UserLibrary (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    game_appid VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'shelved',
    notes TEXT,
    playtime INT, -- Playtime in minutes from Steam
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE,
    FOREIGN KEY (game_appid) REFERENCES GameData(appid) ON DELETE CASCADE,
    UNIQUE KEY unique_user_game (user_id, game_appid)
);

-- Add index for GameData source for efficient lookups by source
CREATE INDEX IF NOT EXISTS idx_gamedata_source ON GameData(source);
