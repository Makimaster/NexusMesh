-- NexusMesh PostgreSQL 初始化脚本
-- 此文件在容器首次启动时自动执行

-- 启用 pgcrypto 扩展（gen_random_uuid()）
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 通用 updated_at 自动更新触发器函数
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
