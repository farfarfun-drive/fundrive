
# 说明
百度云盘的python-api，[官方API](https://openapi.baidu.com/wiki/index.php?title=docs/pcs/rest/file_data_apis_list)  


# 目录

|方法|描述|
|:--:|:--|
|[安装](#安装)|安装方式|
|[get_file_list](#查看目录)|查看该目录下有哪些文件|
|[get_file_info](#查看文件信息)|可以查看某个文件的具体信息|
|[upload_file](#上传单个文件)|上传单个文件|
|[download_file](#下载单个文件)|下载单个文件|
|[upload_dir](#upload_dir-上传文件夹)|上传文件夹|
|[download_dir](#download_dir-下载文件夹)|下载文件夹|


# 使用
获取百度 cookies 中的 BDUSS、STOKEN 和 PTOKEN 值，注意保密。

```python
from fundrive.drives.baidu import BaiDuDrive

client = BaiDuDrive()
client.login(
    bduss="XXXXXXXXXXXXXXXXXXXXXXXX",
    stoken="XXXXXXXXXXXXXXXXXXXXXXXX",
    ptoken="XXXXXXXXXXXXXXXXXXXXXXXX",
)
```

## 查看目录
```python
for file in client.get_file_list("/drive/example/api"):
    print(file.name)
```

## 查看文件信息
```python
print(client.get_file_info("/drive/example/api/test.txt"))
```

## 上传单个文件
```python
client.upload_file("test.txt", "/drive/example/api/test.txt", overwrite=False)
```

## 下载单个文件
```python
client.download_file(
    "/drive/example/api/test.txt", save_dir=".", filename="test2.txt", overwrite=False
)
```

## upload_dir 上传文件夹
```python
client.upload_dir(filedir="logs", fid="/drive/example/api/")
```

## download_dir 下载文件夹
```python
client.download_dir("/drive/example/api/", save_dir="logs")
```


# 参考
[baidupcsapi](https://github.com/ly0/baidupcsapi)
[baidu-pcs-python-sdk](https://github.com/mozillazg/baidu-pcs-python-sdk)


