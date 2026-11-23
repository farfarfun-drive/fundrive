# 115 网盘（Pan115）

基于自主维护的 [`fundrive-pan115`](https://github.com/farfarfun-drive/fundrive-pan115)（`fundrives.pan115`）实现，需要 Python `>=3.12`。

## 安装

```bash
uv add "fundrive[pan115]"
```

## 快速开始

```python
from fundrive import get_drive

drive = get_drive("pan115")

# 方式一：直接传入 cookies 字符串（推荐在服务端/脚本中使用，切勿写入日志或源码）
drive.login(cookies="UID=...; CID=...; SEID=...; KID=...")

# 方式二：不传参数，读取 ~/115-cookies.txt 并以 qandroid 扫码/续期登录
# drive.login()

# 根目录 fid 为 "0"，支持自动拉取全部分页与单页 timeout 透传
entries = drive.get_all_list("0", timeout=10)
files = drive.get_file_list("0", timeout=10)
dirs = drive.get_dir_list("0", timeout=10)

cid = drive.mkdir("0", "demo")
drive.upload_file(filepath="local.txt", fid=cid)
```

## 约定与能力边界

- **ID 体系**：目录 ID 为 115 `cid`，文件 ID 为 `fid`，根目录统一为 `"0"`。
- **分页与超时**：`get_all_list(fid, timeout=..., limit=1150)` 自动按 `offset`/`limit` 拉取完整分页并将 `timeout` 透传给每一页请求。成功读取空目录返回 `[]`；分页超时、认证失败、响应缺条目或服务端分页未前进时会抛出异常，不会返回截断列表。
- **存在性判断**：`exist(fid)` 仅在 SDK 明确返回 `FileNotFoundError`（`P115FileNotFoundError`）或空数据时返回 `False`；网络、认证或 SDK 异常会包装为 `FunDriveError` 抛出。
- **支持的操作**：`login`、`mkdir`、`exist`、`delete`、`get_all_list`、`get_file_list`、`get_dir_list`、`get_file_info`、`get_dir_info`、`upload_file`、`download_file`、`get_download_url`、`search`、`move`、`rename`、`get_quota`、`save_shared`。
