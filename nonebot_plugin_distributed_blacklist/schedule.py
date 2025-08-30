from nonebot import require
from nonebot.log import logger

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler
from . import config, database, api
from .kick_manager import check_and_kick_blacklist_members


async def sync_blacklist_from_database():
    """从数据库增量同步黑名单到本地缓存"""
    try:
        # 使用新的增量同步机制
        success = await database.incremental_sync()
        
        if success:
            # 重新构建缓存（从数据库获取当前状态）
            blacklist_data = await database.get_all_blacklist()
            if blacklist_data:
                api.rebuild_cache_from_database(blacklist_data)
                # 更新本地数据文件
                database.save_blacklist_to_local_data_file(blacklist_data)
                logger.success(f"黑名单增量同步完成，当前共 {len(blacklist_data)} 条记录")
            else:
                api.clear_cache()
                # 清空本地数据文件
                database.clear_local_data_file()
                logger.info("黑名单为空，已清空本地数据")
            
            # 同步完成后立即检查并踢出黑名单用户
            if config.config.distributed_blacklist_enable_auto_kick:
                logger.info("黑名单更新后自动检查群成员...")
                try:
                    await check_and_kick_blacklist_members()
                except Exception as kick_error:
                    logger.error(f"自动踢人过程中出现异常: {kick_error}")
        else:
            logger.warning("增量同步失败，将在下次定时任务中重试")
            
    except Exception as e:
        logger.error(f"同步黑名单失败: {e}")


async def force_full_sync():
    """强制执行全量同步（用于初始化或故障恢复）"""
    try:
        logger.info("开始执行全量同步...")
        
        # 获取所有历史操作
        all_operations = await database.get_operations_since(None)
        
        if all_operations:
            # 解决冲突并应用操作
            resolved_ops = database.resolve_conflicts(all_operations)
            success, failed_count = await database.apply_operations(resolved_ops)
            
            if success:
                # 更新同步时间
                from datetime import datetime, timezone
                await database.update_client_sync_time(datetime.now(timezone.utc))
                
                # 重建缓存
                blacklist_data = await database.get_all_blacklist()
                if blacklist_data:
                    api.rebuild_cache_from_database(blacklist_data)
                    # 更新本地数据文件
                    database.save_blacklist_to_local_data_file(blacklist_data)
                else:
                    api.clear_cache()
                    # 清空本地数据文件
                    database.clear_local_data_file()
                
                logger.success(f"全量同步完成：处理 {len(all_operations)} 个操作，应用 {len(resolved_ops)} 个最终操作")
                return True
        else:
            logger.info("没有找到任何操作记录")
            api.clear_cache()
            # 清空本地数据文件
            database.clear_local_data_file()
            return True
            
    except Exception as e:
        logger.error(f"全量同步失败: {e}")
        return False


# check_and_kick_blacklist_members 函数已移动到 kick_manager.py


async def initialize_scheduler():
    """初始化定时任务"""
    # 初始化数据库连接
    if await database.init_database():
        # 执行数据库结构升级（如果需要）
        await upgrade_database_schema()
        
        # 首先尝试从本地数据文件加载数据
        logger.info("初始化时加载本地数据...")
        local_data = database.get_local_blacklist_data()
        
        # 总是先加载本地数据到内存缓存
        if local_data:
            api.rebuild_cache_from_database(local_data)
            logger.success(f"本地数据加载完成，共 {len(local_data)} 条记录")
        else:
            api.clear_cache()
            logger.info("无本地数据，从空状态开始")
        
        # 执行增量同步以获取数据库中的最新更新
        logger.info("执行增量同步以获取最新数据...")
        if await database.incremental_sync():
            # 同步成功后获取完整数据并更新本地存储
            blacklist_data = await database.get_all_blacklist()
            if blacklist_data:
                api.rebuild_cache_from_database(blacklist_data)
                database.save_blacklist_to_local_data_file(blacklist_data)
                logger.success(f"增量同步完成，当前共 {len(blacklist_data)} 条记录")
            else:
                api.clear_cache()
                database.clear_local_data_file()
                logger.info("数据库中无黑名单数据，已清空本地数据")
        else:
            logger.warning("增量同步失败，继续使用本地数据")
        
        # 添加定时增量同步任务
        scheduler.add_job(
            sync_blacklist_from_database,
            "interval",
            seconds=config.config.distributed_blacklist_sync_interval,
            id="blacklist_sync",
            replace_existing=True
        )
        logger.success(f"黑名单增量同步任务已启动，间隔: {config.config.distributed_blacklist_sync_interval}秒")
        
        # 添加定时踢人任务
        if config.config.distributed_blacklist_enable_auto_kick:
            scheduler.add_job(
                check_and_kick_blacklist_members,
                "interval",
                seconds=config.config.distributed_blacklist_kick_check_interval,
                id="blacklist_kick_check",
                replace_existing=True
            )
            logger.success(f"自动踢人任务已启动，间隔: {config.config.distributed_blacklist_kick_check_interval}秒")
        else:
            logger.info("自动踢人功能已禁用")
    else:
        logger.error("数据库连接失败，定时任务未启动")


async def upgrade_database_schema():
    """升级数据库结构"""
    pool = await database.get_pool_with_retry()
    if not pool:
        logger.error("无法连接数据库，跳过结构升级")
        return
    
    try:
        async with pool.acquire() as conn:
            # 检查并添加 last_operation_time 列
            await conn.execute(
                "ALTER TABLE blacklist ADD COLUMN IF NOT EXISTS last_operation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            )
            
            # 检查并添加 operation_time 列和 reason 列
            await conn.execute(
                "ALTER TABLE sync_log ADD COLUMN IF NOT EXISTS operation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            )
            await conn.execute(
                "ALTER TABLE sync_log ADD COLUMN IF NOT EXISTS reason TEXT DEFAULT ''"
            )
            
            # 创建 sync_state 表
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_state (
                    client_id VARCHAR(64) PRIMARY KEY,
                    last_sync_time TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            
            # 创建索引
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sync_log_operation_time ON sync_log(operation_time)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sync_log_user_operation ON sync_log(user_id, operation_time)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_blacklist_last_operation_time ON blacklist(last_operation_time)"
            )
            
        logger.success("数据库结构升级完成")
    except Exception as e:
        logger.error(f"数据库结构升级失败: {e}")


# 在插件加载时初始化
scheduler.add_job(
    initialize_scheduler,
    "date",
    id="init_distributed_blacklist",
    replace_existing=True
)