---
title: Linux 操作指令合集（分类速查）
date: 2026-10-29 15:00:00
description: 一份按场景分类的 Linux 常用命令速查表：文件目录、查看编辑、权限用户、文本三剑客、系统进程、磁盘内存、网络、压缩归档、包管理、服务与定时任务、Shell 效率技巧，并附危险操作清单。
categories:
  - 技术
tags:
  - Linux
  - 命令
  - 速查
cover: /img/cover-linux.jpg
---

## 写在前面

这份合集按"做什么事"来分类，而不是按字母排。每条都给最常用形态，想深入再 `man 命令` 或 `命令 --help`。适合部署后端服务（前面那些 Node/Java 框架）时随手查。

{% note info %}
通用约定：`[]` 可选、`<> ` 占位、`|` 管道、`.` 当前目录、`~` 家目录、`*` 通配。下面命令默认在 Bash/Zsh。
{% endnote %}

## 一、文件与目录

| 命令 | 作用 |
| --- | --- |
| `ls -lah` | 列出文件（含隐藏、人类可读大小） |
| `pwd` | 当前绝对路径 |
| `cd -` | 回到上一个目录 |
| `mkdir -p a/b/c` | 递归建目录 |
| `touch file` | 新建空文件 / 更新时间戳 |
| `cp -r src dst` | 递归复制 |
| `mv a b` | 移动 / 重命名 |
| `rm -rf dir` | **递归强制删除（危险，见文末）** |
| `ln -s /real /link` | 建软链接 |
| `tree -L 2` | 树状展示（需安装） |

批量按时间清理日志：

```bash
find /var/log -name "*.log" -mtime +7 -delete        # 删 7 天前的 .log
find . -type f -size +100M -exec rm -i {} \;        # 删大于 100M 的文件（交互确认）
```

## 二、查看与编辑

| 命令 | 作用 |
| --- | --- |
| `cat f` | 一次性输出全文 |
| `less f` | 分页查看（空格翻页，`q` 退出） |
| `head -n 20 f` | 看前 20 行 |
| `tail -n 100 f` | 看末尾 100 行 |
| `tail -f f` | **实时跟踪**文件变化（看日志神器） |
| `wc -l f` | 统计行数 |
| `diff a b` | 比对两文件差异 |
| `vim / nano f` | 编辑（应急用 `nano` 更简单） |

```bash
tail -f /var/log/nginx/error.log      # 边访问边看报错
head -n 50 app.log | tail -n 20       # 取第 31~50 行
```

## 三、权限与用户

| 命令 | 作用 |
| --- | --- |
| `chmod 755 f` | 改权限（r=4 w=2 x=1） |
| `chmod +x f` | 加可执行 |
| `chown user:group f` | 改属主 |
| `sudo cmd` | 以管理员执行 |
| `su - user` | 切换用户并加载环境 |
| `useradd -m u` | 建用户（带家目录） |
| `passwd u` | 改密码 |
| `whoami` / `id` | 当前身份 |

{% note warning %}
别随手 `chmod 777`！它等于"所有人可读写执行"，只应在明确需要共享的目录临时使用，正常服务文件 644、可执行脚本 755 即可。
{% endnote %}

## 四、文本处理（三剑客）

**grep 搜索**

```bash
grep -rn "timeout" src/          # 递归、显示行号搜关键字
grep -iE "error|fail" app.log    # 忽略大小写 + 正则（或）
grep -v "^#" conf.yml            # 反向：排除注释行
```

**sed 替换**（流编辑，默认只打印不改文件，加 `-i` 才原地改）

```bash
sed 's/old/new/g' f              # 把 old 换成 new（全局）
sed -i 's/3000/8080/g' .env     # 原地改配置
sed -n '10,20p' f                # 打印 10~20 行
```

**awk 按列处理**（默认以空格/Tab 切分，`$1` 第一列，`$NF` 最后一列）

```bash
awk '{print $1, $NF}' f          # 打印首列和末列
awk -F: '$3>1000 {print $1}' /etc/passwd   # 指定分隔符:
ps aux | awk '$3>50 {print $2, $11}'       # 打印 CPU 占用高的进程 PID 与命令
```

## 五、系统信息与进程

| 命令 | 作用 |
| --- | --- |
| `uname -a` | 内核 / 系统信息 |
| `uptime` | 运行时长与负载 |
| `top` / `htop` | 实时进程（htop 更友好，需装） |
| `ps aux \| grep nginx` | 查进程 |
| `kill -15 PID` | 优雅终止（SIGTERM） |
| `kill -9 PID` | **强制杀死**（SIGKILL，最后手段） |
| `pkill -f "node server"` | 按名字批量杀 |
| `lsof -i :3000` | 谁占用了 3000 端口 |

```bash
ps aux --sort=-%mem | head -6      # 按内存占用排序，看前 5
kill -9 $(lsof -t -i:3000)        # 释放被占用的端口
```

## 六、磁盘与内存

| 命令 | 作用 |
| --- | --- |
| `df -h` | 各挂载点磁盘占用 |
| `du -sh *` | 当前目录各项大小 |
| `du -sh /var/log` | 某目录总大小 |
| `free -h` | 内存与交换区 |
| `lsblk` | 块设备（磁盘/分区） |
| `mount /dev/sdb1 /data` | 挂载 |
| `fdisk -l` | 查看分区表 |

{% note info %}
`df` 看"分区的盘"，`du` 看"目录的文件"。磁盘满了先 `du -sh /*` 定位大目录，别上来就乱删。
{% endnote %}

## 七、网络

| 命令 | 作用 |
| --- | --- |
| `ip a` / `ifconfig` | 网卡与 IP |
| `ping host` | 连通性 |
| `curl -I url` | 只看响应头 |
| `curl -X POST -d 'a=1' url` | POST 请求 |
| `wget -c url` | 断点续传下载 |
| `ss -tulnp` | 监听端口（替代 netstat） |
| `scp f user@h:/path` | 远程拷贝 |
| `ssh user@host` | 登录远程 |
| `dig / nslookup` | DNS 解析 |

```bash
curl -s https://api.github.com | head -c 200        # -s 静默，省进度条
ss -tulnp | grep :443                              # 确认 443 在监听
scp -r ./dist user@server:/var/www/app             # 部署前端产物
```

## 八、压缩与归档

| 命令 | 作用 |
| --- | --- |
| `tar -czvf a.tar.gz dir/` | 打包并 gzip 压缩 |
| `tar -xzvf a.tar.gz` | 解压到当前目录 |
| `tar -tzvf a.tar.gz` | 只看内容不解压 |
| `zip -r a.zip dir/` | zip 压缩 |
| `unzip a.zip -d out/` | 解压到指定目录 |
| `gzip / gunzip` | 单文件压缩 |

{% note warning %}
解压别人给的压缩包，先 `tar -tzvf` 看一眼内容。曾有"路径穿越"压缩包（`../../etc/...`）覆盖系统文件，解到哪都要心里有数。
{% endnote %}

## 九、包管理

| 发行版 | 更新索引 | 安装 | 卸载 |
| --- | --- | --- | --- |
| Debian/Ubuntu | `apt update` | `apt install pkg` | `apt remove pkg` |
| RHEL/CentOS | `yum makecache` | `yum install pkg` | `yum remove pkg` |
| (新) RHEL | `dnf makecache` | `dnf install pkg` | `dnf remove pkg` |
| Arch | `pacman -Sy` | `pacman -S pkg` | `pacman -R pkg` |

```bash
apt update && apt install -y nginx      # 装并自动确认
dnf install -y nodejs npm                # 一条装 Node 运行时
```

## 十、服务与定时任务

| 命令 | 作用 |
| --- | --- |
| `systemctl status nginx` | 查服务状态 |
| `systemctl start/stop/restart nginx` | 启停重启 |
| `systemctl enable nginx` | 开机自启 |
| `journalctl -u nginx -f` | 看某服务日志（实时） |
| `crontab -e` | 编辑定时任务 |
| `crontab -l` | 列出当前任务 |

crontab 格式：`分 时 日 月 周 命令`

```bash
0 3 * * * /usr/bin/backup.sh          # 每天 3:00 备份
*/5 * * * * curl -fsS http://localhost/health || alert   # 每 5 分钟健康检查
```

## 十一、Shell 效率技巧

| 技巧 | 说明 |
| --- | --- |
| `history \| grep docker` | 搜历史命令 |
| `Ctrl+R` | 反向搜索历史 |
| `!!` | 重复上一条命令（常接 `sudo !!`） |
| `!$` | 上条命令的最后一个参数 |
| `alias ll='ls -lah'` | 设别名（写入 `~/.bashrc` 永久生效） |
| `export API_KEY=xxx` | 临时环境变量 |
| `cmd1 && cmd2` | 前成功才跑后 |
| `cmd1 \|\| cmd2` | 前失败才跑后 |
| `cmd > out.log 2>&1 &` | 后台跑并把输出写文件 |

```bash
alias ll='ls -lah'
export NODE_ENV=production
npm run build && pm2 restart all     # 构建成功才重启
```

## 危险操作清单（务必谨慎）

- **`rm -rf /` 或 `rm -rf ./*`**：`-r` 递归、`-f` 不确认，路径写错就全删。先 `ls` 确认再删。
- **`chmod -R 777 /`**：把整棵树权限放开，安全灾难，按目录最小授权。
- **`kill -9` 数据库进程**：强制中断可能丢数据/损坏文件，先 `kill -15` 给优雅退出机会。
- **`> file` 重定向**：会**直接清空**原文件，想追加用 `>>`；误用 `> config` 会抹掉配置。
- **`find / -name x -delete`**：范围写大（从 `/` 开始）会删系统文件，先不加 `-delete` 跑一遍看结果。
- **`mv a b /` 路径写反**：覆盖重要文件，移动前确认目标。
- **`tar` 解压未知包**：先 `tar -tzvf` 检查路径穿越。

> 黄金法则：**破坏性命令先 dry-run（预览），确认无误再执行；删前能备份就备份。**

## 参考

- [Linux 命令大全（鸟哥/man 风格）](https://man7.org/linux/man-pages/)
- [explainshell：把命令拆开讲给你听](https://explainshell.com/)
