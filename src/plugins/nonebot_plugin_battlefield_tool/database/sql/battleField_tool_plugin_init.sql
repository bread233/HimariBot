CREATE TABLE IF NOT EXISTS battleField_user_binds
(
    qq_id VARCHAR(32) PRIMARY KEY,
    ea_name TEXT NOT NULL,
    ea_id  TEXT NOT NULL
);

create TABLE IF NOT EXISTS battleField_session_tags
(
    session_channel_id VARCHAR(32) PRIMARY KEY,
    default_game_tag TEXT NOT NULL
)