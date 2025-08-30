-- ===============================================================
--         分布式黑名单插件 - 数据库初始化脚本
-- ===============================================================
-- 目标:     此脚本用于在一个全新的 PostgreSQL 数据库中创建所有必需的
--           表和索引，以便插件能够正常工作。
--
-- 使用方法:
-- 1. 在 PostgreSQL 中创建一个新的、空的数据库 (例如: CREATE DATABASE distributed_blacklist;)。
-- 2. 连接到这个新创建的数据库。
-- 3. 执行此文件中的所有 SQL 语句。
-- ===============================================================


-- 步骤 1: 创建 `sync_log` 表
-- ---------------------------------------------------------------
-- 这是系统的核心审计日志表，记录每一次黑名单的变更操作。
-- 它是“追加式”的，并且是解决数据冲突的真相来源 (Source of Truth)。

CREATE TABLE IF NOT EXISTS sync_log (
    -- 自增ID，作为每条记录的唯一主键
    id SERIAL PRIMARY KEY,

    -- 操作类型，'INSERT' 代表添加, 'DELETE' 代表移除
    operation VARCHAR(10) NOT NULL,

    -- 被操作的用户QQ号
    user_id BIGINT NOT NULL,

    -- 执行操作的管理员QQ号
    operated_by BIGINT NOT NULL,
    
    -- 添加黑名单时的原因，移除时可为 NULL
    reason TEXT,

    -- 操作的权威时间戳。
    -- 由数据库在写入时自动生成，确保时间的统一性。
    operation_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
);

COMMENT ON TABLE sync_log IS '记录所有黑名单操作的审计日志，是数据同步的真相来源。';
COMMENT ON COLUMN sync_log.operation_time IS '由数据库生成的权威操作时间（UTC），用于冲突解决。';


-- 步骤 2: 创建 `blacklist` 表
-- ---------------------------------------------------------------
-- 这张表存储的是黑名单的“当前状态”，是 `sync_log` 中所有操作经过
-- 冲突解决后得到的最终结果。应用主要通过查询这张表来判断用户是否被拉黑。

CREATE TABLE IF NOT EXISTS blacklist (
    -- 被拉黑的用户QQ号，作为主键
    user_id BIGINT PRIMARY KEY,

    -- 将其添加到黑名单的管理员QQ号
    added_by BIGINT NOT NULL,

    -- 添加时的原因
    reason TEXT DEFAULT '',

    -- 记录创建时间
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
    
    -- 记录更新时间
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),

    -- (核心) 应用于此用户的最后一个操作的时间戳。
    -- 这个字段用于“最后写入者获胜”(Last-Write-Wins)的冲突检测。
    last_operation_time TIMESTAMP WITH TIME ZONE
);

COMMENT ON TABLE blacklist IS '存储当前黑名单的最终状态。';
COMMENT ON COLUMN blacklist.last_operation_time IS '对应 sync_log 中的权威时间，用于解决更新冲突。';


-- 步骤 3: 创建 `sync_state` 表
-- ---------------------------------------------------------------
-- 这张表用于跟踪每一个客户端（Bot实例）的数据同步进度。

CREATE TABLE IF NOT EXISTS sync_state (
    -- 客户端的唯一ID，通常是一个UUID
    client_id VARCHAR(64) PRIMARY KEY,

    -- 该客户端已经成功同步到的最后时间点
    last_sync_time TIMESTAMP WITH TIME ZONE NOT NULL,

    -- 本条状态记录的最后更新时间
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
);

COMMENT ON TABLE sync_state IS '跟踪每个客户端的增量同步进度。';


-- 步骤 4: 创建索引以优化查询性能
-- ---------------------------------------------------------------
-- 索引对于在高负载下保持数据库的快速响应至关重要。

-- 为 sync_log 的 operation_time 创建索引，极大地加速增量同步时的数据拉取。
CREATE INDEX IF NOT EXISTS idx_sync_log_operation_time ON sync_log(operation_time);

-- 为 sync_log 创建复合索引，便于未来可能实现的“查询某个用户的所有操作历史”功能。
CREATE INDEX IF NOT EXISTS idx_sync_log_user_operation ON sync_log(user_id, operation_time);

-- 为 blacklist 的 last_operation_time 创建索引，优化在更新或删除时的冲突检测查询。
CREATE INDEX IF NOT EXISTS idx_blacklist_last_operation_time ON blacklist(last_operation_time);


-- ===============================================================
--                 数据库初始化完成
-- ===============================================================
--