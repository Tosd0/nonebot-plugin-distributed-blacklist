from .config import Config
from nonebot.plugin import PluginMetadata
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.message import event_preprocessor
from nonebot.permission import SUPERUSER
from nonebot.exception import IgnoredException
from nonebot.log import logger
from nonebot.permission import Permission
import time
from . import api, core, database, config, schedule

# 创建自定义权限
def create_blacklist_admin_permission():
    """创建黑名单管理员权限"""
    try:
        admin_users = set()
        if config.config.distributed_blacklist_admins:
            for admin in config.config.distributed_blacklist_admins:
                if isinstance(admin, str):
                    admin_users.add(int(admin))
                elif isinstance(admin, int):
                    admin_users.add(admin)
        logger.info(f"黑名单管理员: {admin_users}")
    except Exception as e:
        logger.error(f"解析黑名单管理员配置失败: {e}")
        admin_users = set()
    
    async def _blacklist_admin(event) -> bool:
        user_id = int(event.get_user_id())  # 转换为int进行比较
        is_admin = user_id in admin_users
        if config.config.distributed_blacklist_debug_mode:
            logger.debug(f"权限检查: 用户{user_id}, 是否管理员: {is_admin}")
        return is_admin
    
    return Permission(_blacklist_admin)

BLACKLIST_ADMINS = create_blacklist_admin_permission()

__plugin_meta__ = PluginMetadata(
    name="分布式黑名单插件",
    description="基于PostgreSQL的分布式黑名单系统，支持多节点同步",
    usage="高效率分布式黑名单管理，支持实时同步",
    type="application",
    config=Config,
    homepage="https://github.com/Tosd0/nonebot-plugin-distributed-blacklist",
    supported_adapters={"~onebot.v11"}
)

# 初始化核心黑名单系统
core_list = api.core_list

# 注册命令
add_black = on_command("添加黑名单", aliases={"加黑", "上黑", "加黑名单"}, permission=BLACKLIST_ADMINS | SUPERUSER)
search_black = on_command("搜索黑名单", aliases={"查黑", "查询黑名单", "查找黑名单"}, permission=BLACKLIST_ADMINS | SUPERUSER)
del_black = on_command("删除黑名单", aliases={"删黑", "下黑", "删黑名单"}, permission=BLACKLIST_ADMINS | SUPERUSER)
sync_black = on_command("同步黑名单", permission=BLACKLIST_ADMINS | SUPERUSER)


# 全局黑名单检测
if config.config.distributed_blacklist_check_global:
    logger.success("全局检测黑名单开启成功！")

    @event_preprocessor
    async def _(event: GroupMessageEvent):
        v: bool = api.search(event.get_user_id())[0]
        if not v:
            pass
        else:
            raise IgnoredException(f"检测到:{event.get_user_id()}属于黑名单")
else:
    logger.warning("全局检测黑名单未开启,开启方法见文档")


@add_black.handle()
async def _(event: GroupMessageEvent, args_msg: Message = CommandArg()):
    args = str(args_msg).strip().split(maxsplit=1)
    
    # 检查是否提供了参数
    if not args or not args[0]:
        await add_black.finish("请提供要添加的QQ号\n使用格式: 添加黑名单 <QQ号> [原因]")
    
    try:
        # 尝试从消息中提取@的用户
        user_id = args_msg[0].data["qq"]
    except (IndexError, KeyError, TypeError):
        # 如果没有@用户，使用第一个参数作为QQ号
        user_id = args[0]
    
    # 验证QQ号格式
    try:
        int(user_id)  # 检查是否为数字
    except ValueError:
        await add_black.finish("QQ号格式错误，请提供有效的数字QQ号")
    
    reason = "" if len(args) == 1 else args[1]
    
    # 检查用户是否已存在
    if core_list.search(user_id)[0]:
        await add_black.finish(f"⚠️ 用户 {user_id} 已经在黑名单中，无需重复添加")
    
    # 添加到数据库
    try:
        success = await database.add_blacklist_user(
            user_id=int(user_id),
            added_by=int(event.get_user_id()),
            reason=reason
        )
    except Exception as e:
        logger.error(f"添加黑名单失败: {e}")
        await add_black.finish("添加失败，数据库操作异常")
    
    if success:
        # 添加到本地缓存
        timestamp = int(time.time())
        core_list.add(
            user_id,
            timestamp,
            reason,
            int(event.get_user_id())
        )
        
        core.add_count += 1
        
        # 先发送成功反馈
        success_msg = f"✅ 已成功将用户 {user_id} 添加到黑名单\n原因: {reason if reason else '无'}"
        
        # 如果启用自动踢人，在反馈后执行
        if config.config.distributed_blacklist_enable_auto_kick:
            await add_black.send(success_msg)
            try:
                from .kick_manager import kick_specific_user
                logger.info(f"新增黑名单用户 {user_id} 后自动踢出...")
                await kick_specific_user(user_id, reason)
                await add_black.send("🔄 已完成自动踢人检查")
            except Exception as e:
                logger.warning(f"自动踢人失败: {e}")
                await add_black.send("⚠️ 自动踢人功能执行异常")
        else:
            await add_black.finish(success_msg)
    else:
        await add_black.finish("❌ 添加失败，请检查数据库连接")


@search_black.handle()
async def _(args_msg: Message = CommandArg()):
    search_input = str(args_msg).strip()
    
    # 检查是否提供了参数
    if not search_input:
        await search_black.finish("请提供要搜索的QQ号\n使用格式: 搜索黑名单 <QQ号>")
    
    user_lines = search_input.split("\r\n")
    for user_id_line in user_lines:
        user_id_line = user_id_line.strip()
        if not user_id_line:
            continue
            
        # 验证QQ号格式
        try:
            int(user_id_line)  # 检查是否为数字
        except ValueError:
            await search_black.send(f"QQ号格式错误: {user_id_line}")
            continue
            
        core.sum_black += 1
        result = core_list.search(user_id_line)
        
        # 获取操作历史记录（无论用户是否在黑名单中都要获取）
        try:
            operation_history = await database.get_user_operation_history(int(user_id_line))
        except Exception as e:
            logger.error(f"获取操作历史失败: {e}")
            operation_history = []
        
        if result[0]:
            # 用户在黑名单中
            from datetime import datetime, timezone, timedelta
            # 转换为 UTC+8 (Asia/Shanghai) 时区显示
            utc_time = datetime.utcfromtimestamp(result[1]).replace(tzinfo=timezone.utc)
            shanghai_time = utc_time.astimezone(timezone(timedelta(hours=8)))
            formatted_time = shanghai_time.strftime("%Y-%m-%d %H:%M:%S")
            
            # 构建基本信息
            message_parts = [
                f"🔍 {user_id_line} 查询结果：",
                f"❌ 此人属于黑名单",
                f"⏰ 添加时间: {formatted_time}",
                f"👤 操作人: {result[2]}",
                f"📝 原因: {result[3] if result[3] else '无'}"
            ]
        else:
            # 用户不在黑名单中
            message_parts = [
                f"🔍 {user_id_line} 查询结果：",
                f"✅ 此人不属于黑名单"
            ]
        
        # 添加操作历史（无论是否在黑名单中都显示）
        if operation_history:
            message_parts.append("\n📋 最近操作记录:")
            for i, (op_time, operator, operation, reason) in enumerate(operation_history, 1):
                if reason:
                    history_line = f"{i}. {op_time} {operator} {operation} ({reason})"
                else:
                    history_line = f"{i}. {op_time} {operator} {operation}"
                message_parts.append(history_line)
        else:
            # 如果没有操作历史，说明这个用户从未被操作过
            if not result[0]:  # 只有在不在黑名单的情况下才显示此消息
                message_parts.append("📋 无操作记录")
        
        await search_black.send("\n".join(message_parts))
    await search_black.finish()


@del_black.handle()
async def _(event: GroupMessageEvent, args_msg: Message = CommandArg()):
    delete_input = str(args_msg).strip()
    
    # 检查是否提供了参数
    if not delete_input:
        await del_black.finish("请提供要删除的QQ号\n使用格式: 删除黑名单 <QQ号>")
    
    try:
        # 尝试从消息中提取@的用户
        user_id = args_msg[0].data["qq"]
    except (IndexError, KeyError, TypeError):
        # 如果没有@用户，使用参数作为QQ号
        user_id = delete_input.split()[0] if delete_input else ""
    
    # 验证QQ号格式
    if not user_id:
        await del_black.finish("请提供要删除的QQ号")
        
    try:
        int(user_id)  # 检查是否为数字
    except ValueError:
        await del_black.finish("QQ号格式错误，请提供有效的数字QQ号")
    
    core.del_count += 1
    
    # 检查用户是否存在
    if not core_list.search(user_id)[0]:
        await del_black.finish(f"⚠️ 用户 {user_id} 不在黑名单中，无需删除")
    
    # 从数据库删除
    try:
        success = await database.remove_blacklist_user(
            user_id=int(user_id),
            operated_by=int(event.get_user_id())
        )
    except Exception as e:
        logger.error(f"删除黑名单失败: {e}")
        await del_black.finish("删除失败，数据库操作异常")
    
    if success:
        # 从本地缓存删除
        core_list.del_black(user_id)
        await del_black.finish(f"✅ 已成功将用户 {user_id} 从黑名单中移除")
    else:
        await del_black.finish("❌ 删除失败，请检查数据库连接")


@sync_black.handle()
async def _():
    """手动触发黑名单同步"""
    await sync_black.send("🔄 开始同步黑名单数据...")
    
    try:
        # 调用同步函数
        from .schedule import sync_blacklist_from_database
        await sync_blacklist_from_database()
        await sync_black.finish("✅ 黑名单同步完成！")
    except Exception as e:
        logger.error(f"手动同步黑名单失败: {e}")
        await sync_black.finish("❌ 同步失败，请检查数据库连接和配置")