# FunDrive 优化功能使用指南

本文档介绍FunDrive项目最新的优化功能，包括统一的驱动管理、错误处理、性能优化工具等。

## 🚀 新增功能概览

### 1. 统一驱动管理

现在可以通过简单的字符串标识符来创建任何支持的云存储驱动：
```python
from fundrive import DRIVE_SPECS, get_drive, list_available_drives

# 查看所有可用驱动
available_drives = list_available_drives()
print(f"支持的驱动: {list(available_drives.keys())}")

# 获取驱动详细信息
for name, spec in DRIVE_SPECS.items():
    print(f"{name}: {spec.class_name}")

# 创建驱动实例
google_drive = get_drive('google', credentials_file='path/to/creds.json')
dropbox_drive = get_drive('dropbox', access_token='your_token')
s3_drive = get_drive('s3', access_key_id='key', secret_access_key='secret')
```

### 2. 统一异常处理

新的异常体系提供更精确的错误信息和处理：

```python
from fundrive import (
    get_drive, 
    AuthenticationError, 
    NetworkError, 
    FileNotFoundError,
    RateLimitError
)

try:
    drive = get_drive('google')
    drive.login()
    drive.upload_file('/local/file.txt', 'root', 'remote_file.txt')
    
except AuthenticationError as e:
    print(f"认证失败: {e}")
    print(f"错误代码: {e.error_code}")
    
except NetworkError as e:
    print(f"网络错误: {e}")
    
except FileNotFoundError as e:
    print(f"文件不存在: {e}")
    print(f"文件路径: {e.file_path}")
    
except RateLimitError as e:
    print(f"请求频率过高: {e}")
    if e.retry_after:
        print(f"建议等待 {e.retry_after} 秒后重试")
```

### 3. 自动重试机制

使用装饰器为函数添加自动重试功能：

```python
from fundrive.core.exceptions import NetworkError, RateLimitError, retry_on_error

class MyDrive:
    @retry_on_error(
        max_retries=3,
        delay=1.0,
        backoff_factor=2.0,
        exceptions=(NetworkError, RateLimitError)
    )
    def upload_with_retry(self, file_path):
        # 上传逻辑，遇到网络错误或频率限制会自动重试
        return self.upload_file(file_path)
```

### 4. 结果缓存

使用缓存装饰器提高重复操作的性能：

```python
from fundrive.core.utils import cache_result

class MyDrive:
    @cache_result(max_size=100, ttl=300)  # 缓存100个结果，5分钟过期
    def get_file_info_cached(self, file_id):
        # 文件信息会被缓存，避免重复API调用
        return self.get_file_info(file_id)
    
    def clear_cache(self):
        # 清空缓存
        self.get_file_info_cached.cache_clear()
    
    def get_cache_stats(self):
        # 获取缓存统计
        return self.get_file_info_cached.cache_stats()
```

### 5. 速率限制

控制API调用频率，避免触发服务端限制：

```python
from fundrive.core.utils import rate_limit

class MyDrive:
    @rate_limit(max_calls=100, time_window=60.0)  # 每分钟最多100次调用
    def api_call(self):
        # API调用会受到速率限制保护
        pass
    
    def get_rate_stats(self):
        # 获取速率限制统计
        return self.api_call.rate_stats()
```

### 6. 进度跟踪

跟踪文件上传/下载进度：

```python
from fundrive.core.utils import ProgressTracker

def upload_with_progress(drive, file_path, remote_path):
    file_size = os.path.getsize(file_path)
    tracker = ProgressTracker(file_size, "上传文件")
    
    # 添加进度回调
    def progress_callback(tracker):
        print(f"\r{tracker} - 速度: {tracker.current/tracker.elapsed_time:.1f} B/s", end="")
    
    tracker.add_callback(progress_callback)
    
    # 模拟上传过程
    with open(file_path, 'rb') as f:
        while chunk := f.read(8192):
            # 上传数据块
            # ... 实际上传逻辑 ...
            tracker.update(len(chunk))
    
    print(f"\n上传完成！总耗时: {tracker.elapsed_time:.2f} 秒")
```

### 7. 工具函数

新增的实用工具函数：

```python
from fundrive import format_size, parse_size, sanitize_filename, get_file_hash

# 格式化文件大小
print(format_size(1536))  # "1.50 KB"
print(format_size(1073741824))  # "1.00 GB"

# 解析大小字符串
size_bytes = parse_size("1.5GB")  # 1610612736
size_bytes = parse_size("500MB")  # 524288000

# 清理文件名
clean_name = sanitize_filename("file<>name?.txt")  # "file__name_.txt"

# 计算文件哈希
file_hash = get_file_hash("/path/to/file.txt", algorithm="md5")
print(f"文件MD5: {file_hash}")
```

### 8. 连接池管理

对于需要频繁创建连接的场景：

```python
from fundrive.core.utils import ConnectionPool
import requests

# 创建HTTP连接池
def create_session():
    session = requests.Session()
    session.headers.update({'User-Agent': 'FunDrive/2.0'})
    return session

pool = ConnectionPool(create_session, max_size=10)

# 使用连接
session = pool.get_connection()
try:
    response = session.get('https://api.example.com/data')
    # 处理响应...
finally:
    pool.return_connection(session)

# 获取连接池统计
stats = pool.stats()
print(f"连接池状态: {stats}")
```

## 🔧 高级用法示例

### 组合使用多个优化功能

```python
from fundrive import get_drive
from fundrive.core.exceptions import (
    NetworkError,
    RateLimitError,
    handle_api_errors,
    log_operation,
    retry_on_error,
)
from fundrive.core.utils import cache_result, rate_limit

class OptimizedDrive:
    def __init__(self, drive_type, **kwargs):
        self.drive = get_drive(drive_type, **kwargs)
    
    @log_operation("文件上传")
    @retry_on_error(max_retries=3, exceptions=(NetworkError, RateLimitError))
    @rate_limit(max_calls=50, time_window=60.0)
    @handle_api_errors
    def upload_file(self, local_path, remote_dir, filename=None):
        """优化的文件上传方法"""
        return self.drive.upload_file(local_path, remote_dir, filename)
    
    @cache_result(max_size=200, ttl=600)  # 缓存10分钟
    @handle_api_errors
    def get_file_info(self, file_id):
        """缓存的文件信息获取"""
        return self.drive.get_file_info(file_id)
    
    @log_operation("文件搜索")
    @cache_result(max_size=50, ttl=300)
    @handle_api_errors
    def search(self, keyword, **kwargs):
        """缓存的文件搜索"""
        return self.drive.search(keyword, **kwargs)

# 使用优化的驱动
drive = OptimizedDrive('dropbox', access_token='your_token')
drive.drive.login()

# 上传文件（带重试、速率限制、日志）
drive.upload_file('/local/file.txt', '/', 'remote_file.txt')

# 获取文件信息（带缓存）
file_info = drive.get_file_info('file_id')

# 搜索文件（带缓存）
results = drive.search('关键词')
```

### 批量操作优化

```python
from fundrive import get_drive, ProgressTracker
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

def batch_upload_optimized(drive, file_list, remote_dir, max_workers=5):
    """优化的批量上传"""
    
    # 计算总大小
    total_size = sum(os.path.getsize(f) for f in file_list)
    tracker = ProgressTracker(total_size, "批量上传")
    
    def upload_single_file(file_path):
        try:
            filename = os.path.basename(file_path)
            result = drive.upload_file(file_path, remote_dir, filename)
            file_size = os.path.getsize(file_path)
            tracker.update(file_size)
            return {'success': True, 'file': filename, 'result': result}
        except Exception as e:
            return {'success': False, 'file': filename, 'error': str(e)}
    
    # 并发上传
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(upload_single_file, file_path): file_path 
            for file_path in file_list
        }
        
        for future in as_completed(future_to_file):
            result = future.result()
            results.append(result)
            
            if result['success']:
                print(f"✅ {result['file']} 上传成功")
            else:
                print(f"❌ {result['file']} 上传失败: {result['error']}")
    
    print(f"\n批量上传完成！总耗时: {tracker.elapsed_time:.2f} 秒")
    success_count = sum(1 for r in results if r['success'])
    print(f"成功: {success_count}/{len(file_list)}")
    
    return results

# 使用示例
drive = get_drive('google', credentials_file='creds.json')
drive.login()

file_list = ['/path/to/file1.txt', '/path/to/file2.txt', '/path/to/file3.txt']
results = batch_upload_optimized(drive, file_list, 'root')
```

## 📊 性能监控

### 监控缓存效果

```python
# 获取缓存统计
cache_stats = drive.get_file_info.cache_stats()
print(f"缓存大小: {cache_stats['size']}/{cache_stats['max_size']}")
print(f"过期条目: {cache_stats['expired_count']}")

# 获取速率限制状态
rate_stats = drive.upload_file.rate_stats()
print(f"当前调用数: {rate_stats['active_calls']}/{rate_stats['max_calls']}")
print(f"剩余调用数: {rate_stats['remaining']}")
```

### 性能基准测试

```python
import time
from fundrive import get_drive

def benchmark_with_without_cache():
    drive = get_drive('dropbox', access_token='token')
    drive.login()
    
    file_ids = ['id1', 'id2', 'id3'] * 10  # 重复的文件ID
    
    # 不使用缓存
    start_time = time.time()
    for file_id in file_ids:
        drive.get_file_info(file_id)
    no_cache_time = time.time() - start_time
    
    # 使用缓存
    @cache_result(max_size=100, ttl=300)
    def get_file_info_cached(file_id):
        return drive.get_file_info(file_id)
    
    start_time = time.time()
    for file_id in file_ids:
        get_file_info_cached(file_id)
    cache_time = time.time() - start_time
    
    print(f"不使用缓存: {no_cache_time:.2f} 秒")
    print(f"使用缓存: {cache_time:.2f} 秒")
    print(f"性能提升: {(no_cache_time/cache_time):.1f}x")

# 运行基准测试
benchmark_with_without_cache()
```

## 🛡️ 最佳实践

1. **合理使用缓存**: 对于频繁访问的文件信息使用缓存，但注意TTL设置
2. **设置适当的重试策略**: 网络操作使用重试，但避免过度重试
3. **监控速率限制**: 定期检查API调用频率，避免触发限制
4. **使用进度跟踪**: 长时间操作提供用户反馈
5. **错误处理**: 使用具体的异常类型进行精确的错误处理
6. **连接池管理**: 频繁网络操作使用连接池提高效率

通过这些优化功能，FunDrive不仅提供了统一的云存储接口，还具备了企业级的性能和稳定性特性。
