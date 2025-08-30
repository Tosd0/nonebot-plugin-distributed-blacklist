import asyncio
import asyncpg
from typing import List, Optional, Tuple, Dict, NamedTuple
from nonebot.log import logger
from .config import config
import uuid
import asyncio
import random
from datetime import datetime, timezone
from pathlib import Path
from nonebot_plugin_localstore import get_plugin_data_file
import json

# 数据库连接池
_pool: Optional[asyncpg.Pool] = None

# 客户端ID（用于标识此实例）
_client_id: Optional[str] = None

def _get_client_id_file_path() -> Path:
    """获取客户端ID文件路径"""
    return get_plugin_data_file("blacklist_client_id.txt")

def _get_local_data_file_path() -> Path:
    """获取本地数据文件路径"""
    return get_plugin_data_file("blacklist_data.json")

def _load_or_generate_client_id() -> str:
    """加载或生成客户端ID"""
    client_id_file = _get_client_id_file_path()
    
    try:
        # 尝试从文件读取现有ID
        if client_id_file.exists():
            with open(client_id_file, 'r', encoding='utf-8') as f:
                client_id = f.read().strip()
                if client_id and len(client_id) > 0:
                    logger.info(f"从文件加载客户端ID: {client_id}")
                    return client_id
        
        # 生成新的客户端ID
        new_client_id = str(uuid.uuid4())
        
        # 保存到文件
        with open(client_id_file, 'w', encoding='utf-8') as f:
            f.write(new_client_id)
        
        logger.info(f"生成新的客户端ID并保存: {new_client_id}")
        return new_client_id
        
    except Exception as e:
        logger.error(f"加载或生成客户端ID失败: {e}")
        # 如果文件操作失败，返回一个临时ID（这种情况下会退回到原有行为）
        fallback_id = str(uuid.uuid4())
        logger.warning(f"使用临时客户端ID: {fallback_id}")
        return fallback_id

def get_client_id() -> str:
    """获取客户端ID，确保单例"""
    global _client_id
    if _client_id is None:
        _client_id = _load_or_generate_client_id()
    return _client_id

# 操作记录类型
class Operation(NamedTuple):
    user_id: int
    operation: str  # 'INSERT' or 'DELETE'
    operated_by: int
    operation_time: datetime
    reason: str = ""


async def init_database():
    """初始化数据库连接池"""
    global _pool
    try:
        _pool = await asyncpg.create_pool(
            host=config.distributed_blacklist_db_host,
            port=config.distributed_blacklist_db_port,
            user=config.distributed_blacklist_db_user,
            password=config.distributed_blacklist_db_password,
            database=config.distributed_blacklist_db_name,
            min_size=config.distributed_blacklist_db_min_connections,
            max_size=config.distributed_blacklist_db_max_connections,
        )
        logger.success("数据库连接池初始化成功")
        return True
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        return False


async def close_database():
    """关闭数据库连接池"""
    global _pool
    if _pool:
        await _pool.close()
        logger.info("数据库连接池已关闭")


async def get_pool_with_retry(max_retries: int = 3, base_delay: float = 1.0) -> Optional[asyncpg.Pool]:
    """带重试机制的数据库连接池获取"""
    global _pool
    
    for attempt in range(max_retries + 1):
        try:
            if _pool is None:
                if not await init_database():
                    raise Exception("数据库初始化失败")
            
            # 检查连接池健康状态
            if _pool and not _pool._closed:
                try:
                    # 尝试从池中获取一个连接并执行简单查询
                    async with _pool.acquire() as conn:
                        await conn.fetchval('SELECT 1')
                    return _pool
                except Exception as health_check_error:
                    logger.warning(f"数据库连接池健康检查失败: {health_check_error}")
                    # 关闭现有连接池，强制重新创建
                    try:
                        await _pool.close()
                    except:
                        pass
                    _pool = None
            
            # 重新创建连接池
            if not await init_database():
                raise Exception("数据库重新初始化失败")
            
            return _pool
            
        except Exception as e:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"获取数据库连接失败（第{attempt + 1}次尝试）: {e}，{delay:.1f}秒后重试")
                await asyncio.sleep(delay)
            else:
                logger.error(f"获取数据库连接池失败，已重试{max_retries}次: {e}")
                return None
    
    return None

async def get_pool() -> Optional[asyncpg.Pool]:
    """获取数据库连接池（保持向下兼容）"""
    return await get_pool_with_retry()


async def add_blacklist_user(user_id: int, added_by: int, reason: str = "") -> bool:
    """添加用户到黑名单，使用数据库权威时间戳"""
    pool = await get_pool_with_retry()
    if not pool:
        return False
    
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. 插入日志（包含reason），并立即用 RETURNING 取回数据库生成的权威时间戳
                row = await conn.fetchrow(
                    """
                    INSERT INTO sync_log (operation, user_id, operated_by, reason)
                    VALUES ('INSERT', $1, $2, $3)
                    RETURNING operation_time
                    """,
                    user_id, added_by, reason
                )
                
                # 直接使用从数据库返回的、带时区的权威时间
                authoritative_time = row['operation_time']
                
                # 2. 使用这个权威时间去更新状态
                await conn.execute(
                    """
                    INSERT INTO blacklist (user_id, added_by, reason, created_at, last_operation_time)
                    VALUES ($1, $2, $3, $4, $4)
                    ON CONFLICT (user_id) DO UPDATE SET
                        added_by = EXCLUDED.added_by,
                        reason = EXCLUDED.reason,
                        updated_at = CURRENT_TIMESTAMP,
                        last_operation_time = EXCLUDED.last_operation_time
                    WHERE EXCLUDED.last_operation_time > blacklist.last_operation_time
                    """,
                    user_id, added_by, reason, authoritative_time
                )
            
        if config.distributed_blacklist_debug_mode:
            # 转换为 UTC+8 显示
            from datetime import timedelta
            if authoritative_time.tzinfo is None:
                utc_time = authoritative_time.replace(tzinfo=timezone.utc)
            else:
                utc_time = authoritative_time
            shanghai_time = utc_time.astimezone(timezone(timedelta(hours=8)))
            formatted_time = shanghai_time.strftime("%Y-%m-%d %H:%M:%S")
            logger.debug(f"用户 {user_id} 已添加到黑名单，操作者: {added_by}，权威时间: {formatted_time}")
        
        # 更新本地数据文件
        try:
            from . import api
            blacklist_data = await get_all_blacklist()
            if blacklist_data:
                api.rebuild_cache_from_database(blacklist_data)
                save_blacklist_to_local_data_file(blacklist_data)
            else:
                api.clear_cache()
                clear_local_data_file()
        except Exception as e:
            logger.warning(f"更新本地数据文件失败: {e}")
        
        return True
    except Exception as e:
        logger.error(f"添加黑名单用户失败: {e}")
        return False

async def remove_blacklist_user(user_id: int, operated_by: int) -> bool:
    """从黑名单移除用户，使用数据库权威时间戳"""
    pool = await get_pool_with_retry()
    if not pool:
        return False
    
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. 插入删除日志，取回权威时间戳
                row = await conn.fetchrow(
                    """
                    INSERT INTO sync_log (operation, user_id, operated_by)
                    VALUES ('DELETE', $1, $2)
                    RETURNING operation_time
                    """,
                    user_id, operated_by
                )
                
                # 直接使用从数据库返回的、带时区的权威时间
                authoritative_time = row['operation_time']

                # 2. 使用这个权威时间去删除状态
                await conn.execute(
                    """DELETE FROM blacklist 
                       WHERE user_id = $1 
                       AND (last_operation_time IS NULL OR last_operation_time <= $2)""",
                    user_id, authoritative_time
                )
                
            if config.distributed_blacklist_debug_mode:
                # 转换为 UTC+8 显示
                from datetime import timedelta
                if authoritative_time.tzinfo is None:
                    utc_time = authoritative_time.replace(tzinfo=timezone.utc)
                else:
                    utc_time = authoritative_time
                shanghai_time = utc_time.astimezone(timezone(timedelta(hours=8)))
                formatted_time = shanghai_time.strftime("%Y-%m-%d %H:%M:%S")
                logger.debug(f"用户 {user_id} 已从黑名单移除，操作者: {operated_by}，权威时间: {formatted_time}")
            
            # 更新本地数据文件
            try:
                from . import api
                blacklist_data = await get_all_blacklist()
                if blacklist_data:
                    api.rebuild_cache_from_database(blacklist_data)
                    save_blacklist_to_local_data_file(blacklist_data)
                else:
                    api.clear_cache()
                    clear_local_data_file()
            except Exception as e:
                logger.warning(f"更新本地数据文件失败: {e}")
            
            return True
    except Exception as e:
        logger.error(f"移除黑名单用户失败: {e}")
        return False

async def get_all_blacklist() -> List[Tuple[int, int, str, int]]:
    """获取所有黑名单用户"""
    pool = await get_pool_with_retry()
    if not pool:
        return []
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, added_by, reason, 
                       EXTRACT(EPOCH FROM created_at)::int as timestamp
                FROM blacklist
                ORDER BY created_at DESC
                """
            )
            
        return [(row['user_id'], row['timestamp'], row['added_by'], row['reason']) for row in rows]
    except Exception as e:
        logger.error(f"获取黑名单失败: {e}")
        return []


async def get_data_version() -> int:
    """获取数据版本号"""
    pool = await get_pool_with_retry()
    if not pool:
        return 0
    
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT version FROM data_version WHERE id = 1")
            return row['version'] if row else 0
    except Exception as e:
        logger.error(f"获取数据版本失败: {e}")
        return 0


async def check_user_in_blacklist(user_id: int) -> bool:
    """检查用户是否在黑名单中"""
    pool = await get_pool_with_retry()
    if not pool:
        return False
    
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM blacklist WHERE user_id = $1",
                user_id
            )
            return row is not None
    except Exception as e:
        logger.error(f"检查用户黑名单状态失败: {e}")
        return False


async def get_client_last_sync_time() -> Optional[datetime]:
    """获取客户端最后同步时间"""
    pool = await get_pool_with_retry()
    if not pool:
        return None
    
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT last_sync_time FROM sync_state WHERE client_id = $1",
                get_client_id()
            )
            return row['last_sync_time'] if row else None
    except Exception as e:
        logger.error(f"获取客户端同步时间失败: {e}")
        return None


async def update_client_sync_time(sync_time: datetime) -> bool:
    """更新客户端同步时间"""
    pool = await get_pool_with_retry()
    if not pool:
        return False
    
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sync_state (client_id, last_sync_time)
                VALUES ($1, $2)
                ON CONFLICT (client_id) DO UPDATE SET
                    last_sync_time = EXCLUDED.last_sync_time,
                    updated_at = CURRENT_TIMESTAMP
                """,
                get_client_id(), sync_time
            )
            return True
    except Exception as e:
        logger.error(f"更新客户端同步时间失败: {e}")
        return False


async def get_operations_since(since_time: Optional[datetime] = None) -> List[Operation]:
    """获取指定时间后的所有操作"""
    pool = await get_pool_with_retry()
    if not pool:
        return []
    
    try:
        async with pool.acquire() as conn:
            # 确保时间参数带时区信息
            query_time = None
            if since_time is not None:
                if since_time.tzinfo is None:
                    # 如果没有时区信息，假设是UTC时间
                    query_time = since_time.replace(tzinfo=timezone.utc)
                else:
                    query_time = since_time
            
            # 查询语句现在直接从 sync_log 获取 reason，更简单可靠
            query = """
                SELECT user_id, operation, operated_by, operation_time, 
                       COALESCE(reason, '') as reason
                FROM sync_log
                WHERE ($1::timestamptz IS NULL OR operation_time > $1)
                ORDER BY operation_time ASC
            """
            rows = await conn.fetch(query, query_time)
            
            return [
                Operation(
                    user_id=row['user_id'],
                    operation=row['operation'],
                    operated_by=row['operated_by'],
                    operation_time=row['operation_time'],
                    reason=row['reason'] or ""
                )
                for row in rows
            ]
    except Exception as e:
        logger.error(f"获取操作记录失败: {e}")
        return []


def resolve_conflicts(operations: List[Operation]) -> Dict[int, Operation]:
    """解决冲突，每个用户应用时间最新的操作"""
    user_latest_ops: Dict[int, Operation] = {}
    
    # 按用户ID分组，每个用户保留最新的操作
    for op in operations:
        user_id = op.user_id
        if user_id not in user_latest_ops or op.operation_time > user_latest_ops[user_id].operation_time:
            user_latest_ops[user_id] = op
    
    if config.distributed_blacklist_debug_mode:
        logger.debug(f"冲突解决结果: 处理了 {len(operations)} 个操作，得到 {len(user_latest_ops)} 个最终操作")
    
    return user_latest_ops


async def apply_operations(operations: Dict[int, Operation]) -> Tuple[bool, int]:
    """应用操作到本地数据库，返回(success, failed_count)"""
    pool = await get_pool_with_retry()
    if not pool:
        return False, len(operations)
    
    failed_operations = 0
    successful_operations = 0
    
    try:
        async with pool.acquire() as conn:
            # 不使用大事务，避免一个操作失败导致整个批次回滚
            for user_id, op in operations.items():
                try:
                    async with conn.transaction():
                        # 从传入的 Operation 对象中获取已经存在的权威时间
                        authoritative_time = op.operation_time

                        if op.operation == 'INSERT':
                            # 直接更新 blacklist 状态表，不再调用会写日志的 internal 函数
                            await conn.execute(
                                """
                                INSERT INTO blacklist (user_id, added_by, reason, created_at, last_operation_time)
                                VALUES ($1, $2, $3, $4, $4)
                                ON CONFLICT (user_id) DO UPDATE SET
                                    added_by = EXCLUDED.added_by,
                                    reason = EXCLUDED.reason,
                                    updated_at = (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                                    last_operation_time = EXCLUDED.last_operation_time
                                WHERE EXCLUDED.last_operation_time > blacklist.last_operation_time
                                """,
                                op.user_id, op.operated_by, op.reason, authoritative_time
                            )
                        elif op.operation == 'DELETE':
                            # 直接操作 blacklist 状态表
                            await conn.execute(
                                """DELETE FROM blacklist 
                                   WHERE user_id = $1 
                                   AND (last_operation_time IS NULL OR last_operation_time <= $2)""",
                                op.user_id, authoritative_time
                            )
                        else:
                            logger.warning(f"未知操作类型: {op.operation}，跳过用户 {user_id}")
                            failed_operations += 1
                            continue
                        
                        successful_operations += 1
                        
                except Exception as op_error:
                    failed_operations += 1
                    logger.error(f"应用用户 {user_id} 的操作失败: {op_error}，跳过并继续其他操作")
        
        if config.distributed_blacklist_debug_mode:
            logger.debug(f"应用操作结果: 成功 {successful_operations} 个，失败 {failed_operations} 个")
        
        # 只要有一个操作成功，就认为整体成功
        return successful_operations > 0, failed_operations
        
    except Exception as e:
        logger.error(f"应用操作整体失败: {e}")
        return False, len(operations)


async def incremental_sync() -> bool:
    """执行增量同步，具有更强的错误处理能力"""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # 1. 获取上次同步时间
            last_sync_time = await get_client_last_sync_time()
            current_time = datetime.now(timezone.utc)
            
            # 2. 获取增量操作
            operations = await get_operations_since(last_sync_time)
            
            if not operations:
                if config.distributed_blacklist_debug_mode:
                    logger.debug("无新增操作，跳过同步")
                await update_client_sync_time(current_time)
                return True
            
            # 3. 解决冲突
            resolved_ops = resolve_conflicts(operations)
            
            # 4. 应用操作（支持部分失败）
            success, failed_count = await apply_operations(resolved_ops)
            
            if success:
                # 即使有部分失败，也更新同步时间，避免被卡住
                await update_client_sync_time(current_time)
                
                if failed_count > 0:
                    logger.warning(f"增量同步部分失败：处理 {len(operations)} 个操作，应用 {len(resolved_ops)} 个最终操作，{failed_count} 个失败")
                else:
                    logger.success(f"增量同步完成：处理 {len(operations)} 个操作，应用 {len(resolved_ops)} 个最终操作")
                
                return True
            else:
                # 所有操作都失败，重试
                retry_count += 1
                if retry_count < max_retries:
                    logger.warning(f"所有操作应用失败，{retry_count}/{max_retries} 次重试，5秒后再试")
                    await asyncio.sleep(5)
                    continue
                else:
                    logger.error(f"增量同步失败：所有操作应用失败，已重试 {max_retries} 次")
                    return False
                
        except Exception as e:
            retry_count += 1
            if retry_count < max_retries:
                logger.warning(f"增量同步出现异常：{e}，{retry_count}/{max_retries} 次重试，5秒后再试")
                await asyncio.sleep(5)
                continue
            else:
                logger.error(f"增量同步失败：{e}，已重试 {max_retries} 次")
                return False
    
    return False


async def get_user_operation_history(user_id: int, limit: int = 3) -> List[Tuple[str, str, str, str]]:
    """获取用户的最近操作记录
    
    Args:
        user_id: 用户ID
        limit: 返回记录数量，默认3条
    
    Returns:
        List[Tuple[str, str, str, str]]: [(时间, 操作人, 操作, 原因), ...]
    """
    pool = await get_pool_with_retry()
    if not pool:
        return []
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT operation_time, operated_by, operation, 
                       COALESCE(reason, '') as reason
                FROM sync_log
                WHERE user_id = $1
                ORDER BY operation_time DESC
                LIMIT $2
                """,
                user_id, limit
            )
            
            result = []
            for row in rows:
                # 格式化时间 - 转换为 UTC+8 (Asia/Shanghai) 时区显示
                from datetime import timedelta
                utc_time = row['operation_time']
                if utc_time.tzinfo is None:
                    utc_time = utc_time.replace(tzinfo=timezone.utc)
                shanghai_time = utc_time.astimezone(timezone(timedelta(hours=8)))
                formatted_time = shanghai_time.strftime("%Y-%m-%d %H:%M:%S")
                
                # 格式化操作
                operation_text = "添加黑名单" if row['operation'] == 'INSERT' else "移除黑名单"
                
                # 操作人
                operator = str(row['operated_by'])
                
                # 原因
                reason = row['reason'] if row['reason'] else ""
                
                result.append((formatted_time, operator, operation_text, reason))
            
            return result
    except Exception as e:
        logger.error(f"获取用户操作历史失败: {e}")
        return []


def save_blacklist_to_local_data_file(blacklist_data: List[Tuple[int, int, str, int]]) -> bool:
    """将黑名单数据保存到本地数据文件"""
    try:
        data_file = _get_local_data_file_path()
        
        # 创建目录（如果不存在）
        data_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 将数据转换为可序列化的格式
        serializable_data = {
            "version": 1,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "data": [
                {
                    "user_id": item[0],
                    "timestamp": item[1], 
                    "added_by": item[2],
                    "reason": item[3]
                }
                for item in blacklist_data
            ]
        }
        
        # 写入文件
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(serializable_data, f, ensure_ascii=False, indent=2)
        
        if config.distributed_blacklist_debug_mode:
            logger.debug(f"黑名单数据已保存到本地数据文件: {data_file}，共 {len(blacklist_data)} 条记录")
        
        return True
    except Exception as e:
        logger.error(f"保存黑名单到本地数据文件失败: {e}")
        return False


def load_blacklist_from_local_data_file() -> Optional[List[Tuple[int, int, str, int]]]:
    """从本地数据文件加载黑名单数据"""
    try:
        data_file = _get_local_data_file_path()
        
        if not data_file.exists():
            logger.info("本地数据文件不存在")
            return None
        
        with open(data_file, 'r', encoding='utf-8') as f:
            file_data = json.load(f)
        
        # 检查文件格式版本
        if file_data.get("version") != 1:
            logger.warning("本地数据文件版本不匹配，忽略数据")
            return None
        
        # 转换回原始格式
        blacklist_data = []
        for item in file_data.get("data", []):
            blacklist_data.append((
                item["user_id"],
                item["timestamp"], 
                item["added_by"],
                item["reason"]
            ))
        
        logger.info(f"从本地数据文件加载黑名单数据: {len(blacklist_data)} 条记录，更新时间: {file_data.get('last_updated', 'unknown')}")
        return blacklist_data
        
    except Exception as e:
        logger.error(f"从本地数据文件加载黑名单数据失败: {e}")
        return None


def clear_local_data_file() -> bool:
    """清空本地数据文件"""
    try:
        data_file = _get_local_data_file_path()
        if data_file.exists():
            data_file.unlink()
            logger.info("本地数据文件已清空")
        return True
    except Exception as e:
        logger.error(f"清空本地数据文件失败: {e}")
        return False


def get_local_blacklist_data() -> List[Tuple[int, int, str, int]]:
    """获取本地黑名单数据，如果本地没有数据则返回空列表"""
    local_data = load_blacklist_from_local_data_file()
    return local_data if local_data is not None else []


