from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):  
    # PostgreSQL数据库配置
    distributed_blacklist_db_host: str = "localhost"
    distributed_blacklist_db_port: int = 5432
    distributed_blacklist_db_name: str = "blacklist"
    distributed_blacklist_db_user: str = "blacklist"
    distributed_blacklist_db_password: str = ""
    
    # 权限配置
    distributed_blacklist_admins: list = []  # 黑名单管理员QQ号列表
    
    # 同步配置
    distributed_blacklist_sync_interval: int = 300  # 同步间隔（秒）
    distributed_blacklist_kick_check_interval: int = 3600  # 踢人检查间隔（秒）
    
    # 连接池配置
    distributed_blacklist_db_max_connections: int = 10
    distributed_blacklist_db_min_connections: int = 2
    
    # 启用定时踢人
    distributed_blacklist_enable_auto_kick: bool = True
    
    # 调试模式
    distributed_blacklist_debug_mode: bool = False
    
    # 全局检测开关
    distributed_blacklist_check_global: bool = False


config = get_plugin_config(Config)