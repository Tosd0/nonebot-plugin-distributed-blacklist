from typing import List

add_count = 0
del_count = 0
sum_black = 0

search_time = 0
search_time_ = 0


class blacklist(object):
    """分布式黑名单系统核心数据结构"""

    def __init__(self):
        self.x = -1
        self.y = -1
        self.arg = False
        self.time = None
        self.reason = ""
        self.account = -1

    def add(self, qq: str, time: int, reason: str, account: int) -> bool:
        """
        添加qq号到内存缓存
        qq: str
        """
        current_node = self
        qq_binary = bin(int(qq))[2:]
        for bit_char in qq_binary:
            bit = int(bit_char)
            if bit == 0:
                if current_node.x == -1:
                    current_node.x = blacklist()
                current_node = current_node.x

            if bit == 1:
                if current_node.y == -1:
                    current_node.y = blacklist()
                current_node = current_node.y
        current_node.arg = True
        current_node.time = time
        current_node.reason = reason
        current_node.account = account
        return True

    def search(self, qq: str) -> List:
        """
        搜索qq号
        返回 [bool, timestamp, account, reason]
        True代表存在 False代表不存在
        """
        try:
            index = 0
            current_node = self
            qq_binary = bin(int(qq))[2:]
            while index < len(qq_binary):
                bit = int(qq_binary[index])
                if bit == 1:
                    if current_node.y == -1:
                        return [False]
                    else:
                        current_node = current_node.y
                else:
                    if current_node.x == -1:
                        return [False]
                    else:
                        current_node = current_node.x
                index += 1
            return [current_node.arg, current_node.time, current_node.account, current_node.reason]
        except (ValueError, AttributeError):
            return [False]

    def many_add(self, blacklist_data: List[List]) -> bool:
        """
        批量添加
        """
        for data_entry in blacklist_data:
            if len(data_entry) >= 4:
                self.add(str(data_entry[0]), data_entry[1], data_entry[2], data_entry[3])
        return True

    def many_search(self, user_ids: List[str]) -> List[List]:
        """
        批量搜索
        """
        results = []
        for user_id in user_ids:
            results.append(self.search(user_id))
        return results

    def del_black(self, qq: str) -> bool:
        """
        从内存缓存删除qq号
        """
        try:
            current_node = self
            qq_binary = bin(int(qq))[2:]
            
            # 如果只有一个节点，直接删除
            if len(qq_binary) == 1:
                if qq_binary == "0":
                    if hasattr(self, 'x') and self.x != -1:
                        self.x.arg = False
                        if self.x.x == -1 and self.x.y == -1:
                            self.x = -1
                else:  # qq_binary == "1"
                    if hasattr(self, 'y') and self.y != -1:
                        self.y.arg = False
                        if self.y.x == -1 and self.y.y == -1:
                            self.y = -1
                return True
            
            # 遍历到倒数第二个节点
            for bit_index in range(0, len(qq_binary) - 1):
                if qq_binary[bit_index] == "0":
                    if current_node.x == -1:
                        return False
                    current_node = current_node.x
                else:
                    if current_node.y == -1:
                        return False
                    current_node = current_node.y

            # 处理最后一个节点
            if qq_binary[-1] == "0":
                if current_node.x != -1:
                    current_node.x.arg = False
                    # 如果子节点为空，删除节点
                    if current_node.x.y == -1 and current_node.x.x == -1:
                        current_node.x = -1
            else:  # qq_binary[-1] == "1"
                if current_node.y != -1:
                    current_node.y.arg = False
                    # 如果子节点为空，删除节点
                    if current_node.y.x == -1 and current_node.y.y == -1:
                        current_node.y = -1

            return True
        except (ValueError, AttributeError):
            return False

    def many_del(self, user_ids: List[str]) -> List[bool]:
        """
        批量删除
        """
        results = []
        for user_id in user_ids:
            results.append(self.del_black(user_id))
        return results

    def clear_cache(self):
        """清空内存缓存"""
        self.x = -1
        self.y = -1
        self.arg = False
        self.time = None
        self.reason = ""
        self.account = -1

    def rebuild_from_data(self, blacklist_data: List[tuple]):
        """从数据库数据重建内存缓存"""
        self.clear_cache()
        for user_id, timestamp, added_by, reason in blacklist_data:
            self.add(str(user_id), timestamp, reason, added_by)

    def get_cache_stats(self) -> dict:
        """获取缓存统计信息"""
        return {
            "add_count": add_count,
            "del_count": del_count,
            "search_count": sum_black,
            "last_search_time": search_time_
        }