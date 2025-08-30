"""
踢人管理模块
处理黑名单用户的踢出逻辑
"""
from nonebot import get_bot, get_driver
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger
from . import api, config
from typing import Dict, Set
import time

# 权限缓存：{bot_id: {"groups": set(group_ids), "last_check": timestamp}}
_admin_groups_cache: Dict[str, Dict] = {}
# 缓存有效期（秒）
CACHE_EXPIRE_TIME = 3600  # 1小时


async def get_admin_groups(bot: Bot) -> Set[int]:
    """获取机器人有管理权限的群列表（带缓存）"""
    bot_id = bot.self_id
    current_time = time.time()
    
    # 检查缓存是否有效
    if (bot_id in _admin_groups_cache and 
        current_time - _admin_groups_cache[bot_id]["last_check"] < CACHE_EXPIRE_TIME):
        logger.debug(f"使用权限缓存，机器人 {bot_id} 有管理权限的群: {len(_admin_groups_cache[bot_id]['groups'])} 个")
        return _admin_groups_cache[bot_id]["groups"]
    
    # 缓存过期或不存在，重新检查权限
    logger.info(f"检查机器人 {bot_id} 的群管理权限...")
    admin_groups = set()
    
    try:
        # 获取机器人加入的所有群
        group_list = await bot.get_group_list()
        
        for group_info in group_list:
            group_id = group_info["group_id"]
            
            try:
                # 检查机器人在该群的权限
                bot_self_info = await bot.get_group_member_info(
                    group_id=group_id, 
                    user_id=int(bot_id),
                    no_cache=True
                )
                bot_role = bot_self_info.get("role", "member")
                
                # 只记录有管理权限的群
                if bot_role in ["admin", "owner"]:
                    admin_groups.add(group_id)
                    logger.debug(f"群 {group_id}: 机器人权限为 {bot_role}")
                else:
                    logger.debug(f"群 {group_id}: 机器人权限不足({bot_role})，跳过")
                    
            except Exception as e:
                logger.warning(f"检查群 {group_id} 权限失败: {e}")
        
        # 更新缓存
        _admin_groups_cache[bot_id] = {
            "groups": admin_groups,
            "last_check": current_time
        }
        
        logger.success(f"权限检查完成，机器人 {bot_id} 在 {len(admin_groups)} 个群中有管理权限")
        
    except Exception as e:
        logger.error(f"获取群列表失败: {e}")
        # 如果获取失败，返回空集合
        admin_groups = set()
    
    return admin_groups


async def send_report_to_superusers(kicked_users: Dict[str, Dict]):
    """向SUPERUSERS发送报备消息"""
    if not kicked_users:
        return
        
    try:
        bot = get_bot()
        if not isinstance(bot, Bot):
            return
            
        # 获取SUPERUSERS配置
        driver = get_driver()
        superusers = driver.config.superusers or set()
        
        if not superusers:
            logger.debug("未配置SUPERUSERS，跳过报备")
            return
        
        # 构建报备消息
        total_users = len(kicked_users)
        report_msg = f"云黑检测到机器人所在的群内有 {total_users} 个人上黑了。\n\n"
        
        for user_id, info in kicked_users.items():
            group_names = []
            for group_id in info["groups"]:
                try:
                    group_info = await bot.get_group_info(group_id=group_id)
                    group_names.append(group_info["group_name"])
                except:
                    group_names.append(f"群{group_id}")
            
            group_count = len(group_names)
            group_list = "、".join(group_names)
            
            report_msg += f"【{user_id}】\n上黑理由：{info['reason']}\n所在的{group_count}个群：\n{group_list}\n\n"
        
        report_msg += "以上人员已踢出。（受缓存影响，部分所在群可能显示不准确，请以实际为准）"
        
        # 发送给每个SUPERUSER
        for superuser in superusers:
            try:
                await bot.send_private_msg(user_id=int(superuser), message=report_msg)
                logger.info(f"已向SUPERUSER {superuser} 发送踢人报备")
            except Exception as e:
                logger.warning(f"向SUPERUSER {superuser} 发送报备失败: {e}")
                
    except Exception as e:
        logger.error(f"发送报备消息失败: {e}")


async def check_and_kick_blacklist_members():
    """检查群成员并踢出黑名单用户"""
    if not config.config.distributed_blacklist_enable_auto_kick:
        logger.debug("自动踢人功能已禁用")
        return
    
    try:
        bot = get_bot()
        if not isinstance(bot, Bot):
            logger.warning("当前Bot不支持OneBot v11协议")
            return
        
        # 获取有管理权限的群列表（使用缓存）
        admin_groups = await get_admin_groups(bot)
        
        if not admin_groups:
            logger.warning("机器人没有任何群的管理权限，跳过踢人检查")
            return
        
        kicked_count = 0
        checked_groups = 0
        kicked_users = {}  # 用于收集被踢用户信息
        
        for group_id in admin_groups:
            try:
                # 获取群成员列表
                member_list = await bot.get_group_member_list(group_id=group_id)
                
                for member in member_list:
                    user_id = str(member["user_id"])
                    
                    # 检查是否在黑名单中
                    if api.is_user_in_cache(user_id):
                        try:
                            # 踢出群聊
                            await bot.set_group_kick(
                                group_id=group_id,
                                user_id=int(user_id),
                                reject_add_request=True
                            )
                            
                            user_info = api.get_user_info_from_cache(user_id)
                            logger.success(
                                f"已将黑名单用户 {user_id} 踢出群 {group_id}, "
                                f"原因: {user_info.get('reason', '无')}"
                            )
                            kicked_count += 1
                            
                            # 收集被踢用户信息用于报备
                            if user_id not in kicked_users:
                                kicked_users[user_id] = {
                                    "reason": user_info.get('reason', '无'),
                                    "groups": []
                                }
                            kicked_users[user_id]["groups"].append(group_id)
                            
                        except Exception as kick_error:
                            logger.warning(f"踢出用户 {user_id} 失败: {kick_error}")
                
                checked_groups += 1
                
            except Exception as group_error:
                logger.warning(f"处理群 {group_id} 时出错: {group_error}")
        
        # 发送报备消息
        if kicked_users:
            await send_report_to_superusers(kicked_users)
        
        if kicked_count > 0:
            logger.success(f"黑名单检查完成，检查了 {checked_groups} 个群，踢出 {kicked_count} 个用户")
        elif config.config.distributed_blacklist_debug_mode:
            logger.debug(f"黑名单检查完成，检查了 {checked_groups} 个群，无需踢出用户")
            
    except Exception as e:
        logger.error(f"自动踢出黑名单用户失败: {e}")


async def kick_specific_user(user_id: str, reason: str = ""):
    """踢出特定用户（刚添加到黑名单的用户）"""
    if not config.config.distributed_blacklist_enable_auto_kick:
        return
    
    try:
        bot = get_bot()
        if not isinstance(bot, Bot):
            return
        
        # 获取有管理权限的群列表（使用缓存）
        admin_groups = await get_admin_groups(bot)
        
        if not admin_groups:
            logger.warning("机器人没有任何群的管理权限，跳过踢人")
            return
        
        kicked_count = 0
        kicked_groups = []  # 收集被踢出的群信息
        
        for group_id in admin_groups:
            try:
                # 检查用户是否在该群中
                try:
                    member_info = await bot.get_group_member_info(
                        group_id=group_id, 
                        user_id=int(user_id),
                        no_cache=True
                    )
                    
                    # 如果用户在群中，踢出
                    await bot.set_group_kick(
                        group_id=group_id,
                        user_id=int(user_id),
                        reject_add_request=True
                    )
                    
                    logger.success(f"已将新增黑名单用户 {user_id} 踢出群 {group_id}, 原因: {reason or '无'}")
                    kicked_count += 1
                    kicked_groups.append(group_id)
                    
                except Exception:
                    # 用户不在该群中，跳过
                    continue
                    
            except Exception as group_error:
                logger.debug(f"检查群 {group_id} 中用户 {user_id} 时出错: {group_error}")
        
        # 如果踢出了用户，发送报备消息
        if kicked_count > 0:
            logger.info(f"新增黑名单用户 {user_id} 已从 {kicked_count} 个群中踢出")
            
            # 构建踢出用户信息并发送报备
            kicked_users = {
                user_id: {
                    "reason": reason or "无",
                    "groups": kicked_groups
                }
            }
            await send_report_to_superusers(kicked_users)
            
    except Exception as e:
        logger.error(f"踢出特定用户失败: {e}")