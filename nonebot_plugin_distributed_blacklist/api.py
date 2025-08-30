import time
from nonebot.adapters.onebot.v11.event import Event
from . import core
from typing import List

# 全局黑名单缓存实例
core_list = core.blacklist()


def add_black(qq: str, time_val: int, reason: str, account: int) -> bool:
    """添加到内存缓存"""
    core.add_count += 1
    return core_list.add(qq, time_val, reason, account)


def del_black(user_id: str) -> bool:
    """从内存缓存删除"""
    core.del_count += 1
    return core_list.del_black(user_id)


def many_add(blacklist_data: List[List]) -> bool:
    """批量添加到内存缓存"""
    core.add_count += len(blacklist_data)
    return core_list.many_add(blacklist_data)


def many_del(user_ids: List[str]) -> List[bool]:
    """批量从内存缓存删除"""
    core.del_count += len(user_ids)
    return core_list.many_del(user_ids)


def search(user_id: str) -> List:
    """搜索用户是否在黑名单中"""
    core.search_time = int(time.time())
    core.sum_black += 1
    result = core_list.search(user_id)
    core.search_time_ = int(time.time())
    return result


def many_search(user_ids: List[str]) -> List[List]:
    """批量搜索"""
    core.sum_black += len(user_ids)
    return core_list.many_search(user_ids)


async def check_hmd(event: Event) -> bool:
    """检查用户是否为黑名单用户"""
    is_blacklisted: bool = search(event.get_user_id())[0]
    if not is_blacklisted:
        return True
    else:
        return False


def rebuild_cache_from_database(blacklist_data: List[tuple]):
    """从数据库数据重建缓存"""
    global core_list
    core_list.rebuild_from_data(blacklist_data)


def clear_cache():
    """清空缓存"""
    global core_list
    core_list.clear_cache()


def get_cache_stats() -> dict:
    """获取缓存统计信息"""
    return core_list.get_cache_stats()


def is_user_in_cache(user_id: str) -> bool:
    """检查用户是否在本地缓存中"""
    return search(user_id)[0]


def get_user_info_from_cache(user_id: str) -> dict:
    """从缓存获取用户详细信息"""
    result = search(user_id)
    if result[0]:
        return {
            "exists": True,
            "timestamp": result[1],
            "added_by": result[2], 
            "reason": result[3]
        }
    else:
        return {"exists": False}