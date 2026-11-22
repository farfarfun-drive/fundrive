# 中国移动云盘（CMCloud）

此驱动使用 [cm-cloud-manage](https://skillhub.cn/skills/org-vt43r0t0/cm-cloud-manage)
中的个人云文件接口。支持列目录、关键词搜索、文件详情、建目录、上传、下载和复制。删除、移动、改名及分享
不在该 Skill 当前文件能力范围内，驱动也没有实现这些操作。

```python
from fundrive.drives import get_drive

# 由你自己的已授权 IDaaS 集成提供；不要把票据写进源码或日志。
headers = {
    "creditToken": "...",
    "skillId": "...",
    "clientId": "...",
    "strategyId": "...",
    "clawUid": "...",
}
drive = get_drive("cmcloud", headers=headers)
if not drive.login():
    raise RuntimeError("移动云盘授权无效或已过期")

files = drive.get_file_list("/")  # 个人云根目录只读
drive.upload_file("report.pdf", drive.dedicated_root_fid)
```

`login()` 通过用户目录接口取得当前授权的智能体专属目录。上传、建目录和复制目标仅接受该目录及其
子目录的真实 `fid`；下载和列表可读取已授权的个人云内容。票据由调用方负责获取和刷新，
驱动不会读取 Skill 的本地凭据文件，也不会自动扫码或续期。上传使用 5 MiB 起的分片，
单文件当前限 5 GiB；后端使用 PDS 时传 `hash_algorithm="sha1"`，默认使用 `sha256`。
复制是异步任务；状态未知时异常包含任务 ID，不要直接重试提交。
