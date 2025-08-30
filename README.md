# NoneBot 分布式黑名单插件

✨ 基于 PostgreSQL 的分布式黑名单系统，支持多客户端名单同步 ✨

## 功能特性

- 🚀 **高性能内存缓存**: 使用高效的二叉树结构实现毫秒级黑名单检查
- 🌐 **分布式架构**: 基于 PostgreSQL 的中心化数据存储，支持多节点部署
- ⚡ **实时同步**: 自动同步黑名单变更，确保所有节点数据一致
- 🛡️ **自动防护**: 定时检查群成员，自动踢出黑名单用户
- 📊 **操作日志**: 完整的操作记录和版本控制

## 系统架构

本插件采用**Hub-and-Spoke**（中心辐射）架构：

- **Hub（中心节点）**: PostgreSQL 数据库，作为唯一数据源
- **Spoke（边缘节点）**: 各个 NoneBot 实例，维护本地高速缓存

```
         PostgreSQL Hub
              |
    +---------+---------+
    |         |         |
  Bot A     Bot B     Bot C
 (Cache)   (Cache)   (Cache)
```

## 💿 安装

<details open>
<summary>使用 pip 安装</summary>

```bash
pip install nonebot-plugin-distributed-blacklist
```

</details>

<details>
<summary>从源码安装</summary>

```bash
git clone https://github.com/tisd0/nonebot-plugin-distributed-blacklist.git
cd nonebot-plugin-distributed-blacklist
pip install -e .
```

</details>

## 📊 数据库配置

本插件使用 PostgreSQL 数据库。在首次运行前，你需要完成数据库的初始化。

### 1. 创建数据库

首先，请在你的 PostgreSQL 服务中创建一个新的数据库。命令行示意：

```bash
psql -U blacklist_user
CREATE DATABASE distributed_blacklist OWNER blacklist_user;
\q
```

### 2. 初始化脚本

我们提供了一个初始化脚本 `init_db.sql` 来为你创建所有必需的数据表和索引。请使用 `psql` 命令行工具来执行它。

这是最推荐的方式：

```bash
psql -U blacklist_user -d distributed_blacklist -f /path/to/your/init_db.sql
```

执行成功且没有报错，则你的数据库已经准备就绪，可以配置插件并启动你的机器人了。

## ⚙️ 配置

在 NoneBot 配置文件中添加以下配置：

| 配置项 | 必填 | 默认值 | 说明 |
|:-----:|:----:|:----:|:----:|
| `distributed_blacklist_db_host` | 否 | localhost | PostgreSQL 服务器地址 |
| `distributed_blacklist_db_port` | 否 | 5432 | PostgreSQL 端口 |
| `distributed_blacklist_db_name` | 否 | blacklist | 数据库名称 |
| `distributed_blacklist_db_user` | 否 | blacklist | 数据库用户名 |
| `distributed_blacklist_db_password` | 否 | 无 | 数据库密码 |
| `distributed_blacklist_admins` | 否 | [] | 黑名单管理员QQ号列表 |
| `distributed_blacklist_sync_interval` | 否 | 300 | 同步间隔（秒） |
| `distributed_blacklist_kick_check_interval` | 否 | 3600 | 踢人检查间隔（秒） |
| `distributed_blacklist_db_max_connections` | 否 | 10 | 最大数据库连接数 |
| `distributed_blacklist_db_min_connections` | 否 | 2 | 最小数据库连接数 |
| `distributed_blacklist_enable_auto_kick` | 否 | true | 启用定时踢人功能 |
| `distributed_blacklist_debug_mode` | 否 | false | 调试模式，启用详细日志输出 |
| `distributed_blacklist_check_global` | 否 | false | 阻断黑名单用户指令 |

### 配置示例

```
# .env 文件
DISTRIBUTED_BLACKLIST_DB_HOST=your_database_host
DISTRIBUTED_BLACKLIST_DB_PORT=5432
DISTRIBUTED_BLACKLIST_DB_NAME=blacklist
DISTRIBUTED_BLACKLIST_DB_USER=blacklist
DISTRIBUTED_BLACKLIST_DB_PASSWORD=your_password
DISTRIBUTED_BLACKLIST_ADMINS=[123456789, 987654321]  # 管理员QQ号列表

DISTRIBUTED_BLACKLIST_CHECK_GLOBAL=true
DISTRIBUTED_BLACKLIST_ENABLE_AUTO_KICK=true
DISTRIBUTED_BLACKLIST_SYNC_INTERVAL=300
DISTRIBUTED_BLACKLIST_KICK_CHECK_INTERVAL=3600
DISTRIBUTED_BLACKLIST_DEBUG_MODE=false
```

## 🎉 使用

### 指令表

以下指令默认都需要命令前缀，请根据自己的设置添加命令前缀，下略。

| 指令 | 别名 | 权限 | 范围 | 说明 |
|:---:|:---:|:---:|:---:|:---:|
| `添加黑名单 <QQ号> [原因]` | `加黑`, `上黑`, `加黑名单` | `SUPERUSER` 或 `DISTRIBUTED_BLACKLIST_ADMINS` | 群聊 或 私聊 | 添加用户到黑名单 |
| `删除黑名单 <QQ号>` | `删黑`, `下黑`, `删黑名单` | `SUPERUSER` 或 `DISTRIBUTED_BLACKLIST_ADMINS` | 群聊 或 私聊 | 从黑名单移除用户 |
| `搜索黑名单 <QQ号>` | `查黑`, `查询黑名单`, `查找黑名单` | `SUPERUSER` 或 `DISTRIBUTED_BLACKLIST_ADMINS` | 群聊 或 私聊 | 查询用户是否在黑名单中 |
| `同步黑名单` | 无 | `SUPERUSER` 或 `DISTRIBUTED_BLACKLIST_ADMINS` | 群聊 或 私聊 | 手动触发黑名单同步 |

### 使用说明

插件会在每次启动的第一次触发踢人时，检查所有所在群的权限。后续只从机器人是管理或群主的群检查黑名单。若在机器人已经缓存管理数据后才给机器人管理，则需要重启`Nonebot`并重新触发踢人流程。

黑名单数据使用增量同步，若增量同步出现问题，请删除`LocalStore`提供的插件数据目录下的`blacklist_data.json`。

### 使用示例

```
# 添加黑名单
添加黑名单 123456789 恶意刷屏

# 删除黑名单
删除黑名单 123456789

# 搜索黑名单
搜索黑名单 123456789

# 同步黑名单
同步黑名单
```

## 📄 许可证

LGPLv3

## 致谢

- 感谢 [nonebot-plugin-easy-blacklist](https://github.com/bingqiu456/nonebot-plugin-easy-blacklist) 提供黑名单部分逻辑实现