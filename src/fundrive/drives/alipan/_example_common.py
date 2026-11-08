"""阿里云盘示例共用的文件操作演示。"""

import argparse
import os
import tempfile
from uuid import uuid4

from farlog import getLogger

logger = getLogger("fundrive.alipan.example")


def run_comprehensive_test(drive, drive_name):
    """运行完整的驱动功能测试"""
    logger.info(f"\n🧪 开始 {drive_name} 完整功能测试...")

    test_results = []

    # 测试1: 登录认证
    logger.info("\n1️⃣ 测试登录认证...")
    try:
        result = drive.login()
        if result:
            logger.info("✅ 登录成功")
            test_results.append(("登录认证", True))
        else:
            logger.error("❌ 登录失败")
            test_results.append(("登录认证", False))
            return test_results
    except Exception as e:
        logger.error(f"❌ 登录异常: {e}")
        test_results.append(("登录认证", False))
        return test_results

    # 测试2: 获取根目录文件列表
    logger.info("\n2️⃣ 测试获取文件列表...")
    try:
        files = drive.get_file_list("root")
        logger.info(f"✅ 获取到 {len(files)} 个文件")
        test_results.append(("获取文件列表", True))
    except Exception as e:
        logger.error(f"❌ 获取文件列表失败: {e}")
        test_results.append(("获取文件列表", False))

    # 测试3: 获取根目录列表
    logger.info("\n3️⃣ 测试获取目录列表...")
    try:
        dirs = drive.get_dir_list("root")
        logger.info(f"✅ 获取到 {len(dirs)} 个目录")
        test_results.append(("获取目录列表", True))
    except Exception as e:
        logger.error(f"❌ 获取目录列表失败: {e}")
        test_results.append(("获取目录列表", False))

    # 测试4: 创建测试目录
    test_dir_name = f"fundrive_test_{uuid4().hex}"
    test_dir_fid = None
    logger.info(f"\n4️⃣ 测试创建目录: {test_dir_name}")
    try:
        result = drive.mkdir("root", test_dir_name)
        if result:
            test_dir_fid = result
            logger.info("✅ 目录创建成功")
            test_results.append(("创建目录", True))
        else:
            logger.error("❌ 目录创建失败")
            test_results.append(("创建目录", False))
    except Exception as e:
        logger.error(f"❌ 创建目录失败: {e}")
        test_results.append(("创建目录", False))

    # 测试5: 创建测试文件并上传
    logger.info("\n5️⃣ 测试文件上传...")
    test_content = (
        f"这是{drive_name}的测试文件内容\n测试时间: {os.popen('date').read().strip()}"
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(test_content)
        temp_file = f.name

    test_file_name = os.path.basename(temp_file)
    test_file = None
    try:
        result = drive.upload_file(temp_file, "root")
        if result:
            logger.info("✅ 文件上传成功")
            test_results.append(("文件上传", True))
        else:
            logger.error("❌ 文件上传失败")
            test_results.append(("文件上传", False))
    except Exception as e:
        logger.error(f"❌ 文件上传异常: {e}")
        test_results.append(("文件上传", False))
    finally:
        os.unlink(temp_file)

    # 测试6: 检查文件是否存在
    logger.info("\n6️⃣ 测试文件存在性检查...")
    try:
        files = drive.get_file_list("root")
        test_file = next((file for file in files if file.name == test_file_name), None)
        exists = test_file is not None and drive.exist(test_file.fid)
        if exists:
            logger.info("✅ 文件存在性检查通过")
            test_results.append(("文件存在检查", True))
        else:
            logger.warning("⚠️ 文件不存在")
            test_results.append(("文件存在检查", False))
    except Exception as e:
        logger.error(f"❌ 文件存在检查失败: {e}")
        test_results.append(("文件存在检查", False))

    # 测试7: 获取文件信息
    logger.info("\n7️⃣ 测试获取文件信息...")
    try:
        if test_file:
            file_info = drive.get_file_info(test_file.fid)
            if file_info:
                logger.info(
                    f"✅ 文件信息: {file_info.name}, 大小: {file_info.size} 字节"
                )
                test_results.append(("获取文件信息", True))
            else:
                logger.error("❌ 获取文件信息失败")
                test_results.append(("获取文件信息", False))
        else:
            logger.warning("⚠️ 未找到测试文件")
            test_results.append(("获取文件信息", False))
    except Exception as e:
        logger.error(f"❌ 获取文件信息异常: {e}")
        test_results.append(("获取文件信息", False))

    # 测试8: 文件下载
    logger.info("\n8️⃣ 测试文件下载...")
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = drive.download_file(
                test_file.fid if test_file else "unknown",
                save_dir=temp_dir,
                filename="downloaded_test.txt",
            )
            if result:
                downloaded_file = os.path.join(temp_dir, "downloaded_test.txt")
                if os.path.exists(downloaded_file):
                    logger.info("✅ 文件下载成功")
                    test_results.append(("文件下载", True))
                else:
                    logger.error("❌ 下载的文件不存在")
                    test_results.append(("文件下载", False))
            else:
                logger.error("❌ 文件下载失败")
                test_results.append(("文件下载", False))
    except Exception as e:
        logger.error(f"❌ 文件下载异常: {e}")
        test_results.append(("文件下载", False))

    # 测试9: 清理测试文件
    logger.info("\n9️⃣ 清理测试文件...")
    try:
        if test_file:
            result = drive.delete(test_file.fid)
            if result:
                logger.info("✅ 测试文件删除成功")
                test_results.append(("删除文件", True))
            else:
                logger.error("❌ 测试文件删除失败")
                test_results.append(("删除文件", False))
        else:
            logger.warning("⚠️ 没有测试文件需要删除")
            test_results.append(("删除文件", True))
    except Exception as e:
        logger.error(f"❌ 删除文件异常: {e}")
        test_results.append(("删除文件", False))

    if test_dir_fid:
        try:
            drive.delete(test_dir_fid)
        except Exception as e:
            logger.error(f"❌ 清理测试目录失败: {e}")

    # 输出测试结果汇总
    logger.info(f"\n📊 {drive_name} 测试结果汇总:")
    passed = 0
    for test_name, result in test_results:
        status = "✅ 通过" if result else "❌ 失败"
        logger.info(f"  {test_name}: {status}")
        if result:
            passed += 1

    logger.info(f"\n🎯 总体结果: {passed}/{len(test_results)} 项测试通过")

    return test_results


def run_interactive_demo(drive, drive_name):
    """运行交互式演示"""
    logger.info("\n🎮 阿里云盘驱动交互式演示")
    logger.info("=" * 50)

    # 登录
    logger.info(f"\n🔐 正在登录 {drive_name}...")
    try:
        if not drive.login():
            logger.error("❌ 登录失败，退出演示")
            return
        logger.info("✅ 登录成功!")
    except Exception as e:
        logger.error(f"❌ 登录异常: {e}")
        return

    # 交互式操作循环
    while True:
        print(f"\n{drive_name} 可用操作:")
        print("1. 查看根目录文件")
        print("2. 查看根目录文件夹")
        print("3. 上传文件")
        print("4. 创建文件夹")
        print("5. 退出")

        choice = input("\n请选择操作 (1-5): ").strip()

        if choice == "1":
            try:
                files = drive.get_file_list("root")
                logger.info(f"\n📁 根目录文件列表 (共 {len(files)} 个):")
                for i, file in enumerate(files[:10], 1):  # 只显示前10个
                    logger.info(f"  {i}. {file.name} ({file.size} 字节)")
                if len(files) > 10:
                    logger.info(f"  ... 还有 {len(files) - 10} 个文件")
            except Exception as e:
                logger.error(f"❌ 获取文件列表失败: {e}")

        elif choice == "2":
            try:
                dirs = drive.get_dir_list("root")
                logger.info(f"\n📂 根目录文件夹列表 (共 {len(dirs)} 个):")
                for i, _dir in enumerate(dirs[:10], 1):  # 只显示前10个
                    logger.info(f"  {i}. {_dir.name}")
                if len(dirs) > 10:
                    logger.info(f"  ... 还有 {len(dirs) - 10} 个文件夹")
            except Exception as e:
                logger.error(f"❌ 获取文件夹列表失败: {e}")

        elif choice == "3":
            file_path = input("请输入要上传的文件路径: ").strip()
            if os.path.exists(file_path):
                try:
                    filename = os.path.basename(file_path)
                    result = drive.upload_file(file_path, "root", filename=filename)
                    if result:
                        logger.info(f"✅ 文件 {filename} 上传成功")
                    else:
                        logger.error(f"❌ 文件 {filename} 上传失败")
                except Exception as e:
                    logger.error(f"❌ 上传文件异常: {e}")
            else:
                logger.error("❌ 文件不存在")

        elif choice == "4":
            dir_name = input("请输入要创建的文件夹名称: ").strip()
            if dir_name:
                try:
                    result = drive.mkdir("root", dir_name)
                    if result:
                        logger.info(f"✅ 文件夹 {dir_name} 创建成功")
                    else:
                        logger.error(f"❌ 文件夹 {dir_name} 创建失败")
                except Exception as e:
                    logger.error(f"❌ 创建文件夹异常: {e}")
            else:
                logger.error("❌ 文件夹名称不能为空")

        elif choice == "5":
            logger.info("👋 退出交互式演示")
            break

        else:
            print("❌ 无效选择，请输入 1-5")


def main(drive_cls):
    parser = argparse.ArgumentParser(description=f"{drive_cls.__name__} 测试和演示")
    parser.add_argument(
        "--test", action="store_true", help="运行完整测试（会写入云盘）"
    )
    parser.add_argument("--interactive", action="store_true", help="运行交互式演示")
    args = parser.parse_args()

    if not args.test and not args.interactive:
        parser.print_help()
        return

    try:
        drive = drive_cls()
    except Exception as exc:
        logger.error(f"创建 {drive_cls.__name__} 失败: {exc}")
        return

    if args.test:
        results = run_comprehensive_test(drive, drive_cls.__name__)
        if not all(passed for _, passed in results):
            raise SystemExit(1)
    else:
        run_interactive_demo(drive, drive_cls.__name__)
